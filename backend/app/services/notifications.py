"""Chat messages and notifications: storing them, pushing them live, and queueing them for users who are offline.

Every notification is written to MongoDB first with `is_delivered: False`. If the recipient has a socket open it is
pushed at once and marked delivered; otherwise it waits for their next connection (see the OFFLINE_SYNC_BUNDLE in
app/routers/chat_and_notifications.py).
"""

import functools
import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.database import get_db, serialize_doc
from app.core.ws_manager import ws_manager
from app.schemas.chat import ChatMessageOut, MessageType, NotificationOut, NotificationType

logger = logging.getLogger(__name__)

PREVIEW_CHARS = 140
# Card fields every action_payload carries, null where they don't apply.
CARD_FIELDS = ("reference_id", "status", "scheduled_date", "scheduled_time", "proposed_amount", "qr_token", "expires_at")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oid(value: Any) -> ObjectId:
    return value if isinstance(value, ObjectId) else ObjectId(value)


def best_effort(func):
    """For side effects that run after the main write has committed (a visit booked, an offer accepted). A failure
    to notify is logged, never turned into an error for an action that already happened."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            logger.exception("%s failed", func.__name__)
            return None

    return wrapper


def thread_id_for(property_id: Any, user_a: Any, user_b: Any) -> str:
    """One thread per listing and pair of people, whoever writes first."""
    low, high = sorted((str(user_a), str(user_b)))
    return f"{property_id}:{low}:{high}"


def card_payload(**fields: Any) -> dict:
    return {key: fields.pop(key, None) for key in CARD_FIELDS} | fields


def message_out(doc: dict) -> ChatMessageOut:
    data = serialize_doc(doc)
    payload = data.get("action_payload")
    if payload is not None:
        expires_at = payload.get("expires_at")
        # A handshake code is only ever shown while it can still be used.
        if payload.get("status") != "ACTIVE" or (expires_at is not None and expires_at <= _now()):
            payload["qr_token"] = None
    return ChatMessageOut.model_validate(data)


def notification_out(doc: dict) -> NotificationOut:
    return NotificationOut.model_validate(serialize_doc(doc))


async def _mark_delivered(collection: str, doc: dict) -> None:
    await get_db()[collection].update_one({"_id": doc["_id"]}, {"$set": {"is_delivered": True}})
    doc["is_delivered"] = True


async def notify(
    recipient_id: Any,
    type_: NotificationType,
    title: str,
    message: str,
    *,
    sender_id: Any = None,
    property_id: Any = None,
    metadata: dict | None = None,
) -> dict:
    """Store a notification and push it live (`{"type": <notification type>, "notification": ...}`) if the
    recipient is online. Offline, it stays queued with is_delivered False."""
    doc = {
        "recipient_id": _oid(recipient_id),
        "sender_id": _oid(sender_id) if sender_id is not None else None,
        "property_id": _oid(property_id) if property_id is not None else None,
        "type": type_.value,
        "title": title,
        "message": message,
        "metadata": metadata or {},
        "is_delivered": False,
        "is_read": False,
        "created_at": _now(),
    }
    await get_db().notifications.insert_one(doc)
    if await ws_manager.send_personal_json(recipient_id, {"type": type_.value, "notification": notification_out(doc)}):
        await _mark_delivered("notifications", doc)
    return doc


async def _queue_message_notification(message: dict, sender_name: str, listing_title: str) -> dict:
    """One unread NEW_MESSAGE notification per thread: later messages update it rather than pile up in the bell."""
    db = get_db()
    query = {
        "recipient_id": message["receiver_id"],
        "type": NotificationType.NEW_MESSAGE.value,
        "metadata.thread_id": message["thread_id"],
        "is_read": False,
    }
    preview = message["content"] if len(message["content"]) <= PREVIEW_CHARS else message["content"][: PREVIEW_CHARS - 1] + "…"
    update = {
        "$set": {
            "sender_id": message["sender_id"],
            "property_id": message["property_id"],
            "title": f"New message from {sender_name}",
            "message": preview,
            "metadata.chat_with": str(message["sender_id"]),
            "metadata.listing_title": listing_title,
            "metadata.message_id": str(message["_id"]),
            "is_delivered": False,
            "created_at": message["created_at"],
        },
        "$inc": {"metadata.unread_count": 1},
    }
    try:
        return await db.notifications.find_one_and_update(query, update, upsert=True, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        # Two messages raced to create the thread's notification; the unique index let one win, so update that one.
        return await db.notifications.find_one_and_update(query, update, return_document=ReturnDocument.AFTER)


async def post_message(
    *,
    property_id: ObjectId,
    sender: dict,
    receiver_id: ObjectId,
    content: str,
    listing_title: str,
    message_type: MessageType = MessageType.TEXT,
    action_payload: dict | None = None,
    queue_notification: bool = True,
) -> dict:
    """Save a chat message (or action card), push it to the receiver if online, and echo it to the sender's other
    tabs. Action cards pass `queue_notification=False`: their own notification (visit, offer, QR) says what happened."""
    now = _now()
    message = {
        "thread_id": thread_id_for(property_id, sender["_id"], receiver_id),
        "property_id": property_id,
        "sender_id": sender["_id"],
        "receiver_id": receiver_id,
        "content": content,
        "message_type": message_type.value,
        "action_payload": action_payload,
        "created_at": now,
        "updated_at": now,
        "is_delivered": False,
        "is_read": False,
    }
    await get_db().chat_messages.insert_one(message)
    notification = await _queue_message_notification(message, sender["full_name"], listing_title) if queue_notification else None

    event = {
        "type": "NEW_CHAT_MESSAGE",
        "message": message_out(message),
        "notification": notification_out(notification) if notification else None,
    }
    if await ws_manager.send_personal_json(receiver_id, event):
        await _mark_delivered("chat_messages", message)
        if notification:
            await _mark_delivered("notifications", notification)
    await ws_manager.send_personal_json(sender["_id"], {"type": "CHAT_MESSAGE_SENT", "message": message_out(message)})
    return message


async def broadcast_card(card: dict) -> None:
    event = {"type": "CHAT_CARD_UPDATED", "message": message_out(card)}
    for user_id in {card["sender_id"], card["receiver_id"]}:
        await ws_manager.send_personal_json(user_id, event)


async def update_cards(message_type: MessageType, reference_id: Any, payload: dict) -> list[dict]:
    """Replace the state of every card about `reference_id` and push CHAT_CARD_UPDATED to both people in the chat."""
    db = get_db()
    query = {"message_type": message_type.value, "action_payload.reference_id": str(reference_id)}
    await db.chat_messages.update_many(query, {"$set": {"action_payload": payload, "updated_at": _now()}})
    cards = await db.chat_messages.find(query).to_list(50)
    for card in cards:
        await broadcast_card(card)
    return cards


async def mark_thread_read(thread_id: str, reader_id: ObjectId) -> int:
    """Mark every message the reader received in this thread as read, tell the other person (read receipts), and
    clear the thread's NEW_MESSAGE notification. Returns how many messages changed."""
    db = get_db()
    unread = await db.chat_messages.find(
        {"thread_id": thread_id, "receiver_id": reader_id, "is_read": False}, {"sender_id": 1}
    ).to_list(None)
    if not unread:
        return 0
    ids = [doc["_id"] for doc in unread]
    await db.chat_messages.update_many({"_id": {"$in": ids}}, {"$set": {"is_read": True, "is_delivered": True}})
    await db.notifications.update_many(
        {"recipient_id": reader_id, "type": NotificationType.NEW_MESSAGE.value, "metadata.thread_id": thread_id, "is_read": False},
        {"$set": {"is_read": True, "is_delivered": True}},
    )
    receipt = {"type": "MESSAGES_READ", "thread_id": thread_id, "reader_id": str(reader_id), "message_ids": [str(i) for i in ids]}
    for sender_id in {doc["sender_id"] for doc in unread}:
        await ws_manager.send_personal_json(sender_id, receipt)
    await ws_manager.send_personal_json(reader_id, receipt)  # the reader's other tabs clear their badges too
    return len(ids)


async def chat_partners(user_id: ObjectId) -> set[str]:
    db = get_db()
    sent_to = await db.chat_messages.distinct("receiver_id", {"sender_id": user_id})
    heard_from = await db.chat_messages.distinct("sender_id", {"receiver_id": user_id})
    return {str(i) for i in (*sent_to, *heard_from)}


async def broadcast_presence(user_id: ObjectId, online: bool) -> None:
    """Tell the user's chat partners who are online right now that the user came online or went offline."""
    watching = ws_manager.online_users() - {str(user_id)}
    if not watching:
        return
    event = {"type": "PRESENCE", "user_id": str(user_id), "online": online}
    for partner in await chat_partners(user_id) & watching:
        await ws_manager.send_personal_json(partner, event)
