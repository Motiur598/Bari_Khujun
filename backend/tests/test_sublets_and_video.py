"""A bachelor tenant's sublet (one seat, or rooms priced one by one, let by the seat or whole) and listing videos."""

from datetime import datetime

import pytest
from bson import ObjectId
from support import DHAKA, jpeg_bytes, rental_payload

from app.services.listings import backfill_sublets, photo_folder
from app.services.move_outs import process_due_move_outs

pytestmark = pytest.mark.anyio


def seat(rent: int = 4000, room_size: int = 2, **charges) -> dict:
    return {"let_type": "SEAT", "seat": {"room_size": room_size, "seat_rent": rent, **charges}, "flatmates": []}


def room(name: str, kind: str = "SINGLE", rent: int = 7000, seats: int = 1, **charges) -> dict:
    return {"name": name, "room_type": kind, "seats": seats, "seat_rent": rent, **charges}


def rooms(*entries: dict) -> dict:
    return {"let_type": "ROOMS", "rooms": list(entries), "flatmates": []}


def editable(listing: dict, sublet: dict) -> dict:
    payload = {key: listing[key] for key in ("category", "title", "description", "pricing", "building", "house_rules", "available_from")}
    payload["location"] = {key: value for key, value in listing["location"].items() if key not in ("division", "district", "upazila")}
    return {**payload, "sublet": sublet}


def sent_back(listing: dict, *keep: int) -> list[dict]:
    """The listing's rooms (those at the given positions) as the editor sends them back."""
    fields = ("id", "name", "room_type", "seats", "seat_rent", "service_charge", "utility_estimate", "maid_estimate")
    return [{key: listing["sublet"]["rooms"][index][key] for key in fields} for index in keep]


class TestPostingASublet:
    async def test_a_single_seat_is_priced_on_its_own(self, make):
        tenant = await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(tenant, seat(4000, utility_estimate=600))

        (only,) = listing["sublet"]["rooms"]
        assert listing["sublet"]["let_type"] == "SEAT" and listing["is_sublet"]
        assert (only["room_type"], only["room_size"], only["seats"], only["available_seats"], only["utility_estimate"]) == ("SEAT", 2, 1, 1, 600)
        assert (listing["effective_rent"], listing["pricing"]["base_rent"], listing["seats"]["split"]) == (4000, None, None)

    async def test_rooms_are_single_or_shared_each_with_its_own_rent(self, make):
        tenant = await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(tenant, rooms(room("Room 1"), room("Room 2", "SHARED", 4500, seats=2, utility_estimate=500)))

        single, shared = listing["sublet"]["rooms"]
        assert (single["room_type"], single["available_seats"], shared["seats"], shared["available_seats"]) == ("SINGLE", 1, 2, 2)
        assert (listing["effective_rent"], listing["seats"]["total_seats"], listing["seats"]["available_seats"]) == (4500, 3, 3)

    async def test_owners_keep_the_whole_flat_split_and_tenants_must_sublet(self, client, make):
        owner, tenant = await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        owner_listing = (await client.get(f"/rentals/{await make.seat_listing(owner)}")).json()
        assert (owner_listing["pricing"]["base_rent"], owner_listing["seats"]["split"]["per_seat_rent"], owner_listing["sublet"]) == (12000, 4000, None)

        as_owner = {**rental_payload(seats=None), "sublet": seat()}
        assert (await client.post("/rentals", json=as_owner, headers=owner.auth)).status_code == 400
        split_seats = rental_payload(seats={"total_seats": 3, "available_seats": 1, "flatmates": []})
        assert (await client.post("/rentals", json=split_seats, headers=tenant.auth)).status_code == 400

    async def test_rooms_cannot_outnumber_bedrooms_and_types_must_fit(self, client, make):
        tenant = await make.account("BACHELOR_TENANT")
        too_many = {**rental_payload(), "sublet": rooms(room("A"), room("B"), room("C"))}
        too_many["building"]["bedrooms"] = 2
        response = await client.post("/rentals", json=too_many, headers=tenant.auth)
        assert response.status_code == 422 and "at most that many rooms" in response.text
        for bad in (room("A", "SINGLE", seats=2), room("A", "SHARED", seats=1)):
            assert (await client.post("/rentals", json={**rental_payload(), "sublet": rooms(bad)}, headers=tenant.auth)).status_code == 422


