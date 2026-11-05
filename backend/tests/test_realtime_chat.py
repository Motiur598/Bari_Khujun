"""Feature 21: realtime chat, persistent notifications and in-chat action cards.

Sockets are opened in-process (support.RealtimeSocket), so each test sees exactly what a browser tab would receive,
and the database is checked afterwards for what was queued, delivered, read and stripped.
"""

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from support import DHAKA, RealtimeSocket, SocketRejected

from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio


def next_slot(days: int = 1, hour: int = 10, minute: int = 30) -> datetime:
    day = datetime.now(DHAKA).date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=DHAKA)


async def send(client, sender, property_id: str, receiver_id: str, content: str):
    return await client.post(
        "/chat/send", json={"property_id": property_id, "receiver_id": receiver_id, "content": content}, headers=sender.auth
    )


async def connect(account) -> RealtimeSocket:
    return RealtimeSocket(app, account.token, origin=settings.allowed_origins[0])


# ---------------------------------------------------------------- the socket itself


async def test_socket_requires_a_valid_token_and_an_allowed_origin(make):
    owner = await make.account("OWNER")
    with pytest.raises(SocketRejected):
        async with RealtimeSocket(app, "not-a-real-token"):
            pass
    with pytest.raises(SocketRejected):
        async with RealtimeSocket(app, owner.token, origin="https://attacker.example"):
            pass

    async with await connect(owner) as ws:
        bundle = await ws.receive_json()
        assert bundle["type"] == "OFFLINE_SYNC_BUNDLE"
        assert bundle["messages"] == [] and bundle["notifications"] == []
        await ws.send_json({"type": "PING"})
        assert (await ws.receive_json())["type"] == "PONG"


async def test_offline_messages_are_sanitized_queued_and_flushed_on_reconnect(make, client, db):
    owner = await make.account("OWNER")
    buyer = await make.account("BUYER", name="Nadia Buyer")
    listing_id = await make.sale_listing(owner, "Banani", 90.4043, 23.7937)

    response = await send(client, buyer, listing_id, owner.id, "Is it still available?<script>alert(1)</script><b>!</b>")
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["content"] == "Is it still available?!"
    assert first["is_delivered"] is False  # the owner is offline
    stored = await db.chat_messages.find_one({"_id": ObjectId(first["id"])})
    assert "<" not in stored["content"] and "alert" not in stored["content"]

    assert (await send(client, buyer, listing_id, owner.id, "Can I visit on Friday?")).status_code == 201
    # One unread alert per thread, updated by later messages rather than stacked.
    alerts = await db.notifications.find({"recipient_id": owner.oid, "type": "NEW_MESSAGE"}).to_list(None)
    assert len(alerts) == 1
    assert alerts[0]["metadata"]["unread_count"] == 2 and alerts[0]["is_delivered"] is False
    assert alerts[0]["title"] == "New message from Nadia Buyer"

    async with await connect(owner) as ws:
        bundle = await ws.receive_json()
    assert bundle["type"] == "OFFLINE_SYNC_BUNDLE"
    assert [m["content"] for m in bundle["messages"]] == ["Is it still available?!", "Can I visit on Friday?"]
    assert bundle["missed"] == {"messages": 2, "notifications": 1, "visits": 0}
    assert await db.chat_messages.count_documents({"receiver_id": owner.oid, "is_delivered": False}) == 0
    assert await db.notifications.count_documents({"recipient_id": owner.oid, "is_delivered": False}) == 0

    # Still unread on the next connection, but no longer "missed": the app won't pop them up twice.
    async with await connect(owner) as ws:
        again = await ws.receive_json()
    assert len(again["messages"]) == 2
    assert again["missed"] == {"messages": 0, "notifications": 0, "visits": 0}


