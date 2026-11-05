import hashlib
import hmac
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

import jwt
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import find_for_party, get_db, parse_object_id
from app.core.limiter import QR_LIMIT, limiter, user_or_ip
from app.core.security import ISSUER, get_current_user, require_roles
from app.schemas.booking import (
    DEPOSIT_METHOD_LABELS,
    OPEN_BOOKING_STATUSES,
    BookingCreate,
    BookingOut,
    BookingStatus,
    DepositMethod,
    EscrowStatus,
    LeaseVerification,
    ListingAvailability,
    QrIssued,
    ScanRequest,
    ScanResult,
    UnitChoice,
    booking_to_out,
    unit_label,
)
from app.schemas.marketplace import DHAKA_TZ
from app.schemas.rental import ListingCategory, RentalStatus, RoomType, SubletType, find_room
from app.schemas.user import Role
from app.services import chat_cards
from app.services.governance import check_qr_spam, log_qr_event, nonce_fingerprint
from app.services.lease_pdf import build_lease_pdf
from app.services.listings import RENT_ONLY, area_label, change_room_seats
from app.utils.file_security import private_file_response

router = APIRouter(prefix="/api/qr-handshake", tags=["qr-handshake"])
logger = logging.getLogger(__name__)

# Handshake tokens are signed with their own secret and carry their own audience, so a login token can never be
# replayed as a handshake code (or the other way round), even if one secret leaked.
QR_AUDIENCE = "barikhujun:qr-handshake"
QR_REQUIRED_CLAIMS = ["exp", "iat", "aud", "iss", "booking_id", "property_id", "tenant_id", "nonce"]
TENANT_ROLES = (Role.BACHELOR_TENANT, Role.FAMILY_TENANT)
CATEGORY_TENANT_ROLE = {
    ListingCategory.FAMILY_FLAT: Role.FAMILY_TENANT,
    ListingCategory.BACHELOR_FLAT: Role.BACHELOR_TENANT,
    ListingCategory.BACHELOR_SEAT: Role.BACHELOR_TENANT,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ledger(status_: EscrowStatus, note: str) -> dict:
    return {"at": _now(), "status": status_.value, "note": note}


def _party(user: dict) -> dict:
    return {"id": user["_id"], "full_name": user["full_name"], "phone": user["phone"], "kyc_status": user["kyc_status"]}


def _is_available(listing: dict, unit: dict | None = None) -> bool:
    """Is anything left to rent here? Given a sublet booking's `unit`, is that seat or room still free?"""
    if listing.get("rental_status") == RentalStatus.RENTED.value:
        return False
    if unit is not None:
        room = find_room(listing, unit["room_id"])
        return room is not None and room["available_seats"] >= unit["seats"]
    return listing["category"] != ListingCategory.BACHELOR_SEAT or listing["seats"]["available_seats"] >= 1


def resolve_unit(listing: dict, choice: UnitChoice) -> dict | None:
    """What a tenant asks for on a bachelor tenant's sublet: its seat, a single room, or one seat or (while every
    seat is free) the whole of a shared room. None for every other listing, which is let as it is."""
    sublet = listing.get("sublet")
    if sublet is None:
        if choice.room_id is not None or choice.whole_room:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This listing isn't let room by room")
        return None
    room_id = choice.room_id
    if room_id is None and sublet["let_type"] == SubletType.SEAT:
        room_id = sublet["rooms"][0]["id"]
    if room_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose the room, and whether you want one seat or the whole room")
    room = find_room(listing, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")
    whole = room["room_type"] == RoomType.SINGLE or (room["room_type"] == RoomType.SHARED and choice.whole_room)
    unit = {"room_id": room["id"], "room_name": room["name"], "seats": room["seats"] if whole else 1, "whole_room": whole}
    if room["available_seats"] < unit["seats"]:
        if whole and room["seats"] > 1:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{room['name']} isn't completely free, so it can't be taken as a whole room")
        raise HTTPException(status.HTTP_409_CONFLICT, f"{room['name']} has no free seat left")
    return unit


def unit_costs(listing: dict, unit: dict) -> dict:
    """What the tenant of a sublet's seat or room pays each month as listed: rent and the optional charges, which are
    per seat (so a whole shared room pays them for each of its seats)."""
    room = find_room(listing, unit["room_id"]) or {}
    seats = unit["seats"]
    return {
        "rent": room.get("seat_rent", 0) * seats,
        "service_charge": room.get("service_charge", 0) * seats,
        "utility_estimate": room.get("utility_estimate", 0) * seats,
        "maid_estimate": room.get("maid_estimate", 0) * seats,
    }


def _lease_signature(booking_id: ObjectId, lease_number: str) -> str:
    message = f"lease:{booking_id}:{lease_number}".encode()
    return hmac.new(settings.qr_handshake_secret.encode(), message, hashlib.sha256).hexdigest()[:32]


async def _load_booking(booking_id: str | ObjectId, user: dict) -> dict:
    """A booking the user is a party to (ownership is in the query). Someone else's booking is a 403."""
    oid = booking_id if isinstance(booking_id, ObjectId) else parse_object_id(booking_id)
    return await find_for_party(get_db().bookings, {"_id": oid}, user["_id"], "booking")


async def _close_booking(booking: dict, new_status: BookingStatus, note: str, actor_filter: dict) -> dict:
    """Reject or cancel an open booking; its deposit is marked for refund and any issued QR stops working.

    `actor_filter` (e.g. {"owner_id": ...}) goes into the update filter, so only that party's request can change it.
    """
    updated = await get_db().bookings.find_one_and_update(
        {"_id": booking["_id"], **actor_filter, "status": {"$in": [s.value for s in OPEN_BOOKING_STATUSES]}},
        {
            "$set": {
                "status": new_status.value,
                "is_open": False,
                "qr": None,
                "escrow_status": EscrowStatus.REFUNDED.value,
                "updated_at": _now(),
            },
            "$push": {"escrow_ledger": _ledger(EscrowStatus.REFUNDED, note)},
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only open requests can be changed")
    qr = booking.get("qr") or {}
    if qr.get("nonce") and not qr.get("used_at"):
        await log_qr_event(booking, "REVOKED", qr["nonce"], note)
    await chat_cards.sync_qr_cards(updated)
    return updated


# ================================================================ Feature 15: request to rent + escrow


def check_can_rent(listing: dict, user: dict, unit: dict | None = None) -> None:
    """Who may ask to rent a place (and, given one, whether that seat or room is still free), shared by the request
    form and rent offers made in the chat."""
    if listing["lister_id"] == user["_id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't rent your own listing")
    if CATEGORY_TENANT_ROLE[listing["category"]] != user["role"]:
        who = "family tenants" if listing["category"] == ListingCategory.FAMILY_FLAT else "bachelor tenants"
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"This listing is only open to {who}")
    if not _is_available(listing, unit):
        raise HTTPException(status.HTTP_409_CONFLICT, "This place is no longer available")


async def check_not_tenant_already(listing: dict, user: dict) -> None:
    already = {"listing_id": listing["_id"], "tenant_id": user["_id"], "status": BookingStatus.CONFIRMED.value}
    if await get_db().bookings.find_one(already, {"_id": 1}):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already rent here")


def check_move_in_date(move_in_date: date) -> None:
    if move_in_date < _now().astimezone(DHAKA_TZ).date():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Move-in date can't be in the past")


def deposit_note(amount: int, method: DepositMethod, reference: str) -> str:
    return (
        f"Tenant logged an advance of BDT {amount:,} via {DEPOSIT_METHOD_LABELS[method]} "
        f"(ref. {reference}). Held until the owner responds."
    )


async def create_booking(
    listing: dict,
    user: dict,
    *,
    move_in_date: date,
    deposit_amount: int,
    payment_method: DepositMethod,
    payment_reference: str,
    message: str | None,
    unit: dict | None = None,
    agreed_rent: int | None = None,
) -> dict:
    """Insert an open rent request (for a sublet, for its seat or room `unit`). `agreed_rent` is the listed rent
    unless a rent offer settled on another figure."""
    owner = await get_db().users.find_one({"_id": listing["lister_id"]})
    reference = payment_reference.strip()
    now = _now()
    booking = {
        "listing_id": listing["_id"],
        "owner_id": listing["lister_id"],
        "tenant_id": user["_id"],
        "listing": {"title": listing["title"], "category": listing["category"], "area": area_label(listing["location"])},
        "unit": unit,
        "owner": _party(owner),
        "tenant": _party(user),
        "status": BookingStatus.PENDING_OWNER.value,
        "is_open": True,
        "agreed_rent": agreed_rent if agreed_rent is not None else unit_costs(listing, unit)["rent"] if unit else listing["effective_rent"],
        "move_in_date": move_in_date.isoformat(),
        "message": message,
        "deposit": {"amount": deposit_amount, "method": payment_method.value, "reference": reference},
        "escrow_status": EscrowStatus.PENDING_OWNER.value,
        "escrow_ledger": [_ledger(EscrowStatus.PENDING_OWNER, deposit_note(deposit_amount, payment_method, reference))],
        "qr": None,
        "confirmed_at": None,
        "lease": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await get_db().bookings.insert_one(booking)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an open request for this place")
    return booking


@router.post("/bookings", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def request_to_rent(payload: BookingCreate, user: dict = Depends(require_roles(*TENANT_ROLES))):
    listing = await get_db().listings.find_one({"_id": parse_object_id(payload.listing_id), **RENT_ONLY})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    await check_not_tenant_already(listing, user)
    check_can_rent(listing, user)
    unit = resolve_unit(listing, payload)
    check_move_in_date(payload.move_in_date)
    booking = await create_booking(
        listing,
        user,
        move_in_date=payload.move_in_date,
        deposit_amount=payload.deposit_amount,
        payment_method=payload.payment_method,
        payment_reference=payload.payment_reference,
        message=payload.message,
        unit=unit,
    )
    return booking_to_out(booking)


@router.get("/bookings/mine", response_model=list[BookingOut])
async def my_bookings(
    side: Annotated[str | None, Query(pattern="^(tenant|owner)$")] = None,
    user: dict = Depends(get_current_user),
):
    if side == "tenant":
        query = {"tenant_id": user["_id"]}
    elif side == "owner":
        query = {"owner_id": user["_id"]}
    else:
        query = {"$or": [{"tenant_id": user["_id"]}, {"owner_id": user["_id"]}]}
    docs = await get_db().bookings.find(query).sort("updated_at", -1).to_list(200)
    return [booking_to_out(doc) for doc in docs]


@router.get("/bookings/{booking_id}", response_model=BookingOut)
async def get_booking(booking_id: str, user: dict = Depends(get_current_user)):
    return booking_to_out(await _load_booking(booking_id, user))


@router.post("/bookings/{booking_id}/reject", response_model=BookingOut)
async def reject_booking(booking_id: str, user: dict = Depends(get_current_user)):
    booking = await _load_booking(booking_id, user)
    if booking["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can reject a request")
    return booking_to_out(
        await _close_booking(booking, BookingStatus.REJECTED, "Owner declined; deposit to be refunded.", {"owner_id": user["_id"]})
    )


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
async def cancel_booking(booking_id: str, user: dict = Depends(get_current_user)):
    booking = await _load_booking(booking_id, user)
    if booking["tenant_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the tenant can cancel a request")
    return booking_to_out(
        await _close_booking(
            booking, BookingStatus.CANCELLED, "Tenant withdrew the request; deposit to be refunded.", {"tenant_id": user["_id"]}
        )
    )


# ================================================================ Feature 11: owner-side QR generator


@router.post("/generate/{booking_id}", response_model=QrIssued)
@limiter.limit(QR_LIMIT, key_func=user_or_ip)
async def generate_handshake_qr(
    request: Request, booking_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)
):
    booking = await _load_booking(booking_id, user)
    token, expires_at, updated = await issue_handshake_qr(booking, user, background_tasks)
    # A code shown on the dashboard replaces any code sent in the chat, so those cards stop offering theirs.
    await chat_cards.booking_approved(updated, user, newly_approved=booking["status"] == BookingStatus.PENDING_OWNER)
    return QrIssued(token=token, expires_at=expires_at, booking=booking_to_out(updated))


async def issue_handshake_qr(booking: dict, user: dict, background_tasks: BackgroundTasks) -> tuple[str, datetime, dict]:
    """Approve the booking (if it isn't yet) and issue a fresh single-use handshake code for it.
    Returns (token, expiry, updated booking). Shared by the dashboard and the chat's "Send Confirmation QR"."""
    if booking["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can approve a request")
    if booking["status"] not in OPEN_BOOKING_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This request is already {booking['status'].lower()}")
    listing = await get_db().listings.find_one({"_id": booking["listing_id"]})
    if listing is None or not _is_available(listing, booking.get("unit")):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That room or seat has been taken" if booking.get("unit") else "The listing is no longer available"
        )

    now = _now()
    expires_at = now + timedelta(hours=settings.qr_token_ttl_hours)
    # A fresh nonce on every issue: regenerating the code makes any earlier code for this booking useless.
    nonce = secrets.token_urlsafe(16)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": QR_AUDIENCE,
            "booking_id": str(booking["_id"]),
            "property_id": str(booking["listing_id"]),
            "owner_id": str(booking["owner_id"]),
            "tenant_id": str(booking["tenant_id"]),
            "agreed_rent": booking["agreed_rent"],
            "nonce": nonce,
            "iat": now,
            "exp": expires_at,
        },
        settings.qr_handshake_secret,
        algorithm=settings.jwt_algorithm,
    )
    update: dict = {
        "$set": {
            "status": BookingStatus.APPROVED.value,
            "qr": {"nonce": nonce, "issued_at": now, "expires_at": expires_at, "used_at": None},
            "escrow_status": EscrowStatus.HELD.value,
            "updated_at": now,
        }
    }
    if booking["status"] == BookingStatus.PENDING_OWNER:
        update["$push"] = {
            "escrow_ledger": _ledger(EscrowStatus.HELD, "Owner approved. Deposit held in escrow until the QR handshake.")
        }
    updated = await get_db().bookings.find_one_and_update(
        {"_id": booking["_id"], "owner_id": user["_id"], "status": booking["status"]}, update, return_document=ReturnDocument.AFTER
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The request changed while approving. Reload and try again.")
    previous = (booking.get("qr") or {}).get("nonce")
    await log_qr_event(updated, "ISSUED", nonce, "Replaces an earlier code" if previous else None)
    # Scammer radar rule 1 runs after the response, so issuing a code never waits on it.
    background_tasks.add_task(check_qr_spam, user["_id"])
    return token, expires_at, updated


# ================================================================ Features 12 & 13: scan, verify, atomic lock


async def _explain_unusable_code(booking_id: ObjectId, nonce: str) -> HTTPException:
    booking = await get_db().bookings.find_one({"_id": booking_id})
    if booking is None:
        return HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    error = _unusable_reason(booking, nonce)
    await log_qr_event(booking, "SCAN_REJECTED", nonce, error.detail)
    return error


def _unusable_reason(booking: dict, nonce: str) -> HTTPException:
    # A spent or superseded code is a bad request (400), like an expired one. A request that was cancelled or
    # rejected in the meantime is a conflict with the booking's state (409).
    if booking["status"] == BookingStatus.CONFIRMED:
        return HTTPException(status.HTTP_400_BAD_REQUEST, "This code has already been used. The booking is confirmed.")
    if booking["status"] != BookingStatus.APPROVED:
        return HTTPException(status.HTTP_409_CONFLICT, f"This request was {booking['status'].lower()}")
    qr = booking.get("qr") or {}
    if qr.get("nonce") != nonce:
        return HTTPException(status.HTTP_400_BAD_REQUEST, "The owner has issued a newer code. Scan the latest one.")
    return HTTPException(status.HTTP_400_BAD_REQUEST, "This code has already been used")


async def _take_unit(booking: dict) -> dict | None:
    """Atomically claim one seat, a sublet's seat or room, or the whole flat. Returns the updated listing, or None if
    nothing is left.

    The availability checks live in the update filter, so two confirmations racing for the last seat can't both
    match: MongoDB applies single-document updates one at a time.
    """
    listing = await get_db().listings.find_one({"_id": booking["listing_id"]}, {"category": 1})
    if listing is None:
        return None
    base = {"_id": booking["listing_id"], "rental_status": RentalStatus.AVAILABLE.value, "suspended": {"$ne": True}}
    now = _now()
    if (unit := booking.get("unit")) is not None:
        # A sublet's seat or room: one update takes its seats, refreshes the totals and the search price, and flips
        # the listing to RENTED once nothing is free.
        return await get_db().listings.find_one_and_update(
            {**base, "sublet.rooms": {"$elemMatch": {"id": unit["room_id"], "available_seats": {"$gte": unit["seats"]}}}},
            change_room_seats(unit["room_id"], -unit["seats"], now),
            return_document=ReturnDocument.AFTER,
        )
    if listing["category"] == ListingCategory.BACHELOR_SEAT:
        # One update both decrements the seat and flips the listing to RENTED at zero, so no reader
        # ever sees 0 free seats on an AVAILABLE listing.
        return await get_db().listings.find_one_and_update(
            {**base, "seats.available_seats": {"$gt": 0}},
            [
                {"$set": {"seats.available_seats": {"$subtract": ["$seats.available_seats", 1]}, "updated_at": now}},
                {
                    "$set": {
                        "rental_status": {
                            "$cond": [{"$lte": ["$seats.available_seats", 0]}, RentalStatus.RENTED.value, RentalStatus.AVAILABLE.value]
                        }
                    }
                },
            ],
            return_document=ReturnDocument.AFTER,
        )
    return await get_db().listings.find_one_and_update(
        base,
        {"$set": {"rental_status": RentalStatus.RENTED.value, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )


def _decode_handshake_token(token: str) -> dict:
    try:
        return jwt.decode(
            token.strip(),
            settings.qr_handshake_secret,
            algorithms=[settings.jwt_algorithm],
            audience=QR_AUDIENCE,
            issuer=ISSUER,
            options={"require": QR_REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This code has expired. Ask the owner to generate a new one.")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This isn't a valid Bari Khujun handshake code")


async def _lease_snapshot(booking: dict, listing: dict, number: str, confirmed_at: datetime, signature: str) -> dict:
    users = {u["_id"]: u async for u in get_db().users.find({"_id": {"$in": [booking["owner_id"], booking["tenant_id"]]}})}

    def person(user_id):
        user = users[user_id]
        return {
            "full_name": user["full_name"],
            "phone": user["phone"],
            "email": user["email"],
            "kyc_status": user["kyc_status"],
            "documents": [{"doc_type": d["doc_type"], "doc_number": d["doc_number"]} for d in user.get("kyc_documents", [])],
        }

    split = (listing.get("seats") or {}).get("split")
    unit = booking.get("unit")
    costs = unit_costs(listing, unit) if unit else {
        "service_charge": split["per_seat_service_charge"] if split else listing["pricing"]["service_charge"],
        "utility_estimate": split["per_seat_utility"] if split else listing["pricing"]["utility_estimate"],
    }
    return {
        "number": number,
        "confirmed_at": confirmed_at,
        "listing": listing,
        "let_as": unit_label(unit),
        # A sublet's single or whole shared room is let as a room, not a seat.
        "agreement_title": "Shared Accommodation Agreement (Room)" if unit and unit["whole_room"] else None,
        "owner": person(booking["owner_id"]),
        "tenant": person(booking["tenant_id"]),
        "agreed_rent": booking["agreed_rent"],
        "service_charge": costs["service_charge"],
        "utility_estimate": costs["utility_estimate"],
        "deposit": booking["deposit"],
        "move_in_date": booking["move_in_date"],
        "escrow_ledger": booking["escrow_ledger"],
        "verify_url": f"{settings.app_base_url}/verify-lease/{booking['_id']}?sig={signature}",
    }


@router.post("/scan-and-confirm", response_model=ScanResult)
@limiter.limit(QR_LIMIT, key_func=user_or_ip)
async def scan_and_confirm(request: Request, payload: ScanRequest, user: dict = Depends(require_roles(*TENANT_ROLES))):
    # 1. Signature (handshake secret), expiry, audience, issuer and required claims.
    claims = _decode_handshake_token(payload.token)
    booking_id = parse_object_id(claims["booking_id"])
    listing_id = parse_object_id(claims["property_id"])
    if claims["tenant_id"] != str(user["_id"]):
        intended = await get_db().bookings.find_one({"_id": booking_id})
        if intended is not None:
            await log_qr_event(intended, "SCAN_REJECTED", claims["nonce"], f"Scanned by another tenant ({user['full_name']})")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This code was issued to a different tenant")

    # 2. One atomic update checks and consumes the code: this tenant, this listing, an approved booking and this
    #    exact, unexpired nonce. It confirms the booking and wipes the nonce in the same write, so a replay, or a
    #    second scan arriving in the same millisecond, matches nothing and is turned away.
    now = _now()
    booking = await get_db().bookings.find_one_and_update(
        {
            "_id": booking_id,
            "tenant_id": user["_id"],
            "listing_id": listing_id,
            "status": BookingStatus.APPROVED.value,
            "qr.nonce": claims["nonce"],
            "qr.used_at": None,
            "qr.expires_at": {"$gt": now},
        },
        {
            "$set": {
                "status": BookingStatus.CONFIRMED.value,
                "is_open": False,
                "confirmed_at": now,
                "qr.nonce": None,
                "qr.nonce_fp": nonce_fingerprint(claims["nonce"]),
                "qr.used_at": now,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if booking is None:
        raise await _explain_unusable_code(booking_id, claims["nonce"])

    # 3. Claim the seat, room or flat. If someone else got it first, this confirmation is undone and refunded.
    taken = await _take_unit(booking)
    if taken is None:
        await log_qr_event(booking, "SCAN_REJECTED", claims["nonce"], "The last unit was taken by another handshake")
        await get_db().bookings.update_one(
            {"_id": booking["_id"], "tenant_id": user["_id"], "status": BookingStatus.CONFIRMED.value, "lease": None},
            {
                "$set": {
                    "status": BookingStatus.CANCELLED.value,
                    "confirmed_at": None,
                    "escrow_status": EscrowStatus.REFUNDED.value,
                    "updated_at": _now(),
                },
                "$push": {
                    "escrow_ledger": _ledger(
                        EscrowStatus.REFUNDED, "The place was fully booked before this handshake; deposit to be refunded."
                    )
                },
            },
        )
        await chat_cards.sync_qr_cards(await get_db().bookings.find_one({"_id": booking["_id"]}))
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This place was booked by someone else moments ago. Your deposit is marked for refund."
        )

    await log_qr_event(booking, "CONFIRMED", claims["nonce"])

    # 4. Release escrow and record the lease. The unit is ours now, so this can't be undone.
    lease_number = f"BK-L-{now.astimezone(DHAKA_TZ):%Y%m%d}-{str(booking['_id'])[-6:].upper()}"
    signature = _lease_signature(booking["_id"], lease_number)
    ledger_entry = _ledger(EscrowStatus.RELEASED, "QR handshake confirmed. Deposit released to the owner.")
    confirmed = await get_db().bookings.find_one_and_update(
        {"_id": booking["_id"], "tenant_id": user["_id"], "status": BookingStatus.CONFIRMED.value},
        {
            "$set": {
                "escrow_status": EscrowStatus.RELEASED.value,
                "lease": {"number": lease_number, "signature": signature, "path": None, "generated_at": None},
                "updated_at": now,
            },
            "$push": {"escrow_ledger": ledger_entry},
        },
        return_document=ReturnDocument.AFTER,
    )
    try:
        snapshot = await _lease_snapshot(confirmed, taken, lease_number, now, signature)
        pdf = await run_in_threadpool(build_lease_pdf, snapshot)
        lease_path = settings.upload_dir / "leases" / f"{booking['_id']}.pdf"
        await run_in_threadpool(lease_path.parent.mkdir, parents=True, exist_ok=True)
        await run_in_threadpool(lease_path.write_bytes, pdf)
        confirmed = await get_db().bookings.find_one_and_update(
            {"_id": booking["_id"]},
            {"$set": {"lease.path": str(lease_path), "lease.generated_at": _now()}},
            return_document=ReturnDocument.AFTER,
        )
    except Exception:
        # The tenancy stands even if the PDF fails; the download endpoint reports it as not ready.
        logger.exception("Lease PDF generation failed for booking %s", booking["_id"])

    # 5. Every other open request that can no longer be met is cancelled and refunded: all of them once nothing is
    #    left to rent, otherwise those for this room wanting more seats than it still has free.
    cancelled = 0
    beaten: dict | None = None
    if taken["rental_status"] == RentalStatus.RENTED.value:
        beaten = {}
    elif (unit := booking.get("unit")) is not None:
        room_free = (find_room(taken, unit["room_id"]) or {}).get("available_seats", 0)
        beaten = {"unit.room_id": unit["room_id"], "unit.seats": {"$gt": room_free}}
    if beaten is not None:
        losing = {"listing_id": booking["listing_id"], "is_open": True, "_id": {"$ne": booking["_id"]}, **beaten}
        competitors = await get_db().bookings.find(losing).to_list(None)
        result = await get_db().bookings.update_many(
            losing,
            {
                "$set": {
                    "status": BookingStatus.CANCELLED.value,
                    "is_open": False,
                    "qr": None,
                    "escrow_status": EscrowStatus.REFUNDED.value,
                    "updated_at": now,
                },
                "$push": {
                    "escrow_ledger": _ledger(EscrowStatus.REFUNDED, "Another tenant confirmed the seat or room asked for; deposit to be refunded.")
                },
            },
        )
        cancelled = result.modified_count
        for competitor in competitors:
            qr = competitor.get("qr") or {}
            if qr.get("nonce") and not qr.get("used_at"):
                await log_qr_event(competitor, "REVOKED", qr["nonce"], "Another tenant confirmed the seat or room asked for")
            await chat_cards.sync_qr_cards({**competitor, "status": BookingStatus.CANCELLED.value, "qr": None})

    await chat_cards.handshake_confirmed(confirmed, user)

    return ScanResult(
        booking=booking_to_out(confirmed),
        listing=ListingAvailability(
            rental_status=taken["rental_status"],
            available_seats=taken["seats"]["available_seats"] if taken.get("seats") else None,
        ),
        cancelled_requests=cancelled,
    )


# ================================================================ Feature 14: lease PDF + verification


@router.get("/bookings/{booking_id}/lease.pdf")
async def download_lease(booking_id: str, user: dict = Depends(get_current_user)):
    booking = await _load_booking(booking_id, user)
    lease = booking.get("lease")
    if not lease or not lease.get("path"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The lease PDF isn't available for this booking")
    return private_file_response(
        {"path": lease["path"], "content_type": "application/pdf", "original_filename": f"{lease['number']}.pdf"}
    )


@router.get("/leases/{booking_id}/verify", response_model=LeaseVerification)
async def verify_lease(booking_id: str, sig: Annotated[str, Query(min_length=8, max_length=64)]):
    booking = await get_db().bookings.find_one({"_id": parse_object_id(booking_id)})
    lease = (booking or {}).get("lease")
    if not lease or not hmac.compare_digest(sig, lease["signature"]):
        return LeaseVerification(valid=False)
    return LeaseVerification(
        valid=True,
        lease_number=lease["number"],
        property_title=booking["listing"]["title"],
        area=booking["listing"]["area"],
        owner_name=booking["owner"]["full_name"],
        tenant_name=booking["tenant"]["full_name"],
        agreed_rent=booking["agreed_rent"],
        deposit_amount=booking["deposit"]["amount"],
        move_in_date=booking["move_in_date"],
        confirmed_at=booking["confirmed_at"],
    )