class TestRentingFromASublet:
    async def test_the_single_seat_needs_no_room_named(self, client, make):
        lister, tenant = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, seat(4000))
        booking_id, token = await make.approved_booking(lister, tenant, listing["id"])
        assert (await make.scan(tenant, token)).status_code == 200

        booking = (await client.get(f"/qr-handshake/bookings/{booking_id}", headers=tenant.auth)).json()
        assert (booking["agreed_rent"], booking["unit"]["whole_room"], booking["unit"]["seats"]) == (4000, False, 1)
        after = (await client.get(f"/rentals/{listing['id']}")).json()
        assert (after["seats"]["available_seats"], after["rental_status"]) == (0, "RENTED")

    async def test_rooms_need_one_named_and_other_listings_take_none(self, make):
        lister, owner, tenant = await make.account("BACHELOR_TENANT"), await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Room 1")))
        response = await make.request_to_rent(tenant, listing["id"])
        assert response.status_code == 400 and "Choose the room" in response.json()["detail"]
        owner_listing = await make.seat_listing(owner)
        assert (await make.request_to_rent(tenant, owner_listing, room_id="a" * 32)).status_code == 400

    async def test_a_whole_shared_room_takes_every_seat_and_cancels_the_requests_it_beat(self, client, make, db):
        lister = await make.account("BACHELOR_TENANT")
        whole, seat_seeker, single_seeker, late = [await make.account("BACHELOR_TENANT") for _ in range(4)]
        listing = await make.sublet_listing(lister, rooms(room("Shared room", "SHARED", 4500, seats=2), room("Single room", rent=7000)))
        shared_id, single_id = (r["id"] for r in listing["sublet"]["rooms"])

        whole_id, token = await make.approved_booking(lister, whole, listing["id"], shared_id, whole_room=True)
        seat_request = (await make.request_to_rent(seat_seeker, listing["id"], shared_id)).json()
        single_request = (await make.request_to_rent(single_seeker, listing["id"], single_id)).json()
        booked = await db.bookings.find_one({"_id": ObjectId(whole_id)})
        assert booked["agreed_rent"] == 9000
        assert booked["unit"] == {"room_id": shared_id, "room_name": "Shared room", "seats": 2, "whole_room": True}
        assert (single_request["agreed_rent"], single_request["unit"]["whole_room"]) == (7000, True)

        assert (await make.scan(whole, token)).status_code == 200

        after = (await client.get(f"/rentals/{listing['id']}")).json()
        assert [r["available_seats"] for r in after["sublet"]["rooms"]] == [0, 1]
        assert (after["seats"]["available_seats"], after["rental_status"], after["effective_rent"]) == (1, "AVAILABLE", 7000)
        assert (await db.bookings.find_one({"_id": ObjectId(seat_request["id"])}))["status"] == "CANCELLED"
        assert (await db.bookings.find_one({"_id": ObjectId(single_request["id"])}))["status"] == "PENDING_OWNER"
        assert (await make.request_to_rent(late, listing["id"], shared_id)).status_code == 409

    async def test_a_whole_room_needs_every_seat_in_it_free(self, make):
        lister, first, second = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Shared room", "SHARED", 4500, seats=2)))
        shared_id = listing["sublet"]["rooms"][0]["id"]
        _, token = await make.approved_booking(lister, first, listing["id"], shared_id)
        assert (await make.scan(first, token)).status_code == 200

        response = await make.request_to_rent(second, listing["id"], shared_id, whole_room=True)
        assert response.status_code == 409 and "isn't completely free" in response.json()["detail"]

    async def test_moving_out_gives_the_room_back_and_bills_go_per_seat(self, client, make, db):
        lister, tenant = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Shared room", "SHARED", 4500, seats=2, service_charge=300)))
        booking_id, token = await make.approved_booking(lister, tenant, listing["id"], listing["sublet"]["rooms"][0]["id"], whole_room=True)
        assert (await make.scan(tenant, token)).status_code == 200

        today = datetime.now(DHAKA).date()
        bills = await client.post(
            "/operations/invoices/generate",
            json={"listing_id": listing["id"], "period": f"{make.move_in_date():%Y-%m}", "electricity": 600, "gas": 0, "water": 100},
            headers=lister.auth,
        )
        assert bills.status_code == 201, bills.text
        (invoice,) = bills.json()["created"]
        assert {line["key"]: line["amount"] for line in invoice["lines"]} == {"rent": 9000, "service_charge": 600, "electricity": 1200, "gas": 0, "water": 200}

        await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"move_out": {"move_out_date": today.isoformat()}}})
        assert await process_due_move_outs(today) == 1
        after = (await client.get(f"/rentals/{listing['id']}")).json()
        assert (after["sublet"]["rooms"][0]["available_seats"], after["seats"]["available_seats"], after["rental_status"]) == (2, 2, "AVAILABLE")

    async def test_a_rent_offer_in_the_chat_is_for_a_seat_or_room(self, client, make, db):
        lister, tenant = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Room 1", rent=6500)))
        room_id = listing["sublet"]["rooms"][0]["id"]
        proposal = {
            "listing_id": listing["id"], "room_id": room_id, "amount": 6000, "move_in_date": make.move_in_date().isoformat(),
            "deposit_amount": 6000, "payment_method": "BKASH", "payment_reference": "TRXCHAT101",
        }
        offer = await client.post("/chat/rent-offers", json=proposal, headers=tenant.auth)
        assert offer.status_code == 201, offer.text
        assert (offer.json()["listed_rent"], offer.json()["unit"]["room_name"]) == (6500, "Room 1")

        accepted = await client.post(f"/chat/rent-offers/{offer.json()['id']}/respond", json={"action": "ACCEPT"}, headers=lister.auth)
        assert accepted.status_code == 200, accepted.text
        booking = await db.bookings.find_one({"_id": ObjectId(accepted.json()["booking_id"])})
        assert (booking["agreed_rent"], booking["unit"]["room_id"]) == (6000, room_id)