async def test_live_delivery_threads_and_read_receipts(make, client, db):
    owner = await make.account("OWNER", name="Karim Owner")
    tenant = await make.account("BACHELOR_TENANT", name="Rafi Tenant")
    listing_id = await make.seat_listing(owner)

    async with await connect(owner) as owner_ws, await connect(tenant) as tenant_ws:
        await owner_ws.receive_until("OFFLINE_SYNC_BUNDLE")
        await tenant_ws.receive_until("OFFLINE_SYNC_BUNDLE")

        response = await send(client, tenant, listing_id, owner.id, "Hello! Is the seat free from next month?")
        assert response.status_code == 201
        message = response.json()
        assert message["is_delivered"] is True

        event = await owner_ws.receive_until("NEW_CHAT_MESSAGE")
        assert event["message"]["id"] == message["id"]
        assert event["notification"]["type"] == "NEW_MESSAGE"
        echo = await tenant_ws.receive_until("CHAT_MESSAGE_SENT")
        assert echo["message"]["id"] == message["id"]

        threads = (await client.get("/chat/threads", headers=owner.auth)).json()
        assert len(threads) == 1
        assert threads[0]["unread_count"] == 1
        assert threads[0]["other_user"] == {"id": tenant.id, "full_name": "Rafi Tenant", "role": "BACHELOR_TENANT", "online": True}
        assert threads[0]["listing"]["id"] == listing_id

        page = (await client.get(f"/chat/messages/{listing_id}/{tenant.id}", headers=owner.auth)).json()
        assert [m["is_read"] for m in page["items"]] == [True]
        receipt = await tenant_ws.receive_until("MESSAGES_READ")
        assert receipt["message_ids"] == [message["id"]]

        threads = (await client.get("/chat/threads", headers=owner.auth)).json()
        assert threads[0]["unread_count"] == 0
        assert await db.notifications.count_documents({"recipient_id": owner.oid, "type": "NEW_MESSAGE", "is_read": False}) == 0

        # The lister can reply in an existing thread.
        assert (await send(client, owner, listing_id, tenant.id, "Yes, from the 1st.")).status_code == 201
        assert (await tenant_ws.receive_until("NEW_CHAT_MESSAGE"))["message"]["content"] == "Yes, from the 1st."

    # Pagination: newest page first, oldest-first inside a page.
    for n in range(3):
        await send(client, tenant, listing_id, owner.id, f"follow-up {n}")
    page = (await client.get(f"/chat/messages/{listing_id}/{owner.id}", params={"limit": 2}, headers=tenant.auth)).json()
    assert [m["content"] for m in page["items"]] == ["follow-up 1", "follow-up 2"] and page["has_more"] is True
    older = (
        await client.get(
            f"/chat/messages/{listing_id}/{owner.id}", params={"limit": 2, "before": page["items"][0]["id"]}, headers=tenant.auth
        )
    ).json()
    assert [m["content"] for m in older["items"]] == ["Yes, from the 1st.", "follow-up 0"]


async def test_who_can_message_whom(make, client, db):
    owner = await make.account("OWNER")
    buyer = await make.account("BUYER")
    stranger = await make.account("BUYER")
    listing_id = await make.sale_listing(owner, "Gulshan", 90.4152, 23.7925)

    # Chats about a listing always include its lister.
    assert (await send(client, buyer, listing_id, stranger.id, "hi")).status_code == 403
    # The lister can't cold-message someone who never got in touch about the listing...
    assert (await send(client, owner, listing_id, stranger.id, "Want to buy?")).status_code == 403
    assert (await send(client, owner, listing_id, owner.id, "note to self")).status_code == 400
    # ...but can once they have (here, an offer).
    offer = await client.post(
        "/marketplace/offers", json={"listing_id": listing_id, "offer_type": "PURCHASE", "amount": 13_000_000}, headers=buyer.auth
    )
    assert offer.status_code == 201, offer.text
    assert (await send(client, owner, listing_id, buyer.id, "Thanks for the offer")).status_code == 201

    # Another user only ever reads their own thread with the lister, never the buyer's.
    page = (await client.get(f"/chat/messages/{listing_id}/{owner.id}", headers=stranger.auth)).json()
    assert page["items"] == []
    # Someone else's notification can't be marked read (or even found).
    alert = await db.notifications.find_one({"recipient_id": owner.oid})
    assert (await client.patch(f"/notifications/{alert['_id']}/read", headers=stranger.auth)).status_code == 404
    response = await client.patch(f"/notifications/{alert['_id']}/read", headers=owner.auth)
    assert response.status_code == 200 and response.json()["is_read"] is True
    assert (await send(client, buyer, listing_id, owner.id, "<img src=x onerror=alert(1)>")).status_code == 422  # empty once stripped


