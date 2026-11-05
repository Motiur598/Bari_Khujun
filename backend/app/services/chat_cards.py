"""Action cards in chat (visit requests, offers, handshake QR codes), kept in step with the records they show.

Each card's `action_payload` is derived from its record by one of the `*_card` functions below. The routers call the
hooks here after a record changes, which rewrite the card and push CHAT_CARD_UPDATED to both people. Changes made
elsewhere (a listing deleted, an account banned) are caught up by `refresh_cards` the next time a chat is read.
"""

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.core.database import get_db
from app.schemas.booking import LEASE_STATUSES, BookingStatus, unit_label
from app.schemas.chat import MessageType, NotificationType
from app.schemas.marketplace import DHAKA_TZ, VisitStatus
from app.services.notifications import best_effort, broadcast_card, card_payload, notify, post_message, update_cards


def _now() -> datetime:
    return datetime.now(timezone.utc)


def taka(amount: int) -> str:
    return f"BDT {amount:,}"


def visit_day(starts_at: datetime) -> str:
    local = starts_at.astimezone(DHAKA_TZ)
    return f"{local:%a} {local.day} {local:%b %Y}"


def visit_time(starts_at: datetime) -> str:
    return f"{starts_at.astimezone(DHAKA_TZ):%I:%M %p}".lstrip("0")


# ================================================================ visits


def visit_card_state(visit: dict) -> str:
    if visit["status"] == VisitStatus.BOOKED:
        return visit.get("approval") or "PENDING"
    return "DECLINED" if visit.get("approval") == "DECLINED" else "CANCELLED"


def visit_card(visit: dict) -> dict:
    local = visit["starts_at"].astimezone(DHAKA_TZ)
    return card_payload(
        reference_id=str(visit["_id"]),
        status=visit_card_state(visit),
        scheduled_date=local.date().isoformat(),
        scheduled_time=f"{local:%H:%M}",
        starts_at=visit["starts_at"],
        mode=visit["mode"],
        note=visit.get("note"),
    )


def _visit_metadata(visit: dict, actor_id: ObjectId) -> dict:
    local = visit["starts_at"].astimezone(DHAKA_TZ)
    return {
        "visit_id": str(visit["_id"]),
        "property_id": str(visit["listing_id"]),
        "visit_date": local.date().isoformat(),
        "visit_time": f"{local:%H:%M}",
        "listing_mode": visit.get("listing_mode", "RENT"),
        "chat_with": str(actor_id),
    }


@best_effort
async def visit_booked(visit: dict, visitor: dict) -> None:
    """Feature 10 hook: the visit request lands in the chat with the lister, and the lister gets an alert."""
    day, time = visit_day(visit["starts_at"]), visit_time(visit["starts_at"])
    await post_message(
        property_id=visit["listing_id"],
        sender=visitor,
        receiver_id=visit["host_id"],
        content=f"Visit request: {day} at {time}",
        listing_title=visit["listing_title"],
        message_type=MessageType.VISIT_REQUEST_CARD,
        action_payload=visit_card(visit),
        queue_notification=False,
    )
    await notify(
        visit["host_id"],
        NotificationType.VISIT_SCHEDULED,
        "📅 New House Visit Scheduled!",
        f"{visitor['full_name']} fixed a time to visit '{visit['listing_title']}' on {day} at {time}.",
        sender_id=visitor["_id"],
        property_id=visit["listing_id"],
        metadata={**_visit_metadata(visit, visitor["_id"]), "visitor_id": str(visitor["_id"])},
    )


_VISIT_UPDATES = {
    ("APPROVED", True): ("✅ Visit time approved", "{actor} approved your visit to '{title}' on {day} at {time}."),
    ("APPROVED", False): ("✅ New visit time accepted", "{actor} accepted {day} at {time} for the visit to '{title}'."),
    ("RESCHEDULE_PROPOSED", True): ("🕒 New visit time proposed", "{actor} proposed {day} at {time} for your visit to '{title}'."),
    ("DECLINED", True): ("❌ Visit declined", "{actor} declined the visit to '{title}' on {day} at {time}."),
    ("CANCELLED", True): ("Visit cancelled", "{actor} cancelled the visit to '{title}' on {day} at {time}."),
    ("CANCELLED", False): ("Visit cancelled", "{actor} cancelled the visit to '{title}' on {day} at {time}."),
}