class TestEditingASublet:
    async def test_rooms_keep_their_photos_and_a_requested_room_stays(self, client, make):
        lister, tenant = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Room A"), room("Room B")))
        room_a, room_b = listing["sublet"]["rooms"]
        upload = await client.post(
            f"/rentals/{listing['id']}/rooms/{room_b['id']}/photos", files=[("files", ("b.jpg", jpeg_bytes(), "image/jpeg"))], headers=lister.auth
        )
        photo_id = upload.json()["sublet"]["rooms"][1]["photos"][0]["id"]
        await make.request_to_rent(tenant, listing["id"], room_a["id"])

        refused = await client.put(f"/rentals/{listing['id']}", json=editable(listing, rooms(*sent_back(listing, 1))), headers=lister.auth)
        assert refused.status_code == 409 and "Room A has a tenant or an open request" in refused.json()["detail"]

        renamed = sent_back(listing, 0, 1)
        renamed[1] = {**renamed[1], "name": "Room B (balcony)", "seat_rent": 7500}
        edited = await client.put(f"/rentals/{listing['id']}", json=editable(listing, rooms(*renamed)), headers=lister.auth)
        assert edited.status_code == 200, edited.text
        kept = edited.json()["sublet"]["rooms"][1]
        assert (kept["id"], kept["name"], kept["photos"][0]["id"]) == (room_b["id"], "Room B (balcony)", photo_id)

    async def test_a_room_cannot_shrink_below_the_seats_tenants_hold(self, client, make):
        lister, tenant = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Shared room", "SHARED", 4500, seats=2)))
        _, token = await make.approved_booking(lister, tenant, listing["id"], listing["sublet"]["rooms"][0]["id"], whole_room=True)
        assert (await make.scan(tenant, token)).status_code == 200

        as_single = sent_back(listing, 0)
        as_single[0] = {**as_single[0], "room_type": "SINGLE", "seats": 1}
        response = await client.put(f"/rentals/{listing['id']}", json=editable(listing, rooms(*as_single)), headers=lister.auth)
        assert response.status_code == 409 and "hold 2 seats" in response.json()["detail"]

    async def test_sublets_from_before_become_a_single_seat_with_their_requests(self, client, make, db):
        lister, tenant = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, seat())
        booking_id = (await make.request_to_rent(tenant, listing["id"])).json()["id"]
        # How sublets used to be stored: the whole flat's costs, split per seat.
        await db.listings.update_one(
            {"_id": ObjectId(listing["id"])},
            {"$set": {"sublet": None, "pricing.base_rent": 16000, "pricing.utility_estimate": 2400,
                      "seats": {"total_seats": 4, "available_seats": 1, "flatmates": [],
                                "split": {"per_seat_rent": 4000, "per_seat_service_charge": 0, "per_seat_utility": 600, "per_seat_maid": 0, "per_seat_total": 4600}}}},
        )
        await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$unset": {"unit": ""}})

        await backfill_sublets()

        migrated = (await client.get(f"/rentals/{listing['id']}")).json()
        (only,) = migrated["sublet"]["rooms"]
        assert (migrated["sublet"]["let_type"], only["room_type"], only["seat_rent"], only["utility_estimate"]) == ("SEAT", "SEAT", 4000, 600)
        assert (migrated["pricing"]["base_rent"], migrated["seats"]["total_seats"], migrated["effective_rent"]) == (None, 1, 4000)
        assert (await db.bookings.find_one({"_id": ObjectId(booking_id)}))["unit"]["room_id"] == only["id"]