# ---------------------------------------------------------------- visit request cards


async def test_visit_alert_reaches_the_owner_and_the_card_follows_their_answer(make, client, db):
    owner = await make.account("OWNER", name="Salma Owner")
    tenant = await make.account("FAMILY_TENANT", name="Arif Family")
    listing_id = await make.flat_listing(owner, "Dhanmondi", 90.3742, 23.7461)
    starts = next_slot(days=2)

    async with await connect(owner) as owner_ws:
        await owner_ws.receive_until("OFFLINE_SYNC_BUNDLE")
        response = await client.post(
            "/marketplace/visits",
            json={"listing_id": listing_id, "starts_at": starts.isoformat(), "mode": "IN_PERSON"},
            headers=tenant.auth,
        )
        assert response.status_code == 201, response.text
        visit_id = response.json()["id"]

        card_event = await owner_ws.receive_until("NEW_CHAT_MESSAGE")
        alert = await owner_ws.receive_until("VISIT_SCHEDULED")

    card = card_event["message"]
    assert card["message_type"] == "VISIT_REQUEST_CARD" and card_event["notification"] is None
    assert card["action_payload"]["reference_id"] == visit_id
    assert card["action_payload"]["status"] == "PENDING"
    assert card["action_payload"]["scheduled_date"] == starts.date().isoformat()
    assert card["action_payload"]["scheduled_time"] == "10:30"

    notification = alert["notification"]
    day = f"{starts:%a} {starts.day} {starts:%b %Y}"
    assert notification["title"] == "📅 New House Visit Scheduled!"
    assert notification["message"] == f"Arif Family fixed a time to visit 'Family flat in Dhanmondi' on {day} at 10:30 AM."
    assert notification["metadata"].items() >= {
        "visit_id": visit_id, "property_id": listing_id, "visit_date": starts.date().isoformat(), "visit_time": "10:30", "visitor_id": tenant.id
    }.items()
    assert (await db.notifications.find_one({"_id": ObjectId(notification["id"])}))["is_delivered"] is True

    status_url = f"/marketplace/visits/{visit_id}/status"
    # Only the owner answers a visit request.
    assert (await client.patch(status_url, json={"status": "APPROVED"}, headers=tenant.auth)).status_code == 403

    # The tenant is offline: the owner's proposal of a new time waits for them.
    new_time = next_slot(days=2, hour=11, minute=0)
    response = await client.patch(status_url, json={"status": "RESCHEDULE_PROPOSED", "starts_at": new_time.isoformat()}, headers=owner.auth)
    assert response.status_code == 200, response.text
    assert response.json()["approval"] == "RESCHEDULE_PROPOSED"
    stored = await db.chat_messages.find_one({"_id": ObjectId(card["id"])})
    assert stored["action_payload"]["status"] == "RESCHEDULE_PROPOSED" and stored["action_payload"]["scheduled_time"] == "11:00"
    assert (await client.patch(status_url, json={"status": "APPROVED"}, headers=owner.auth)).status_code == 409

    async with await connect(tenant) as tenant_ws:
        bundle = await tenant_ws.receive_json()
        missed = [n for n in bundle["notifications"] if not n["is_delivered"]]
        assert [n["type"] for n in missed] == ["VISIT_STATUS_CHANGED"]
        assert "proposed" in missed[0]["message"]

        # The tenant accepts the new time; both sides see the card change.
        response = await client.patch(status_url, json={"status": "APPROVED"}, headers=tenant.auth)
        assert response.status_code == 200 and response.json()["approval"] == "APPROVED"
        assert (await tenant_ws.receive_until("CHAT_CARD_UPDATED"))["message"]["action_payload"]["status"] == "APPROVED"

        response = await client.patch(status_url, json={"status": "DECLINED"}, headers=owner.auth)
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED" and response.json()["approval"] == "DECLINED"
        assert (await tenant_ws.receive_until("CHAT_CARD_UPDATED"))["message"]["action_payload"]["status"] == "DECLINED"
        assert (await tenant_ws.receive_until("VISIT_STATUS_CHANGED"))["notification"]["title"] == "❌ Visit declined"


# ---------------------------------------------------------------- offer cards