@best_effort
async def visit_changed(visit: dict, actor: dict) -> None:
    await update_cards(MessageType.VISIT_REQUEST_CARD, visit["_id"], visit_card(visit))
    state = visit_card_state(visit)
    by_host = actor["_id"] == visit["host_id"]
    title, text = _VISIT_UPDATES.get((state, by_host), _VISIT_UPDATES[("CANCELLED", by_host)])
    await notify(
        visit["visitor_id"] if by_host else visit["host_id"],
        NotificationType.VISIT_STATUS_CHANGED,
        title,
        text.format(
            actor=actor["full_name"], title=visit["listing_title"], day=visit_day(visit["starts_at"]), time=visit_time(visit["starts_at"])
        ),
        sender_id=actor["_id"],
        property_id=visit["listing_id"],
        metadata={**_visit_metadata(visit, actor["_id"]), "status": state},
    )


# ================================================================ offers (sale offers and rent offers)


def _is_rent(offer: dict) -> bool:
    return "tenant_id" in offer


def offer_parties(offer: dict) -> tuple[ObjectId, ObjectId]:
    """(lister, counterparty): seller and buyer for a sale offer, owner and tenant for a rent offer."""
    return (offer["owner_id"], offer["tenant_id"]) if _is_rent(offer) else (offer["seller_id"], offer["buyer_id"])


def offer_card(offer: dict) -> dict:
    if _is_rent(offer):
        return card_payload(
            reference_id=str(offer["_id"]),
            status=offer["status"],
            proposed_amount=offer["amount"],
            kind="RENT",
            unit_label=unit_label(offer.get("unit")),
            listed_rent=offer["listed_rent"],
            deposit_amount=offer["deposit_amount"],
            move_in_date=offer["move_in_date"],
            booking_id=str(offer["booking_id"]) if offer.get("booking_id") else None,
        )
    return card_payload(
        reference_id=str(offer["_id"]),
        status=offer["status"],
        proposed_amount=offer["amount"],
        kind="SALE",
        offer_type=offer["offer_type"],
        token_amount=offer.get("token_amount"),
        asking_price=offer["asking_price"],
    )


def _offer_summary(offer: dict) -> str:
    if _is_rent(offer):
        label = unit_label(offer.get("unit"))
        return f"{taka(offer['amount'])} a month" + (f" ({label})" if label else "")
    token = offer.get("token_amount")
    return f"{taka(offer['amount'])}" + (f" with {taka(token)} bayna" if token else "")


@best_effort
async def offer_made(offer: dict, proposer: dict) -> None:
    lister_id, _ = offer_parties(offer)
    summary = _offer_summary(offer)
    await post_message(
        property_id=offer["listing_id"],
        sender=proposer,
        receiver_id=lister_id,
        content=f"{'Rent proposal' if _is_rent(offer) else 'Offer'}: {summary}",
        listing_title=offer["listing_title"],
        message_type=MessageType.OFFER_PROPOSAL_CARD,
        action_payload=offer_card(offer),
        queue_notification=False,
    )
    await notify(
        lister_id,
        NotificationType.OFFER_UPDATE,
        "💰 New rent proposal" if _is_rent(offer) else "💰 New offer",
        f"{proposer['full_name']} proposed {summary} for '{offer['listing_title']}'.",
        sender_id=proposer["_id"],
        property_id=offer["listing_id"],
        metadata={"offer_id": str(offer["_id"]), "kind": "RENT" if _is_rent(offer) else "SALE", "chat_with": str(proposer["_id"])},
    )


_OFFER_UPDATES = {
    "COUNTERED": ("↩️ Counter-offer", "{actor} countered with {summary} for '{title}'."),
    "ACCEPTED": ("🤝 Offer accepted", "{actor} accepted {summary} for '{title}'."),
    "REJECTED": ("Offer declined", "{actor} declined the offer of {summary} for '{title}'."),
    "WITHDRAWN": ("Offer withdrawn", "{actor} withdrew the offer of {summary} for '{title}'."),
    "CLOSED": ("Offer closed", "Your offer of {summary} for '{title}' was closed: {note}"),
}