class TestRoomPhotos:
    async def test_rooms_have_their_own_photos_served_with_the_listing(self, client, make):
        lister = await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Room A"), room("Room B")))
        room_a = listing["sublet"]["rooms"][0]
        base = f"/rentals/{listing['id']}/rooms/{room_a['id']}/photos"

        uploaded = await client.post(base, files=[("files", ("a.jpg", jpeg_bytes(), "image/jpeg"))], headers=lister.auth)
        assert uploaded.status_code == 200, uploaded.text
        photo_id = uploaded.json()["sublet"]["rooms"][0]["photos"][0]["id"]
        assert uploaded.json()["photos"] == []
        assert (await client.get(f"/rentals/{listing['id']}/photos/{photo_id}")).status_code == 200

        too_many = [("files", (f"{i}.jpg", jpeg_bytes(), "image/jpeg")) for i in range(4)]
        assert (await client.post(base, files=too_many, headers=lister.auth)).status_code == 400

        # Taking Room A off the listing deletes its photos.
        edited = await client.put(f"/rentals/{listing['id']}", json=editable(listing, rooms(*sent_back(listing, 1))), headers=lister.auth)
        assert edited.status_code == 200, edited.text
        assert not (photo_folder(ObjectId(listing["id"])) / f"{photo_id}.jpg").exists()
        assert (await client.get(f"/rentals/{listing['id']}/photos/{photo_id}")).status_code == 404

    async def test_only_the_lister_can_add_room_photos(self, client, make):
        lister, stranger = await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing = await make.sublet_listing(lister, rooms(room("Room A")))
        photo = [("files", ("a.jpg", jpeg_bytes(), "image/jpeg"))]
        url = f"/rentals/{listing['id']}/rooms/{listing['sublet']['rooms'][0]['id']}/photos"
        assert (await client.post(url, files=photo, headers=stranger.auth)).status_code == 403
        assert (await client.post(f"/rentals/{listing['id']}/rooms/{'b' * 32}/photos", files=photo, headers=lister.auth)).status_code == 404