async def test_sale_offer_card_follows_the_negotiation(make, client, db):
    owner = await make.account("OWNER")
    buyer = await make.account("BUYER")
    listing_id = await make.sale_listing(owner, "Uttara", 90.3984, 23.8759)

    response = await client.post(
        "/marketplace/offers", json={"listing_id": listing_id, "offer_type": "PURCHASE", "amount": 13_500_000}, headers=buyer.auth
    )
    offer_id = response.json()["id"]
    card = await db.chat_messages.find_one({"message_type": "OFFER_PROPOSAL_CARD", "action_payload.reference_id": offer_id})
    assert card["sender_id"] == buyer.oid and card["receiver_id"] == owner.oid
    assert card["action_payload"]["status"] == "AWAITING_SELLER" and card["action_payload"]["proposed_amount"] == 13_500_000

    async with await connect(buyer) as buyer_ws:
        await buyer_ws.receive_until("OFFLINE_SYNC_BUNDLE")
        counter = await client.post(
            f"/marketplace/offers/{offer_id}/respond", json={"action": "COUNTER", "amount": 13_800_000}, headers=owner.auth
        )
        assert counter.status_code == 200
        updated = (await buyer_ws.receive_until("CHAT_CARD_UPDATED"))["message"]["action_payload"]
        assert updated["status"] == "AWAITING_BUYER" and updated["proposed_amount"] == 13_800_000
        assert (await buyer_ws.receive_until("OFFER_UPDATE"))["notification"]["title"] == "↩️ Counter-offer"

        assert (await client.post(f"/marketplace/offers/{offer_id}/respond", json={"action": "ACCEPT"}, headers=buyer.auth)).status_code == 200
        assert (await buyer_ws.receive_until("CHAT_CARD_UPDATED"))["message"]["action_payload"]["status"] == "ACCEPTED"