@best_effort
async def offer_changed(offer: dict, actor: dict | None) -> None:
    """After a response (accept, counter, reject, withdraw) or a system close (`actor` None)."""
    await update_cards(MessageType.OFFER_PROPOSAL_CARD, offer["_id"], offer_card(offer))
    lister_id, counterparty_id = offer_parties(offer)
    last = offer["history"][-1]
    if actor is None:
        recipient, sender_id = counterparty_id, None
    else:
        recipient = counterparty_id if actor["_id"] == lister_id else lister_id
        sender_id = actor["_id"]
    title, text = _OFFER_UPDATES.get(last["event"], _OFFER_UPDATES["CLOSED"])
    await notify(
        recipient,
        NotificationType.OFFER_UPDATE,
        title,
        text.format(
            actor=actor["full_name"] if actor else "Bari Khujun", summary=_offer_summary(offer), title=offer["listing_title"],
            note=last.get("note") or "the listing is no longer open",
        ),
        sender_id=sender_id,
        property_id=offer["listing_id"],
        metadata={
            "offer_id": str(offer["_id"]),
            "kind": "RENT" if _is_rent(offer) else "SALE",
            "status": offer["status"],
            "chat_with": str(lister_id if recipient == counterparty_id else counterparty_id),
        },
    )


# ================================================================ handshake QR


def _same_instant(a: datetime | None, b: datetime | None) -> bool:
    # MongoDB keeps milliseconds, so a timestamp that has been stored can differ from the in-memory one by < 1 ms.
    return a is not None and b is not None and abs((a - b).total_seconds()) < 0.001


def qr_card_state(booking: dict, issued_at: datetime | None) -> str:
    if booking["status"] in LEASE_STATUSES:
        return "CONFIRMED"
    qr = booking.get("qr") or {}
    if booking["status"] != BookingStatus.APPROVED or not _same_instant(qr.get("issued_at"), issued_at):
        return "REVOKED"  # declined, cancelled, or replaced by a newer code
    return "ACTIVE" if qr["expires_at"] > _now() else "EXPIRED"


def qr_card(booking: dict, *, token: str | None, issued_at: datetime | None) -> dict:
    state = qr_card_state(booking, issued_at)
    lease = booking.get("lease") or {}
    return card_payload(
        reference_id=str(booking["_id"]),
        status=state,
        qr_token=token if state == "ACTIVE" else None,
        expires_at=(booking.get("qr") or {}).get("expires_at") if state in ("ACTIVE", "EXPIRED") else None,
        issued_at=issued_at,
        agreed_rent=booking["agreed_rent"],
        deposit_amount=booking["deposit"]["amount"],
        move_in_date=booking["move_in_date"],
        lease_ready=bool(lease.get("path")),
        lease_number=lease.get("number"),
    )


async def send_qr_card(booking: dict, owner: dict, token: str) -> dict:
    """Put a freshly issued code in the chat: the thread's live QR card is refreshed in place, or a new one posted."""
    issued_at = booking["qr"]["issued_at"]
    payload = qr_card(booking, token=token, issued_at=issued_at)
    db = get_db()
    card = await db.chat_messages.find_one(
        {
            "message_type": MessageType.QR_CONFIRMATION_CARD.value,
            "action_payload.reference_id": str(booking["_id"]),
            "action_payload.status": {"$ne": "CONFIRMED"},
        },
        sort=[("_id", -1)],
    )
    if card is not None:
        await db.chat_messages.update_one({"_id": card["_id"]}, {"$set": {"action_payload": payload, "updated_at": _now()}})
        card["action_payload"] = payload
        await broadcast_card(card)
    else:
        card = await post_message(
            property_id=booking["listing_id"],
            sender=owner,
            receiver_id=booking["tenant_id"],
            content=f"Confirmation QR for {booking['listing']['title']}",
            listing_title=booking["listing"]["title"],
            message_type=MessageType.QR_CONFIRMATION_CARD,
            action_payload=payload,
            queue_notification=False,
        )
    await notify(
        booking["tenant_id"],
        NotificationType.QR_UPDATE,
        "📲 Confirmation QR received",
        f"{owner['full_name']} sent a confirmation QR for '{booking['listing']['title']}'. Confirm the deal in the chat before it expires.",
        sender_id=owner["_id"],
        property_id=booking["listing_id"],
        metadata={"booking_id": str(booking["_id"]), "owner_id": str(owner["_id"]), "chat_with": str(owner["_id"])},
    )
    return card