# ---------------------------------------------------------------- videos

LOCATION = b"+23.7275+090.3855/"


def box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def mp4_bytes(seconds: int = 12) -> bytes:
    """A tiny MP4 laid out like a phone recording: ftyp, a movie with a GPS tag in udta and a track meta box, media."""
    mvhd = box(b"mvhd", bytes(4) + bytes(8) + (1000).to_bytes(4, "big") + (seconds * 1000).to_bytes(4, "big") + bytes(80))
    trak = box(b"trak", box(b"tkhd", bytes(84)) + box(b"meta", bytes(4) + box(b"keys", b"com.apple.quicktime.location.ISO6709" + LOCATION)))
    udta = box(b"udta", box(b"\xa9xyz", len(LOCATION).to_bytes(2, "big") + b"\x15\xc7" + LOCATION))
    return box(b"ftyp", b"isom" + bytes(4) + b"isomiso2mp41") + box(b"moov", mvhd + trak + udta) + box(b"mdat", b"frame-data" * 50)


class TestListingVideo:
    async def upload(self, client, account, listing_id: str, content: bytes, name: str = "walkthrough.mp4"):
        return await client.post(f"/rentals/{listing_id}/video", files={"file": (name, content, "video/mp4")}, headers=account.auth)

    async def test_a_video_is_stored_without_its_location_and_streams_with_ranges(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        original = mp4_bytes()

        response = await self.upload(client, owner, listing_id, original)
        assert response.status_code == 200, response.text
        video = response.json()["video"]
        assert (video["size_bytes"], video["duration_seconds"]) == (len(original), 12.0)

        stored = (photo_folder(ObjectId(listing_id)) / f"{video['id']}.mp4").read_bytes()
        assert len(stored) == len(original) and LOCATION not in stored and b"udta" not in stored
        assert stored.endswith(b"frame-data" * 50)  # the media itself is untouched

        url = f"/rentals/{listing_id}/video/{video['id']}"
        whole = await client.get(url)
        assert (whole.status_code, whole.headers["content-type"], whole.content) == (200, "video/mp4", stored)
        part = await client.get(url, headers={"Range": "bytes=0-99"})
        assert (part.status_code, len(part.content)) == (206, 100)

    async def test_a_new_video_replaces_the_old_one(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        first = (await self.upload(client, owner, listing_id, mp4_bytes())).json()["video"]["id"]
        second = (await self.upload(client, owner, listing_id, mp4_bytes(30))).json()["video"]["id"]

        assert not (photo_folder(ObjectId(listing_id)) / f"{first}.mp4").exists()
        assert (await client.get(f"/rentals/{listing_id}/video/{first}")).status_code == 404
        removed = await client.delete(f"/rentals/{listing_id}/video/{second}", headers=owner.auth)
        assert (removed.status_code, removed.json()["video"]) == (200, None)
        assert not (photo_folder(ObjectId(listing_id)) / f"{second}.mp4").exists()

    async def test_only_real_short_videos_are_accepted(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        assert (await self.upload(client, owner, listing_id, jpeg_bytes(), "photo.mp4")).status_code == 400
        assert (await self.upload(client, owner, listing_id, b"<b>not a video</b>" * 20, "x.mp4")).status_code == 400
        assert (await self.upload(client, owner, listing_id, mp4_bytes() + b"trailing")).status_code == 400
        assert (await self.upload(client, owner, listing_id, mp4_bytes(seconds=400))).status_code == 400
        folder = photo_folder(ObjectId(listing_id))
        assert list(folder.glob("*.mp4")) + list(folder.glob("*.part")) == []

    async def test_sale_listings_take_a_video_too(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.sale_listing(owner, "Dhanmondi", 90.3742, 23.7461)
        response = await client.post(
            f"/marketplace/sale-listings/{listing_id}/video", files={"file": ("tour.mp4", mp4_bytes(), "video/mp4")}, headers=owner.auth
        )
        assert response.status_code == 200 and response.json()["video"]["duration_seconds"] == 12.0
