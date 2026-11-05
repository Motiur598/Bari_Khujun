"""Feature 21: realtime chat between tenants/buyers and listers, action cards, and persistent notifications.

One WebSocket per browser tab (`/ws/realtime?token=...`) carries everything live. On every (re)connection the
server first sends an OFFLINE_SYNC_BUNDLE with all unread messages and notifications, so nothing that happened while
the user was offline is lost. After that it pushes:

    NEW_CHAT_MESSAGE      a message or action card arrived (with its NEW_MESSAGE notification, if it has one)
    CHAT_MESSAGE_SENT     the user's own message, echoed to their other tabs
    CHAT_CARD_UPDATED     an action card changed state (visit approved, offer countered, QR confirmed...)
    MESSAGES_READ         the other person read these messages (read receipts)
    PRESENCE              a chat partner came online or went offline
    VISIT_SCHEDULED, VISIT_STATUS_CHANGED, OFFER_UPDATE, QR_UPDATE   a notification of that type

The client sends {"type": "PING"} every 25 s and gets {"type": "PONG"}.
"""

import asyncio
import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import get_db, parse_object_id, serialize_doc
from app.core.limiter import CHAT_LIMIT, QR_LIMIT, limiter, user_or_ip
from app.core.security import get_current_user, require_roles, user_from_token
from app.core.ws_manager import ws_manager
from app.routers import qr_handshake
from app.routers.qr_handshake import TENANT_ROLES
from app.schemas.booking import DepositMethod
from app.schemas.chat import (
    OPEN_RENT_OFFER_STATUSES,
    ChatMessageOut,
    ChatQrSend,
    ChatSend,
    ChatUser,
    MessagePage,
    NotificationList,
    NotificationOut,
    NotificationType,
    OpenBooking,
    RentOfferCreate,
    RentOfferOut,
    RentOfferResponse,
    RentOfferStatus,
    ThreadContext,
    ThreadListing,
    ThreadListingDetail,
    ThreadOut,
)
from app.schemas.marketplace import SaleStatus
from app.schemas.user import Role
from app.services import chat_cards
from app.services.listings import RENT_ONLY
from app.services.notifications import (
    broadcast_presence,
    mark_thread_read,
    message_out,
    notification_out,
    post_message,
    thread_id_for,
)

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 75  # the app pings every 25 s; a socket silent for this long is gone
RECHECK_SECONDS = 300  # a long-lived socket re-checks its account this often (ban, sign-out everywhere, expiry)
AUTH_REVOKED = 4401  # close code once the token stops being valid; the app then checks its session
BUNDLE_LIMIT = 200
THREAD_LIMIT = 100