async def test_rent_offer_becomes_a_booking_then_a_qr_card_that_confirms_the_deal(make, client, db):
    owner = await make.account("OWNER", name="Hasan Owner")
    tenant = await make.account("BACHELOR_TENANT", name="Tanvir Tenant")
    rival = await make.account("BACHELOR_TENANT")
    listing_id = await make.seat_listing(owner)
    proposal = {
        "listing_id": listing_id,
        "amount": 11_000,
        "move_in_date": make.move_in_date().isoformat(),
        "deposit_amount": 4_000,
        "payment_method": "BKASH",
        "payment_reference": "TRXCHAT001",
    }

    response = await client.post("/chat/rent-offers", json=proposal, headers=tenant.auth)
    assert response.status_code == 201, response.text
    offer_id = response.json()["id"]
    assert (await client.post("/chat/rent-offers", json=proposal, headers=tenant.auth)).status_code == 409
    card = await db.chat_messages.find_one({"message_type": "OFFER_PROPOSAL_CARD", "action_payload.reference_id": offer_id})
    assert card["action_payload"].items() >= {"status": "AWAITING_OWNER", "proposed_amount": 11_000, "kind": "RENT"}.items()

    respond = f"/chat/rent-offers/{offer_id}/respond"
    # The tenant can't accept their own terms, and nobody outside the deal can touch it.
    assert (await client.post(respond, json={"action": "ACCEPT"}, headers=tenant.auth)).status_code == 409
    assert (await client.post(respond, json={"action": "ACCEPT"}, headers=rival.auth)).status_code == 404
    assert (await client.post(respond, json={"action": "COUNTER", "amount": 11_500}, headers=owner.auth)).status_code == 200
    accepted = await client.post(respond, json={"action": "ACCEPT"}, headers=tenant.auth)
    assert accepted.status_code == 200, accepted.text
    booking_id = accepted.json()["booking_id"]
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    assert booking["agreed_rent"] == 11_500 and booking["status"] == "PENDING_OWNER" and booking["deposit"]["amount"] == 4_000

    context = (await client.get(f"/chat/threads/{listing_id}/{tenant.id}", headers=owner.auth)).json()
    assert context["can_send_qr"] is True and context["open_booking"]["id"] == booking_id
    tenant_view = (await client.get(f"/chat/threads/{listing_id}/{owner.id}", headers=tenant.auth)).json()
    assert tenant_view["can_send_qr"] is False

    send_qr = {"property_id": listing_id, "tenant_id": tenant.id}
    # Only the listing's owner can send the confirmation QR.
    assert (await client.post("/chat/qr/send", json=send_qr, headers=tenant.auth)).status_code == 404

    async with await connect(tenant) as tenant_ws, await connect(owner) as owner_ws:
        await tenant_ws.receive_until("OFFLINE_SYNC_BUNDLE")
        await owner_ws.receive_until("OFFLINE_SYNC_BUNDLE")

        response = await client.post("/chat/qr/send", json=send_qr, headers=owner.auth)
        assert response.status_code == 200, response.text
        qr_card = response.json()
        first_token = qr_card["action_payload"]["qr_token"]
        assert qr_card["message_type"] == "QR_CONFIRMATION_CARD" and qr_card["action_payload"]["status"] == "ACTIVE"
        assert qr_card["action_payload"]["agreed_rent"] == 11_500 and first_token
        arrived = await tenant_ws.receive_until("NEW_CHAT_MESSAGE")
        assert arrived["message"]["id"] == qr_card["id"]
        assert (await tenant_ws.receive_until("QR_UPDATE"))["notification"]["title"] == "📲 Confirmation QR received"

        # A code shown from the dashboard replaces the one in the chat: its card is revoked and the token removed.
        assert (await client.post(f"/qr-handshake/generate/{booking_id}", headers=owner.auth)).status_code == 200
        revoked = (await tenant_ws.receive_until("CHAT_CARD_UPDATED"))["message"]["action_payload"]
        assert revoked["status"] == "REVOKED" and revoked["qr_token"] is None

        # Regenerating from the chat refreshes the same card with a new single-use code.
        response = await client.post("/chat/qr/send", json=send_qr, headers=owner.auth)
        regenerated = response.json()
        token = regenerated["action_payload"]["qr_token"]
        assert regenerated["id"] == qr_card["id"] and token != first_token
        assert (await tenant_ws.receive_until("CHAT_CARD_UPDATED"))["message"]["action_payload"]["qr_token"] == token
        assert (await make.scan(tenant, first_token)).status_code == 400

        # Only the tenant the code was issued to can confirm with it.
        assert (await make.scan(rival, token)).status_code == 403
        confirmed = await make.scan(tenant, token)
        assert confirmed.status_code == 200, confirmed.text

        flipped = (await tenant_ws.receive_until("CHAT_CARD_UPDATED"))["message"]["action_payload"]
        assert flipped["status"] == "CONFIRMED" and flipped["qr_token"] is None and flipped["lease_ready"] is True
        assert (await owner_ws.receive_until("QR_UPDATE"))["notification"]["title"] == "🎉 Deal confirmed"

    stored = await db.chat_messages.find_one({"_id": ObjectId(qr_card["id"])})
    assert stored["action_payload"]["status"] == "CONFIRMED" and stored["action_payload"]["qr_token"] is None
    history = (await client.get(f"/chat/messages/{listing_id}/{owner.id}", headers=tenant.auth)).json()["items"]
    assert all(m["action_payload"] is None or m["action_payload"]["qr_token"] is None for m in history)
    assert (await client.get(f"/qr-handshake/bookings/{booking_id}/lease.pdf", headers=owner.auth)).status_code == 200


async def test_expired_qr_codes_are_stripped_from_chat_history(make, client, db):
    owner = await make.account("OWNER")
    tenant = await make.account("BACHELOR_TENANT")
    listing_id = await make.seat_listing(owner)
    booking_id, _ = await make.approved_booking(owner, tenant, listing_id)

    response = await client.post("/chat/qr/send", json={"property_id": listing_id, "tenant_id": tenant.id}, headers=owner.auth)
    card_id = response.json()["id"]
    assert response.json()["action_payload"]["qr_token"]

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"qr.expires_at": past}})
    page = (await client.get(f"/chat/messages/{listing_id}/{owner.id}", headers=tenant.auth)).json()
    card = next(m for m in page["items"] if m["id"] == card_id)
    assert card["action_payload"]["status"] == "EXPIRED" and card["action_payload"]["qr_token"] is None
    assert (await db.chat_messages.find_one({"_id": ObjectId(card_id)}))["action_payload"]["qr_token"] is None