@best_effort
async def sync_qr_cards(booking: dict) -> None:
    """Re-derive the booking's QR cards (confirmed, declined, cancelled or replaced) and push the ones that changed."""
    db = get_db()
    cards = await db.chat_messages.find(
        {"message_type": MessageType.QR_CONFIRMATION_CARD.value, "action_payload.reference_id": str(booking["_id"])}
    ).to_list(20)
    for card in cards:
        old = card["action_payload"]
        payload = qr_card(booking, token=old.get("qr_token"), issued_at=old.get("issued_at"))
        if payload != old:
            await db.chat_messages.update_one({"_id": card["_id"]}, {"$set": {"action_payload": payload, "updated_at": _now()}})
            card["action_payload"] = payload
            await broadcast_card(card)


@best_effort
async def booking_approved(booking: dict, owner: dict, newly_approved: bool) -> None:
    """The owner showed a handshake code from the dashboard. Any code sent in the chat has just been replaced, so
    its card stops offering it, and on the first approval the tenant hears about it."""
    await sync_qr_cards(booking)
    if not newly_approved:
        return
    await notify(
        booking["tenant_id"],
        NotificationType.QR_UPDATE,
        "✅ Rent request approved",
        f"{owner['full_name']} approved your request for '{booking['listing']['title']}'. Scan their handshake QR to confirm.",
        sender_id=owner["_id"],
        property_id=booking["listing_id"],
        metadata={"booking_id": str(booking["_id"]), "owner_id": str(owner["_id"]), "chat_with": str(owner["_id"])},
    )


@best_effort
async def handshake_confirmed(booking: dict, tenant: dict) -> None:
    await sync_qr_cards(booking)
    await notify(
        booking["owner_id"],
        NotificationType.QR_UPDATE,
        "🎉 Deal confirmed",
        f"{tenant['full_name']} confirmed '{booking['listing']['title']}'. The digital lease has been issued.",
        sender_id=tenant["_id"],
        property_id=booking["listing_id"],
        metadata={"booking_id": str(booking["_id"]), "owner_id": str(booking["owner_id"]), "chat_with": str(tenant["_id"])},
    )


# ================================================================ catching up on reads


async def refresh_cards(messages: list[dict]) -> None:
    """Bring the cards in `messages` up to date with their records, in place (one query per card type)."""
    cards = [m for m in messages if m.get("message_type", MessageType.TEXT.value) != MessageType.TEXT.value and m.get("action_payload")]
    if not cards:
        return
    db = get_db()

    def ids(message_type: MessageType, **match: Any) -> list[ObjectId]:
        return [
            ObjectId(c["action_payload"]["reference_id"])
            for c in cards
            if c["message_type"] == message_type.value and all(c["action_payload"].get(k) == v for k, v in match.items())
        ]

    records: dict[str, dict] = {}
    sources = (
        (db.visit_slots, ids(MessageType.VISIT_REQUEST_CARD)),
        (db.offers, ids(MessageType.OFFER_PROPOSAL_CARD, kind="SALE")),
        (db.rent_offers, ids(MessageType.OFFER_PROPOSAL_CARD, kind="RENT")),
        (db.bookings, ids(MessageType.QR_CONFIRMATION_CARD)),
    )
    for collection, wanted in sources:
        if wanted:
            for doc in await collection.find({"_id": {"$in": wanted}}).to_list(None):
                records[str(doc["_id"])] = doc

    for card in cards:
        old = card["action_payload"]
        record = records.get(old["reference_id"])
        if record is None:
            continue  # the record is gone (e.g. its listing was deleted); the card keeps its last known state
        if card["message_type"] == MessageType.VISIT_REQUEST_CARD.value:
            payload = visit_card(record)
        elif card["message_type"] == MessageType.OFFER_PROPOSAL_CARD.value:
            payload = offer_card(record)
        else:
            payload = qr_card(record, token=old.get("qr_token"), issued_at=old.get("issued_at"))
        if payload != old:
            await db.chat_messages.update_one({"_id": card["_id"]}, {"$set": {"action_payload": payload, "updated_at": _now()}})
            card["action_payload"] = payload