_LISTING_FIELDS = {
    "title": 1, "listing_mode": 1, "lister_id": 1, "category": 1, "effective_rent": 1, "sale": 1,
    "rental_status": 1, "sale_status": 1, "seats": 1, "sublet": 1, "suspended": 1, "location": 1,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ================================================================ WebSocket


async def _send_offline_bundle(websocket: WebSocket, user: dict) -> None:
    """Everything still unread, flagged with whether it had reached the user before (is_delivered). The items that
    hadn't are what the app pops up as "while you were away"; afterwards they're marked delivered."""
    db = get_db()
    uid = user["_id"]
    messages = await db.chat_messages.find({"receiver_id": uid, "is_read": False}).sort("_id", -1).to_list(BUNDLE_LIMIT)
    messages.reverse()
    await chat_cards.refresh_cards(messages)
    notifications = await db.notifications.find({"recipient_id": uid, "is_read": False}).sort("created_at", -1).to_list(BUNDLE_LIMIT)
    missed_messages = [m["_id"] for m in messages if not m["is_delivered"]]
    missed_notifications = [n for n in notifications if not n["is_delivered"]]
    bundle = {
        "type": "OFFLINE_SYNC_BUNDLE",
        "messages": [message_out(m) for m in messages],
        "notifications": [notification_out(n) for n in notifications],
        "missed": {
            "messages": len(missed_messages),
            "notifications": len(missed_notifications),
            "visits": sum(1 for n in missed_notifications if n["type"] == NotificationType.VISIT_SCHEDULED),
        },
        "unread_messages": await db.chat_messages.count_documents({"receiver_id": uid, "is_read": False}),
        "unread_notifications": await db.notifications.count_documents({"recipient_id": uid, "is_read": False}),
    }
    await websocket.send_json(jsonable_encoder(bundle))
    if missed_messages:
        await db.chat_messages.update_many({"_id": {"$in": missed_messages}}, {"$set": {"is_delivered": True}})
    if missed_notifications:
        await db.notifications.update_many(
            {"_id": {"$in": [n["_id"] for n in missed_notifications]}}, {"$set": {"is_delivered": True}}
        )


@router.websocket("/ws/realtime")
async def realtime(websocket: WebSocket, token: Annotated[str, Query(max_length=4096)] = ""):
    # Browsers always send Origin on a WebSocket handshake; only the app's own origins may open one.
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    # Authenticated before the handshake completes: a bad, expired or revoked token never gets a socket.
    try:
        user = await user_from_token(token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    uid = str(user["_id"])
    came_online = ws_manager.connect(uid, websocket)
    try:
        await _send_offline_bundle(websocket, user)
        if came_online:
            await broadcast_presence(user["_id"], True)
        checked_at = time.monotonic()
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=IDLE_TIMEOUT_SECONDS)
            except TimeoutError:
                await websocket.close(code=status.WS_1001_GOING_AWAY)
                break
            if message["type"] == "websocket.disconnect":
                break
            if time.monotonic() - checked_at > RECHECK_SECONDS:
                try:
                    await user_from_token(token)
                except HTTPException:
                    await websocket.close(code=AUTH_REVOKED)
                    break
                checked_at = time.monotonic()
            try:
                event = json.loads(message.get("text") or "{}")
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "PING":
                await websocket.send_json({"type": "PONG"})
    except (WebSocketDisconnect, RuntimeError):
        pass  # the client went away mid-send
    finally:
        if ws_manager.disconnect(uid, websocket):
            try:
                await broadcast_presence(user["_id"], False)
            except Exception:
                logger.exception("Presence broadcast failed for %s", uid)


# ================================================================ chat: who may talk to whom


async def _load_listing(property_id: str | ObjectId) -> dict:
    oid = property_id if isinstance(property_id, ObjectId) else parse_object_id(property_id)
    listing = await get_db().listings.find_one({"_id": oid}, _LISTING_FIELDS)
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return listing


async def _load_user(user_id: str) -> dict:
    user = await get_db().users.find_one({"_id": parse_object_id(user_id)}, {"full_name": 1, "role": 1, "is_banned": 1})
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def _has_dealings(listing_id: ObjectId, lister_id: ObjectId, other_id: ObjectId) -> bool:
    """Whether this person has already reached out about the listing: a visit, rent request or offer."""
    db = get_db()
    checks = (
        (db.visit_slots, {"listing_id": listing_id, "host_id": lister_id, "visitor_id": other_id}),
        (db.bookings, {"listing_id": listing_id, "owner_id": lister_id, "tenant_id": other_id}),
        (db.offers, {"listing_id": listing_id, "seller_id": lister_id, "buyer_id": other_id}),
        (db.rent_offers, {"listing_id": listing_id, "owner_id": lister_id, "tenant_id": other_id}),
    )
    for collection, query in checks:
        if await collection.find_one(query, {"_id": 1}):
            return True
    return False


async def _check_can_message(listing: dict, sender: dict, receiver: dict) -> None:
    """Anyone signed in may message a listing's lister about it. The lister may reply, or write first to someone
    who has booked a visit, asked to rent or made an offer, but can't cold-message other users."""
    if receiver["_id"] == sender["_id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't message yourself")
    lister_id = listing["lister_id"]
    if lister_id not in (sender["_id"], receiver["_id"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Messages about a listing go to the person who listed it")
    if receiver.get("is_banned"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been suspended")
    thread = thread_id_for(listing["_id"], sender["_id"], receiver["_id"])
    if await get_db().chat_messages.find_one({"thread_id": thread}, {"_id": 1}):
        return
    if sender["_id"] == lister_id:
        if not await _has_dealings(listing["_id"], lister_id, receiver["_id"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can message this person once they've contacted you about the listing")
    elif listing.get("suspended"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")


def _chat_user(user: dict | None, user_id: ObjectId) -> ChatUser:
    return ChatUser(
        id=str(user_id),
        full_name=user["full_name"] if user else "Deleted account",
        role=user.get("role", "") if user else "",
        online=ws_manager.is_online(user_id),
    )


def _listing_mode(listing: dict) -> str:
    return listing.get("listing_mode", "RENT")


def _is_open_for_business(listing: dict) -> bool:
    if listing.get("suspended"):
        return False
    if _listing_mode(listing) == "SALE":
        return listing.get("sale_status") == SaleStatus.AVAILABLE
    if listing.get("rental_status") == "RENTED":
        return False
    return listing.get("category") != "BACHELOR_SEAT" or (listing.get("seats") or {}).get("available_seats", 0) >= 1


# ================================================================ chat: messages and threads


@router.post("/api/chat/send", response_model=ChatMessageOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(CHAT_LIMIT, key_func=user_or_ip)
async def send_message(request: Request, payload: ChatSend, user: dict = Depends(get_current_user)):
    """`content` has already been through nh3 (SafeText): tags are stripped before it is stored or pushed."""
    listing = await _load_listing(payload.property_id)
    receiver = await _load_user(payload.receiver_id)
    await _check_can_message(listing, user, receiver)
    message = await post_message(
        property_id=listing["_id"], sender=user, receiver_id=receiver["_id"], content=payload.content, listing_title=listing["title"]
    )
    return message_out(message)


@router.get("/api/chat/threads", response_model=list[ThreadOut])
async def my_threads(user: dict = Depends(get_current_user)):
    """The user's conversations, newest first: one per listing and person, with the unread count for the badge."""
    db = get_db()
    uid = user["_id"]
    pipeline = [
        {"$match": {"$or": [{"sender_id": uid}, {"receiver_id": uid}]}},
        {"$sort": {"_id": -1}},
        {
            "$group": {
                "_id": "$thread_id",
                "last": {"$first": "$$ROOT"},
                "unread": {"$sum": {"$cond": [{"$and": [{"$eq": ["$receiver_id", uid]}, {"$eq": ["$is_read", False]}]}, 1, 0]}},
            }
        },
        {"$sort": {"last._id": -1}},
        {"$limit": THREAD_LIMIT},
    ]
    groups = await db.chat_messages.aggregate(pipeline).to_list(None)
    if not groups:
        return []
    other_ids = {g["last"]["receiver_id"] if g["last"]["sender_id"] == uid else g["last"]["sender_id"] for g in groups}
    users = {u["_id"]: u for u in await db.users.find({"_id": {"$in": list(other_ids)}}, {"full_name": 1, "role": 1}).to_list(None)}
    listing_ids = list({g["last"]["property_id"] for g in groups})
    listings = {
        doc["_id"]: doc
        for doc in await db.listings.find({"_id": {"$in": listing_ids}}, {"title": 1, "listing_mode": 1, "lister_id": 1}).to_list(None)
    }
    await chat_cards.refresh_cards([g["last"] for g in groups])

    threads = []
    for group in groups:
        last = group["last"]
        other_id = last["receiver_id"] if last["sender_id"] == uid else last["sender_id"]
        listing = listings.get(last["property_id"])
        threads.append(
            ThreadOut(
                thread_id=group["_id"],
                property_id=str(last["property_id"]),
                listing=ThreadListing(
                    id=str(listing["_id"]), title=listing["title"], listing_mode=_listing_mode(listing), lister_id=str(listing["lister_id"])
                )
                if listing
                else None,
                other_user=_chat_user(users.get(other_id), other_id),
                last_message=message_out(last),
                unread_count=group["unread"],
            )
        )
    return threads


@router.get("/api/chat/threads/{property_id}/{other_user_id}", response_model=ThreadContext)
async def thread_context(property_id: str, other_user_id: str, user: dict = Depends(get_current_user)):
    """The chat window's header and toolbar: the other person, the listing, and which quick actions apply."""
    listing = await _load_listing(property_id)
    other = await _load_user(other_user_id)
    viewer_is_lister = listing["lister_id"] == user["_id"]
    if not viewer_is_lister and listing["lister_id"] != other["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Messages about a listing go to the person who listed it")
    db = get_db()
    mode = _listing_mode(listing)
    open_now = _is_open_for_business(listing)

    can_make_offer = False
    if not viewer_is_lister and open_now:
        if mode == "SALE":
            can_make_offer = user["role"] == Role.BUYER and not await db.offers.find_one(
                {"listing_id": listing["_id"], "buyer_id": user["_id"], "is_open": True}, {"_id": 1}
            )
        else:
            try:
                qr_handshake.check_can_rent(listing, user)
                can_make_offer = not await db.rent_offers.find_one(
                    {"listing_id": listing["_id"], "tenant_id": user["_id"], "is_open": True}, {"_id": 1}
                )
            except HTTPException:
                can_make_offer = False

    open_booking = None
    if viewer_is_lister and mode == "RENT":
        booking = await db.bookings.find_one(
            {"listing_id": listing["_id"], "owner_id": user["_id"], "tenant_id": other["_id"], "is_open": True}
        )
        if booking is not None:
            open_booking = OpenBooking(
                id=str(booking["_id"]), status=booking["status"], agreed_rent=booking["agreed_rent"], deposit_amount=booking["deposit"]["amount"]
            )

    return ThreadContext(
        thread_id=thread_id_for(listing["_id"], user["_id"], other["_id"]),
        listing=ThreadListingDetail(
            id=str(listing["_id"]),
            title=listing["title"],
            listing_mode=mode,
            lister_id=str(listing["lister_id"]),
            category=listing.get("category"),
            effective_rent=listing.get("effective_rent"),
            asking_price=(listing.get("sale") or {}).get("asking_price"),
            available=open_now,
            rooms=(listing.get("sublet") or {}).get("rooms"),
        ),
        other_user=_chat_user(other, other["_id"]),
        viewer_is_lister=viewer_is_lister,
        can_make_offer=can_make_offer,
        can_send_qr=open_booking is not None,
        open_booking=open_booking,
    )


@router.get("/api/chat/messages/{property_id}/{other_user_id}", response_model=MessagePage)
async def thread_messages(
    property_id: str,
    other_user_id: str,
    before: Annotated[str | None, Query(max_length=24, description="Message id: return messages older than this one")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
    user: dict = Depends(get_current_user),
):
    """A page of the conversation, oldest first, ending at `before` (or the latest message). Reading it marks the
    messages the user received as read. The thread id contains the user's own id, so only their own chats load."""
    thread = thread_id_for(parse_object_id(property_id), user["_id"], parse_object_id(other_user_id))
    query: dict = {"thread_id": thread}
    if before:
        query["_id"] = {"$lt": parse_object_id(before)}
    docs = await get_db().chat_messages.find(query).sort("_id", -1).limit(limit + 1).to_list(None)
    has_more = len(docs) > limit
    docs = docs[:limit][::-1]
    await chat_cards.refresh_cards(docs)
    await mark_thread_read(thread, user["_id"])
    for doc in docs:
        if doc["receiver_id"] == user["_id"]:
            doc["is_read"] = doc["is_delivered"] = True
    return MessagePage(items=[message_out(doc) for doc in docs], has_more=has_more)


@router.post("/api/chat/messages/{property_id}/{other_user_id}/read")
async def read_thread(property_id: str, other_user_id: str, user: dict = Depends(get_current_user)):
    """For messages that arrive while the chat is open on screen."""
    thread = thread_id_for(parse_object_id(property_id), user["_id"], parse_object_id(other_user_id))
    return {"marked": await mark_thread_read(thread, user["_id"])}


# ================================================================ notifications


@router.get("/api/notifications", response_model=NotificationList)
async def my_notifications(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    unread_only: bool = False,
    user: dict = Depends(get_current_user),
):
    query: dict = {"recipient_id": user["_id"]}
    if unread_only:
        query["is_read"] = False
    db = get_db()
    docs = await db.notifications.find(query).sort("created_at", -1).to_list(limit)
    unread = await db.notifications.count_documents({"recipient_id": user["_id"], "is_read": False})
    return NotificationList(items=[notification_out(doc) for doc in docs], unread_count=unread)


@router.patch("/api/notifications/{notification_id}/read", response_model=NotificationOut)
async def read_notification(notification_id: str, user: dict = Depends(get_current_user)):
    # The recipient is part of the filter: someone else's notification is simply not found.
    updated = await get_db().notifications.find_one_and_update(
        {"_id": parse_object_id(notification_id), "recipient_id": user["_id"]},
        {"$set": {"is_read": True, "is_delivered": True}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return notification_out(updated)


@router.post("/api/notifications/read-all")
async def read_all_notifications(user: dict = Depends(get_current_user)):
    result = await get_db().notifications.update_many(
        {"recipient_id": user["_id"], "is_read": False}, {"$set": {"is_read": True, "is_delivered": True}}
    )
    return {"marked": result.modified_count}


# ================================================================ chat actions: rent offers
# (Sale offers made in the chat use POST /api/marketplace/offers and /offers/{id}/respond, which post and update the
# OFFER_PROPOSAL_CARD themselves.)


def _rent_offer_out(doc: dict) -> RentOfferOut:
    return RentOfferOut.model_validate(serialize_doc(doc))


@router.post("/api/chat/rent-offers", response_model=RentOfferOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(CHAT_LIMIT, key_func=user_or_ip)
async def make_rent_offer(request: Request, payload: RentOfferCreate, user: dict = Depends(require_roles(*TENANT_ROLES))):
    """A tenant proposes a monthly rent from the chat. It carries the same advance a rent request logs, so once the
    owner accepts it becomes a booking that is ready for the handshake QR."""
    db = get_db()
    listing = await db.listings.find_one({"_id": parse_object_id(payload.listing_id), **RENT_ONLY})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    await qr_handshake.check_not_tenant_already(listing, user)
    qr_handshake.check_can_rent(listing, user)
    unit = qr_handshake.resolve_unit(listing, payload)
    qr_handshake.check_move_in_date(payload.move_in_date)
    owner = await db.users.find_one({"_id": listing["lister_id"]}, {"full_name": 1})
    now = _now()
    offer = {
        "listing_id": listing["_id"],
        "listing_title": listing["title"],
        "unit": unit,
        "listed_rent": qr_handshake.unit_costs(listing, unit)["rent"] if unit else listing["effective_rent"],
        "owner_id": listing["lister_id"],
        "tenant_id": user["_id"],
        "owner": {"id": listing["lister_id"], "full_name": owner["full_name"] if owner else "Owner"},
        "tenant": {"id": user["_id"], "full_name": user["full_name"]},
        "status": RentOfferStatus.AWAITING_OWNER.value,
        "is_open": True,
        "amount": payload.amount,
        "deposit_amount": payload.deposit_amount,
        "move_in_date": payload.move_in_date.isoformat(),
        "payment": {"method": payload.payment_method.value, "reference": payload.payment_reference.strip()},
        "booking_id": None,
        "history": [
            {"at": now, "actor": "TENANT", "event": "OFFERED", "amount": payload.amount, "deposit_amount": payload.deposit_amount, "note": payload.note}
        ],
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.rent_offers.insert_one(offer)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an open rent proposal for this place")
    await chat_cards.offer_made(offer, user)
    return _rent_offer_out(offer)


async def _book_accepted_rent(offer: dict) -> dict:
    """Turn an accepted rent offer into a rent request at the agreed rent, ready for the owner's QR. If the tenant
    already has an open request for the place, its rent is updated instead (the advance already logged stands)."""
    db = get_db()
    listing = await db.listings.find_one({"_id": offer["listing_id"], **RENT_ONLY})
    tenant = await db.users.find_one({"_id": offer["tenant_id"]})
    if listing is None or tenant is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This place is no longer available")
    await qr_handshake.check_not_tenant_already(listing, tenant)
    qr_handshake.check_can_rent(listing, tenant, offer.get("unit"))
    move_in = date.fromisoformat(offer["move_in_date"])
    qr_handshake.check_move_in_date(move_in)

    existing = await db.bookings.find_one({"listing_id": listing["_id"], "tenant_id": tenant["_id"], "is_open": True})
    if existing is None:
        return await qr_handshake.create_booking(
            listing,
            tenant,
            move_in_date=move_in,
            deposit_amount=offer["deposit_amount"],
            payment_method=DepositMethod(offer["payment"]["method"]),
            payment_reference=offer["payment"]["reference"],
            message=f"Rent agreed in chat: BDT {offer['amount']:,} a month.",
            unit=offer.get("unit"),
            agreed_rent=offer["amount"],
        )
    now = _now()
    updated = await db.bookings.find_one_and_update(
        {"_id": existing["_id"], "tenant_id": tenant["_id"], "is_open": True},
        {
            # The room or seat agreed in the chat replaces whatever the earlier request asked for.
            "$set": {"agreed_rent": offer["amount"], "unit": offer.get("unit"), "move_in_date": offer["move_in_date"], "updated_at": now},
            "$push": {
                "escrow_ledger": {
                    "at": now,
                    "status": existing["escrow_status"],
                    "note": f"Rent agreed in chat at BDT {offer['amount']:,} a month; the advance already logged stands.",
                }
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The rent request changed in the meantime. Reload and try again.")
    await chat_cards.sync_qr_cards(updated)  # a code already in the chat now shows the agreed rent
    return updated


@router.post("/api/chat/rent-offers/{offer_id}/respond", response_model=RentOfferOut)
async def respond_to_rent_offer(offer_id: str, payload: RentOfferResponse, user: dict = Depends(get_current_user)):
    """Turn-based like sale offers: whoever didn't make the latest proposal accepts, rejects or counters it, so the
    owner is the one who accepts a tenant's terms. Only the tenant can withdraw."""
    db = get_db()
    offer = await db.rent_offers.find_one(
        {"_id": parse_object_id(offer_id), "$or": [{"owner_id": user["_id"]}, {"tenant_id": user["_id"]}]}
    )
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rent proposal not found")
    actor = "OWNER" if offer["owner_id"] == user["_id"] else "TENANT"
    current = offer["status"]
    if current not in OPEN_RENT_OFFER_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal is already closed")

    changes: dict = {}
    if payload.action == "WITHDRAW":
        if actor != "TENANT":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the tenant can withdraw a proposal")
        new_status, event = RentOfferStatus.WITHDRAWN, "WITHDRAWN"
    else:
        turn = "OWNER" if current == RentOfferStatus.AWAITING_OWNER else "TENANT"
        if actor != turn:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Waiting for the {turn.lower()} to respond")
        if payload.action == "ACCEPT":
            new_status, event = RentOfferStatus.ACCEPTED, "ACCEPTED"
        elif payload.action == "REJECT":
            new_status, event = RentOfferStatus.REJECTED, "REJECTED"
        else:
            changes = {"amount": payload.amount}
            if payload.deposit_amount is not None:
                changes["deposit_amount"] = payload.deposit_amount
            new_status = RentOfferStatus.AWAITING_TENANT if actor == "OWNER" else RentOfferStatus.AWAITING_OWNER
            event = "COUNTERED"

    now = _now()
    entry = {
        "at": now,
        "actor": actor,
        "event": event,
        "amount": changes.get("amount", offer["amount"]),
        "deposit_amount": changes.get("deposit_amount", offer["deposit_amount"]),
        "note": payload.note,
    }
    party = "owner_id" if actor == "OWNER" else "tenant_id"
    updated = await db.rent_offers.find_one_and_update(
        # Matching the status we read makes each turn atomic against a concurrent response.
        {"_id": offer["_id"], "status": current, party: user["_id"]},
        {
            "$set": {**changes, "status": new_status.value, "is_open": new_status in OPEN_RENT_OFFER_STATUSES, "updated_at": now},
            "$push": {"history": entry},
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The proposal changed while you were responding. Reload it.")

    if new_status == RentOfferStatus.ACCEPTED:
        try:
            booking = await _book_accepted_rent(updated)
        except HTTPException:
            # Nothing to rent any more (or the tenant can't): the proposal goes back to where it was.
            await db.rent_offers.update_one(
                {"_id": offer["_id"], "status": RentOfferStatus.ACCEPTED.value},
                {"$set": {"status": current, "is_open": True, "updated_at": offer["updated_at"]}, "$pop": {"history": 1}},
            )
            raise
        updated = await db.rent_offers.find_one_and_update(
            {"_id": offer["_id"]}, {"$set": {"booking_id": booking["_id"]}}, return_document=ReturnDocument.AFTER
        )
    await chat_cards.offer_changed(updated, user)
    return _rent_offer_out(updated)


# ================================================================ chat actions: handshake QR


@router.post("/api/chat/qr/send", response_model=ChatMessageOut)
@limiter.limit(QR_LIMIT, key_func=user_or_ip)
async def send_confirmation_qr(
    request: Request, payload: ChatQrSend, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)
):
    """The owner sends (or regenerates) the handshake QR for this tenant's open rent request, straight into the chat.
    Same generator as the dashboard: handshake secret, 24 h expiry, a fresh single-use nonce that voids older codes."""
    booking = await get_db().bookings.find_one(
        {
            "listing_id": parse_object_id(payload.property_id),
            "owner_id": user["_id"],  # only the listing's owner finds the request at all
            "tenant_id": parse_object_id(payload.tenant_id),
            "is_open": True,
        }
    )
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no open rent request from this tenant to approve")
    token, _expires_at, updated = await qr_handshake.issue_handshake_qr(booking, user, background_tasks)
    card = await chat_cards.send_qr_card(updated, user, token)
    return message_out(card)

