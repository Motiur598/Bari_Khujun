"""Listings and the deals that hang on them stay consistent: deleting, editing seats, renting twice."""

from datetime import datetime, timedelta

import pytest
from bson import ObjectId
from support import DHAKA

pytestmark = pytest.mark.anyio


def editable_location(listing: dict) -> dict:
    # Division, district and upazila are worked out by the server from the pin; clients send the rest.
    return {key: value for key, value in listing["location"].items() if key not in ("division", "district", "upazila")}


async def book_visit(client, visitor, listing_id: str) -> str:
    starts = (datetime.now(DHAKA) + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    response = await client.post(
        "/marketplace/visits", json={"listing_id": listing_id, "starts_at": starts.isoformat(), "mode": "VIDEO"}, headers=visitor.auth
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestDeletingARental:
    async def test_open_requests_are_cancelled_refunded_and_their_code_dies(self, client, make, db):
        owner, tenant, visitor = await make.account("OWNER"), await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner, total_seats=4, available_seats=2)
        booking_id, token = await make.approved_booking(owner, tenant, listing_id)
        visit_id = await book_visit(client, visitor, listing_id)

        response = await client.delete(f"/rentals/{listing_id}", headers=owner.auth)

        assert response.status_code == 204
        booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
        assert (booking["status"], booking["escrow_status"], booking["is_open"], booking["qr"]) == ("CANCELLED", "REFUNDED", False, None)
        assert booking["escrow_ledger"][-1]["note"].startswith("The listing was removed")
        assert await db.qr_handshake_logs.count_documents({"booking_id": booking["_id"], "event": "REVOKED"}) == 1
        assert (await make.scan(tenant, token)).status_code == 409
        assert (await db.visit_slots.find_one({"_id": ObjectId(visit_id)}))["status"] == "CANCELLED"
        assert await db.listings.find_one({"_id": ObjectId(listing_id)}) is None

    async def test_a_listing_with_a_tenant_cannot_be_deleted(self, client, make, db):
        owner, tenant = await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        booking_id = await make.confirmed_lease(owner, tenant)
        listing_id = (await db.bookings.find_one({"_id": ObjectId(booking_id)}))["listing_id"]

        response = await client.delete(f"/rentals/{listing_id}", headers=owner.auth)

        assert response.status_code == 409
        listing = await db.listings.find_one({"_id": listing_id})
        assert listing is not None and "suspended" not in listing  # left as it was


class TestDeletingASale:
    async def offer(self, client, buyer, listing_id: str) -> dict:
        response = await client.post(
            "/marketplace/offers", json={"listing_id": listing_id, "offer_type": "PURCHASE", "amount": 13_500_000}, headers=buyer.auth
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def test_open_offers_close_and_visits_are_cancelled(self, client, make, db):
        owner, buyer = await make.account("OWNER"), await make.account("BUYER")
        listing_id = await make.sale_listing(owner, "Dhanmondi", 90.3742, 23.7461)
        offer = await self.offer(client, buyer, listing_id)
        visit_id = await book_visit(client, buyer, listing_id)

        assert (await client.delete(f"/marketplace/sale-listings/{listing_id}", headers=owner.auth)).status_code == 204
        assert (await db.offers.find_one({"_id": ObjectId(offer["id"])}))["status"] == "CLOSED"
        assert (await db.visit_slots.find_one({"_id": ObjectId(visit_id)}))["status"] == "CANCELLED"

    async def test_a_sale_with_an_accepted_offer_cannot_be_deleted(self, client, make, db):
        owner, buyer = await make.account("OWNER"), await make.account("BUYER")
        listing_id = await make.sale_listing(owner, "Dhanmondi", 90.3742, 23.7461)
        offer = await self.offer(client, buyer, listing_id)
        accepted = await client.post(f"/marketplace/offers/{offer['id']}/respond", json={"action": "ACCEPT"}, headers=owner.auth)
        assert accepted.status_code == 200, accepted.text

        assert (await client.delete(f"/marketplace/sale-listings/{listing_id}", headers=owner.auth)).status_code == 409
        listing = await db.listings.find_one({"_id": ObjectId(listing_id)})
        assert listing is not None and "suspended" not in listing


class TestSeatsAndLeases:
    async def test_a_tenant_cannot_take_a_second_lease_in_the_same_flat(self, client, make):
        owner, tenant = await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner, total_seats=4, available_seats=2)
        _, token = await make.approved_booking(owner, tenant, listing_id)
        assert (await make.scan(tenant, token)).status_code == 200

        response = await client.post(
            "/qr-handshake/bookings",
            json={"listing_id": listing_id, "move_in_date": make.move_in_date().isoformat(), "deposit_amount": 4000,
                  "payment_method": "BKASH", "payment_reference": "TRX12345"},
            headers=tenant.auth,
        )
        assert (response.status_code, response.json()["detail"]) == (409, "You already rent here")

    async def test_seats_held_by_tenants_cannot_be_offered_again(self, client, make):
        owner, tenant = await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner, total_seats=3, available_seats=2)
        _, token = await make.approved_booking(owner, tenant, listing_id)
        assert (await make.scan(tenant, token)).status_code == 200
        listing = (await client.get(f"/rentals/{listing_id}")).json()
        payload = {key: listing[key] for key in ("category", "title", "description", "pricing", "building", "house_rules", "available_from")}
        payload["location"] = editable_location(listing)


        everything_free = {**payload, "seats": {"total_seats": 3, "available_seats": 3, "flatmates": []}}
        refused = await client.put(f"/rentals/{listing_id}", json=everything_free, headers=owner.auth)
        within_limit = {**payload, "seats": {"total_seats": 3, "available_seats": 2, "flatmates": []}}
        allowed = await client.put(f"/rentals/{listing_id}", json=within_limit, headers=owner.auth)

        assert refused.status_code == 409 and "at most 2 can be free" in refused.json()["detail"]
        assert (allowed.status_code, allowed.json()["seats"]["available_seats"]) == (200, 2)

    async def test_the_listing_type_cannot_change_under_an_open_request(self, client, make):
        owner, tenant = await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner, total_seats=3, available_seats=1)
        await make.approved_booking(owner, tenant, listing_id)
        listing = (await client.get(f"/rentals/{listing_id}")).json()
        payload = {key: listing[key] for key in ("title", "description", "pricing", "building", "house_rules", "available_from")}
        payload["location"] = editable_location(listing)

        response = await client.put(f"/rentals/{listing_id}", json={**payload, "category": "BACHELOR_FLAT", "seats": None}, headers=owner.auth)
        assert response.status_code == 409
