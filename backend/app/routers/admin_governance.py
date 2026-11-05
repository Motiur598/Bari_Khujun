"""Feature 20: fraud detection and dispute arbitration.

Two routers live here:
- `router` (/api/admin/governance): admin-only radar, QR audit trail, deed vault, arbitration rulings and bans.
- `disputes_router` (/api/disputes): where tenants and buyers raise disputes and the other side responds.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import get_db, parse_object_id, serialize_doc
from app.core.sanitizers import clean_text
from app.core.security import get_current_user, require_roles
from app.utils.file_security import PHOTO_TYPES, private_file_response, store_upload
from app.schemas.booking import LEASE_STATUSES, OPEN_BOOKING_STATUSES, BookingStatus, EscrowStatus
from app.schemas.governance import (
    AlertResolve,
    AuditEntry,
    BanRequest,
    BanResult,
    DisputeOut,
    DisputeStatus,
    DisputeType,
    EligibleSubject,
    Fault,
    KycDecision,
    Overview,
    QrHandshakeRow,
    QrRevoke,
    RadarRun,
    RulingIn,
    RulingOutcome,
)
from app.schemas.marketplace import DHAKA_TZ, OPEN_OFFER_STATUSES, OfferStatus, OfferType, SaleListingOut, TitleStatus, sale_listing_to_out
from app.schemas.user import KycStatus, Role, UserOut, user_to_out
from app.services import kyc_verification
from app.services.governance import log_action, log_qr_event, sweep
from app.services.listings import LISTER_LOOKUP
from app.services.trust import FAULT_PENALTY_POINTS, penalize

router = APIRouter(prefix="/api/admin/governance", tags=["admin governance"])
disputes_router = APIRouter(prefix="/api/disputes", tags=["disputes"])

AdminUser = Annotated[dict, Depends(require_roles(Role.ADMIN))]
MAX_EVIDENCE_PHOTOS = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit_out(doc: dict) -> AuditEntry:
    return AuditEntry.model_validate(serialize_doc(doc))


# ================================================================ overview


@router.get("/overview", response_model=Overview)
async def overview(_admin: AdminUser):
    db = get_db()
    return Overview(
        open_alerts=await db.security_audit_logs.count_documents({"kind": "ALERT", "status": "OPEN"}),
        open_disputes=await db.disputes.count_documents({"is_open": True}),
        pending_titles=await db.listings.count_documents({"listing_mode": "SALE", "title_status": TitleStatus.PENDING.value}),
        active_qr_codes=await db.bookings.count_documents(
            {"status": BookingStatus.APPROVED.value, "qr.used_at": None, "qr.expires_at": {"$gt": _now()}}
        ),
        banned_users=await db.users.count_documents({"is_banned": True}),
    )


# ================================================================ 1. scammer radar


@router.get("/alerts", response_model=list[AuditEntry])
async def list_audit_log(
    _admin: AdminUser,
    kind: Annotated[str | None, Query(pattern="^(ALERT|ACTION)$")] = None,
    entry_status: Annotated[str | None, Query(alias="status", pattern="^(OPEN|RESOLVED)$")] = None,
):
    query: dict = {}
    if kind:
        query["kind"] = kind
    if entry_status:
        query["status"] = entry_status
    docs = await get_db().security_audit_logs.find(query).sort("created_at", -1).to_list(200)
    return [_audit_out(doc) for doc in docs]


@router.post("/alerts/{alert_id}/resolve", response_model=AuditEntry)
async def resolve_alert(alert_id: str, payload: AlertResolve, admin: AdminUser):
    updated = await get_db().security_audit_logs.find_one_and_update(
        {"_id": parse_object_id(alert_id), "kind": "ALERT", "status": "OPEN"},
        {
            "$set": {
                "status": "RESOLVED",
                "resolution_note": payload.note,
                "actor": {"id": admin["_id"], "full_name": admin["full_name"]},
                "updated_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open alert with that id")
    return _audit_out(updated)


@router.post("/radar/run", response_model=RadarRun)
async def run_radar(_admin: AdminUser):
    """Re-check recent QR activity now (the radar also runs on a timer and after every QR issue)."""
    return RadarRun(new_alerts=await sweep())


# ================================================================ 1b. automated ID checks


@router.get("/kyc-verifications/{record_id}/images/{side}")
async def kyc_card_image(record_id: str, side: Literal["front", "back"], _admin: AdminUser):
    """A photo of either side of a card the automated check kept, so cards flagged as alike can be compared."""
    record = await get_db().kyc_verifications.find_one({"_id": parse_object_id(record_id)}, {"files": 1})
    if record is None or side not in record.get("files", {}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return private_file_response(record["files"][side])


# Each decision: the statuses it applies to, the status it sets, how the card then counts in duplicate checks, and
# the trust points it takes (or, for a restore, gives back).
_KYC_DECISIONS = {
    "approve": ((KycStatus.PENDING,), KycStatus.VERIFIED, kyc_verification.Outcome.VERIFIED, 0, "KYC_APPROVED", "Approved {name}'s ID"),
    "revoke": ((KycStatus.PENDING, KycStatus.VERIFIED), KycStatus.REVOKED, kyc_verification.Outcome.REVOKED,
               kyc_verification.REVOKE_PENALTY_POINTS, "KYC_REVOKED", "Revoked {name}'s ID verification"),
    "restore": ((KycStatus.REVOKED,), KycStatus.VERIFIED, kyc_verification.Outcome.VERIFIED,
                -kyc_verification.REVOKE_PENALTY_POINTS, "KYC_RESTORED", "Restored {name}'s ID verification"),
}


@router.post("/users/{user_id}/kyc/{decision}", response_model=UserOut)
async def decide_kyc(user_id: str, decision: Literal["approve", "revoke", "restore"], payload: KycDecision, admin: AdminUser):
    """Settle an ID the automated check flagged: approve a card held for review, revoke one that belongs to someone
    else (30 trust points off), or restore an account revoked by mistake (the points come back), for example after
    the real owner appealed with a video of themselves holding the card."""
    db = get_db()
    allowed, new_status, outcome, points, action, message = _KYC_DECISIONS[decision]
    target = parse_object_id(user_id)
    updated = await db.users.find_one_and_update(
        {"_id": target, "role": {"$ne": Role.ADMIN.value}, "kyc_status": {"$in": [s.value for s in allowed]}},
        {"$set": {"kyc_status": new_status.value, "kyc_review_note": payload.note, "updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This account's ID can't be {'restored' if decision == 'restore' else decision + 'd'} now")
    if points:
        await penalize(target, points)
    await kyc_verification.set_latest_outcome(target, outcome)
    await db.security_audit_logs.update_many(
        {"kind": "ALERT", "status": "OPEN", "subject_user_id": target, "rule": {"$in": list(kyc_verification.KYC_RULES)}},
        {"$set": {"status": "RESOLVED", "resolution_note": payload.note, "updated_at": _now(),
                  "actor": {"id": admin["_id"], "full_name": admin["full_name"]}}},
    )
    await log_action(admin, action, f"{message.format(name=updated['full_name'])}: {payload.note}", target)
    return user_to_out(await db.users.find_one({"_id": target}))


# ================================================================ 2a. QR audit trail


def _code_state(booking: dict) -> str:
    qr = booking.get("qr") or {}
    if booking["status"] in LEASE_STATUSES:
        return "USED"
    if booking["status"] != BookingStatus.APPROVED or not qr.get("nonce"):
        return "NONE"
    if qr.get("used_at"):
        return "USED"
    return "ACTIVE" if qr["expires_at"] > _now() else "EXPIRED"


@router.get("/qr-handshakes", response_model=list[QrHandshakeRow])
async def qr_audit_trail(
    _admin: AdminUser,
    state: Annotated[str | None, Query(pattern="^(ACTIVE|EXPIRED|USED|NONE)$")] = None,
    owner_id: str | None = None,
):
    match: dict = {}
    if owner_id:
        match["owner_id"] = parse_object_id(owner_id)
    groups = await get_db().qr_handshake_logs.aggregate([
        {"$match": match},
        {"$sort": {"at": -1}},
        {
            "$group": {
                "_id": "$booking_id",
                "events": {"$push": {"event": "$event", "nonce_fp": "$nonce_fp", "detail": "$detail", "at": "$at"}},
                "codes_issued": {"$sum": {"$cond": [{"$eq": ["$event", "ISSUED"]}, 1, 0]}},
                "last_event_at": {"$max": "$at"},
            }
        },
        {"$sort": {"last_event_at": -1}},
        {"$limit": 300},
    ]).to_list(None)
    bookings = {
        b["_id"]: b async for b in get_db().bookings.find({"_id": {"$in": [g["_id"] for g in groups]}})
    }
    rows = []
    for group in groups:
        booking = bookings.get(group["_id"])
        if booking is None:
            continue
        code_state = _code_state(booking)
        if state and code_state != state:
            continue
        rows.append(QrHandshakeRow(
            booking_id=str(booking["_id"]),
            listing_id=str(booking["listing_id"]),
            listing_title=booking["listing"]["title"],
            owner={"id": str(booking["owner_id"]), "full_name": booking["owner"]["full_name"]},
            tenant={"id": str(booking["tenant_id"]), "full_name": booking["tenant"]["full_name"]},
            booking_status=booking["status"],
            code_state=code_state,
            codes_issued=group["codes_issued"],
            last_event_at=group["last_event_at"],
            expires_at=(booking.get("qr") or {}).get("expires_at") if code_state in ("ACTIVE", "EXPIRED") else None,
            confirmed_at=booking.get("confirmed_at"),
            lease_number=(booking.get("lease") or {}).get("number"),
            events=group["events"],
        ))
    return rows


@router.post("/qr-handshakes/{booking_id}/revoke", response_model=QrHandshakeRow | None)
async def revoke_qr(booking_id: str, payload: QrRevoke, admin: AdminUser):
    """Kill an unused code. The request goes back to waiting for the owner, who can issue a fresh code."""
    booking = await get_db().bookings.find_one({"_id": parse_object_id(booking_id)})
    if booking is None or _code_state(booking) not in ("ACTIVE", "EXPIRED"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This booking has no unused QR code to revoke")
    note = f"Bari Khujun revoked the handshake code: {payload.reason}"
    updated = await get_db().bookings.find_one_and_update(
        {"_id": booking["_id"], "status": BookingStatus.APPROVED.value, "qr.nonce": booking["qr"]["nonce"], "qr.used_at": None},
        {
            "$set": {"status": BookingStatus.PENDING_OWNER.value, "qr": None, "escrow_status": EscrowStatus.PENDING_OWNER.value, "updated_at": _now()},
            "$push": {"escrow_ledger": {"at": _now(), "status": EscrowStatus.PENDING_OWNER.value, "note": note}},
        },
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The code was used or replaced in the meantime")
    await log_qr_event(booking, "REVOKED", booking["qr"]["nonce"], f"Revoked by admin: {payload.reason}")
    await log_action(admin, "QR_REVOKED", note, booking["owner_id"], booking_id=booking_id)
    rows = await qr_audit_trail(admin, owner_id=str(booking["owner_id"]))
    return next((row for row in rows if row.booking_id == booking_id), None)


# ================================================================ 2b. deed vault (Feature 7 documents)


@router.get("/deed-vault", response_model=list[SaleListingOut])
async def deed_vault(
    _admin: AdminUser,
    title_status: Annotated[str, Query(alias="status", pattern="^(PENDING|VERIFIED|REJECTED|NOT_SUBMITTED|ALL)$")] = "PENDING",
):
    # Admins see suspended listings too, so this skips the usual SALE_ONLY filter.
    query: dict = {"listing_mode": "SALE"}
    if title_status != "ALL":
        query["title_status"] = title_status
    pipeline = [{"$match": query}, {"$sort": {"updated_at": -1}}, {"$limit": 200}, *LISTER_LOOKUP]
    return [sale_listing_to_out(doc) for doc in await get_db().listings.aggregate(pipeline).to_list(None)]


# ================================================================ 4. cascading scammer ban


@router.post("/users/{user_id}/ban-scammer", response_model=BanResult)
async def ban_scammer(user_id: str, payload: BanRequest, admin: AdminUser):
    db = get_db()
    target = await db.users.find_one({"_id": parse_object_id(user_id)})
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target["role"] == Role.ADMIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admin accounts can't be banned here")
    now = _now()
    banned = await db.users.update_one(
        {"_id": target["_id"], "is_banned": {"$ne": True}},
        # token_version also moves on, so every token the user holds is revoked, not just refused at the next check.
        {
            "$set": {"is_banned": True, "banned_at": now, "ban_reason": payload.reason, "banned_by": admin["_id"]},
            "$inc": {"token_version": 1},
        },
    )
    if banned.modified_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "This user is already banned")

    # 1. Every listing goes dark.
    listings = await db.listings.update_many(
        {"lister_id": target["_id"], "suspended": {"$ne": True}},
        {"$set": {"suspended": True, "suspended_at": now, "suspended_reason": payload.reason}},
    )

    # 2. Open requests on either side are cancelled and refunded; any live QR code dies with them.
    note = "A party's account was suspended by Bari Khujun; deposit to be refunded."
    revoked = 0
    open_bookings = await db.bookings.find(
        {"is_open": True, "$or": [{"owner_id": target["_id"]}, {"tenant_id": target["_id"]}]}
    ).to_list(None)
    for booking in open_bookings:
        qr = booking.get("qr") or {}
        await db.bookings.update_one(
            {"_id": booking["_id"], "status": {"$in": [s.value for s in OPEN_BOOKING_STATUSES]}},
            {
                "$set": {"status": BookingStatus.CANCELLED.value, "is_open": False, "qr": None, "escrow_status": EscrowStatus.REFUNDED.value, "updated_at": now},
                "$push": {"escrow_ledger": {"at": now, "status": EscrowStatus.REFUNDED.value, "note": note}},
            },
        )
        if qr.get("nonce") and not qr.get("used_at"):
            revoked += 1
            await log_qr_event(booking, "REVOKED", qr["nonce"], "Owner or tenant banned")

    # 3. Open offers close, and upcoming visits are called off.
    offers = await db.offers.update_many(
        {"is_open": True, "$or": [{"buyer_id": target["_id"]}, {"seller_id": target["_id"]}]},
        {
            "$set": {"status": OfferStatus.CLOSED.value, "is_open": False, "updated_at": now},
            "$push": {"history": {"at": now, "actor": "SYSTEM", "event": "CLOSED", "note": "A party's account was suspended"}},
        },
    )
    visits = await db.visit_slots.update_many(
        {"status": "BOOKED", "starts_at": {"$gt": now}, "$or": [{"host_id": target["_id"]}, {"visitor_id": target["_id"]}]},
        {"$set": {"status": "CANCELLED", "cancelled_by": "ADMIN", "cancelled_at": now}},
    )
    await db.security_audit_logs.update_many(
        {"kind": "ALERT", "status": "OPEN", "subject_user_id": target["_id"]},
        {"$set": {"status": "RESOLVED", "resolution_note": f"User banned: {payload.reason}", "updated_at": now,
                  "actor": {"id": admin["_id"], "full_name": admin["full_name"]}}},
    )
    result = BanResult(
        user_id=user_id,
        full_name=target["full_name"],
        listings_suspended=listings.modified_count,
        bookings_cancelled=len(open_bookings),
        qr_codes_revoked=revoked,
        offers_closed=offers.modified_count,
        visits_cancelled=visits.modified_count,
    )
    await log_action(admin, "USER_BANNED", f"Banned {target['full_name']}: {payload.reason}", target["_id"], **result.model_dump())
    return result


# ================================================================ 3. arbitration court


async def _dispute_out(doc: dict) -> DisputeOut:
    data = serialize_doc(doc)
    if doc.get("booking_id"):
        booking = await get_db().bookings.find_one({"_id": doc["booking_id"]}, {"move_in_photos": 1})
        data["baseline_photos"] = serialize_doc((booking or {}).get("move_in_photos", []))
    return DisputeOut.model_validate(data)


async def _load_dispute(dispute_id: str, user: dict) -> dict:
    dispute = await get_db().disputes.find_one({"_id": parse_object_id(dispute_id)})
    if dispute is None or (user["role"] != Role.ADMIN and user["_id"] not in (dispute["claimant_id"], dispute["respondent_id"])):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispute not found")
    return dispute


def _photo_response(photos: list[dict], photo_id: str):
    photo = next((p for p in photos if p["id"] == photo_id), None)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return private_file_response(photo)


async def _store_evidence(files: list[UploadFile], dispute_id: ObjectId) -> list[dict]:
    if len(files) > MAX_EVIDENCE_PHOTOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Attach at most {MAX_EVIDENCE_PHOTOS} photos")
    stored = []
    try:
        for upload in files:
            stored.append(await store_upload(upload, settings.upload_dir / "disputes" / str(dispute_id), PHOTO_TYPES))
    except HTTPException:
        for item in stored:
            Path(item["storage_path"]).unlink(missing_ok=True)
        raise
    now = _now()
    return [{**item, "id": item.pop("file_id"), "uploaded_at": now} for item in stored]


async def _eligible_subjects(user: dict) -> list[EligibleSubject]:
    db = get_db()
    subjects = []
    async for booking in db.bookings.find({"tenant_id": user["_id"]}).sort("updated_at", -1):
        types = [DisputeType.FAKE_TO_LET]
        if booking["status"] in LEASE_STATUSES:
            types.insert(0, DisputeType.DEPOSIT_DEDUCTION)
        subjects.append(EligibleSubject(
            kind="BOOKING",
            id=str(booking["_id"]),
            label=f"{booking['listing']['title']} ({booking['status'].replace('_', ' ').lower()})",
            counterpart=booking["owner"]["full_name"],
            escrow_amount=booking["deposit"]["amount"],
            types=types,
        ))
    async for offer in db.offers.find({"buyer_id": user["_id"], "offer_type": OfferType.TOKEN_MONEY.value, "status": OfferStatus.ACCEPTED.value}):
        subjects.append(EligibleSubject(
            kind="OFFER",
            id=str(offer["_id"]),
            label=f"{offer['listing_title']} (accepted bayna offer)",
            counterpart=offer["seller"]["full_name"],
            escrow_amount=offer["token_amount"],
            types=[DisputeType.BAYNA_BREACH],
        ))
    return subjects


@disputes_router.get("/eligible", response_model=list[EligibleSubject])
async def eligible_subjects(user: dict = Depends(require_roles(Role.BACHELOR_TENANT, Role.FAMILY_TENANT, Role.BUYER))):
    return await _eligible_subjects(user)


@disputes_router.post("", response_model=DisputeOut, status_code=status.HTTP_201_CREATED)
async def raise_dispute(
    dispute_type: Annotated[DisputeType, Form(alias="type")],
    claimed_amount: Annotated[int, Form(gt=0)],
    description: Annotated[str, Form(min_length=10, max_length=2000)],
    booking_id: Annotated[str | None, Form()] = None,
    offer_id: Annotated[str | None, Form()] = None,
    photos: Annotated[list[UploadFile], File()] = [],
    user: dict = Depends(require_roles(Role.BACHELOR_TENANT, Role.FAMILY_TENANT, Role.BUYER)),
):
    db = get_db()
    description = clean_text(description)
    if len(description) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Describe what happened in at least a sentence")
    if dispute_type == DisputeType.BAYNA_BREACH:
        offer = await db.offers.find_one({"_id": parse_object_id(offer_id or "")}) if offer_id else None
        if offer is None or offer["buyer_id"] != user["_id"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pick an offer of yours for a bayna dispute")
        if offer["offer_type"] != OfferType.TOKEN_MONEY or offer["status"] != OfferStatus.ACCEPTED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Bayna disputes are for accepted token-money offers")
        subject_key, escrow = f"offer:{offer['_id']}", offer["token_amount"]
        listing_id, listing_title = offer["listing_id"], offer["listing_title"]
        claimant_side, respondent_side = "BUYER", "SELLER"
        respondent = {"id": offer["seller_id"], "full_name": offer["seller"]["full_name"]}
        links = {"offer_id": offer["_id"], "booking_id": None}
    else:
        booking = await db.bookings.find_one({"_id": parse_object_id(booking_id or "")}) if booking_id else None
        if booking is None or booking["tenant_id"] != user["_id"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pick a booking of yours for this dispute")
        if dispute_type == DisputeType.DEPOSIT_DEDUCTION and booking["status"] not in LEASE_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "Deposit disputes need a QR-confirmed lease")
        subject_key, escrow = f"booking:{booking['_id']}", booking["deposit"]["amount"]
        listing_id, listing_title = booking["listing_id"], booking["listing"]["title"]
        claimant_side, respondent_side = "TENANT", "OWNER"
        respondent = {"id": booking["owner_id"], "full_name": booking["owner"]["full_name"]}
        links = {"booking_id": booking["_id"], "offer_id": None}
    if claimed_amount > escrow:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"You can claim at most the BDT {escrow:,} held for this deal")

    dispute_id = ObjectId()
    now = _now()
    dispute = {
        "_id": dispute_id,
        "case_number": f"BK-D-{now.astimezone(DHAKA_TZ):%Y%m%d}-{str(dispute_id)[-6:].upper()}",
        "type": dispute_type.value,
        "status": DisputeStatus.OPEN.value,
        "is_open": True,
        "subject_key": subject_key,
        **links,
        "listing_id": listing_id,
        "listing_title": listing_title,
        "claimant_id": user["_id"],
        "respondent_id": respondent["id"],
        "claimant": {"id": user["_id"], "full_name": user["full_name"], "side": claimant_side},
        "respondent": {**respondent, "side": respondent_side},
        "escrow_amount": escrow,
        "claimed_amount": claimed_amount,
        "description": description,
        "claimant_photos": [],
        "response": None,
        "ruling": None,
        "timeline": [{"at": now, "actor": "CLAIMANT", "event": "RAISED", "note": None}],
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.disputes.insert_one(dispute)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "There's already an open dispute about this deal")
    if photos:
        stored = await _store_evidence(photos, dispute_id)
        await db.disputes.update_one({"_id": dispute_id, "claimant_id": user["_id"]}, {"$set": {"claimant_photos": stored}})
        dispute["claimant_photos"] = stored
    return await _dispute_out(dispute)


@disputes_router.get("/mine", response_model=list[DisputeOut])
async def my_disputes(user: dict = Depends(get_current_user)):
    docs = await get_db().disputes.find(
        {"$or": [{"claimant_id": user["_id"]}, {"respondent_id": user["_id"]}]}
    ).sort("updated_at", -1).to_list(100)
    return [await _dispute_out(doc) for doc in docs]


@disputes_router.get("/{dispute_id}", response_model=DisputeOut)
async def get_dispute(dispute_id: str, user: dict = Depends(get_current_user)):
    return await _dispute_out(await _load_dispute(dispute_id, user))


@disputes_router.post("/{dispute_id}/response", response_model=DisputeOut)
async def respond_to_dispute(
    dispute_id: str,
    statement: Annotated[str, Form(min_length=10, max_length=2000)],
    claimed_deduction: Annotated[int | None, Form(ge=0)] = None,
    photos: Annotated[list[UploadFile], File()] = [],
    user: dict = Depends(get_current_user),
):
    dispute = await _load_dispute(dispute_id, user)
    if dispute["respondent_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the other party can respond to this dispute")
    if dispute["status"] != DisputeStatus.OPEN or dispute.get("response"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This dispute isn't waiting for your response")
    if claimed_deduction is not None and claimed_deduction > dispute["escrow_amount"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"You can claim at most BDT {dispute['escrow_amount']:,}")
    statement = clean_text(statement)
    if len(statement) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Explain your side in at least a sentence")
    stored = await _store_evidence(photos, dispute["_id"])
    now = _now()
    updated = await get_db().disputes.find_one_and_update(
        {"_id": dispute["_id"], "respondent_id": user["_id"], "status": DisputeStatus.OPEN.value, "response": None},
        {
            "$set": {
                "status": DisputeStatus.UNDER_REVIEW.value,
                "response": {"statement": statement, "claimed_deduction": claimed_deduction, "photos": stored, "responded_at": now},
                "updated_at": now,
            },
            "$push": {"timeline": {"at": now, "actor": "RESPONDENT", "event": "RESPONDED", "note": None}},
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The dispute changed in the meantime. Reload it.")
    return await _dispute_out(updated)


@disputes_router.get("/{dispute_id}/photos/{photo_id}")
async def dispute_photo(dispute_id: str, photo_id: str, user: dict = Depends(get_current_user)):
    dispute = await _load_dispute(dispute_id, user)
    return _photo_response(dispute.get("claimant_photos", []) + ((dispute.get("response") or {}).get("photos") or []), photo_id)


@disputes_router.get("/{dispute_id}/baseline/{photo_id}")
async def dispute_baseline_photo(dispute_id: str, photo_id: str, user: dict = Depends(get_current_user)):
    """The tenant's move-in photos, visible to the arbitrator as well as both parties."""
    dispute = await _load_dispute(dispute_id, user)
    booking = await get_db().bookings.find_one({"_id": dispute.get("booking_id")}, {"move_in_photos": 1}) if dispute.get("booking_id") else None
    return _photo_response((booking or {}).get("move_in_photos", []), photo_id)


@router.get("/disputes", response_model=list[DisputeOut])
async def list_disputes(
    _admin: AdminUser,
    dispute_status: Annotated[DisputeStatus | None, Query(alias="status")] = None,
):
    query = {"status": dispute_status.value} if dispute_status else {}
    docs = await get_db().disputes.find(query).sort([("is_open", -1), ("created_at", 1)]).to_list(200)
    return [await _dispute_out(doc) for doc in docs]


@router.post("/disputes/{dispute_id}/rule", response_model=DisputeOut)
async def rule_on_dispute(dispute_id: str, payload: RulingIn, admin: AdminUser):
    db = get_db()
    dispute = await _load_dispute(dispute_id, admin)
    if dispute["status"] == DisputeStatus.RESOLVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This dispute has already been ruled on")
    escrow = dispute["escrow_amount"]
    if payload.outcome == RulingOutcome.REFUND_TENANT:
        to_claimant, to_respondent = escrow, 0
    elif payload.outcome == RulingOutcome.PAY_OWNER:
        to_claimant, to_respondent = 0, escrow
    else:
        to_claimant, to_respondent = payload.claimant_amount, payload.respondent_amount
        if to_claimant + to_respondent != escrow:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A split has to add up to the BDT {escrow:,} in escrow")

    now = _now()
    penalized = None
    if payload.fault != Fault.NONE:
        party = dispute["claimant"] if payload.fault == Fault.CLAIMANT else dispute["respondent"]
        penalized = {"id": party["id"], "full_name": party["full_name"]}
    ruling = {
        "outcome": payload.outcome.value,
        "claimant_amount": to_claimant,
        "respondent_amount": to_respondent,
        "fault": payload.fault.value,
        "penalized": penalized,
        "penalty_points": FAULT_PENALTY_POINTS if penalized else 0,
        "note": payload.note,
        "ruled_by": {"id": admin["_id"], "full_name": admin["full_name"]},
        "ruled_at": now,
    }
    updated = await db.disputes.find_one_and_update(
        {"_id": dispute["_id"], "status": {"$ne": DisputeStatus.RESOLVED.value}},
        {
            "$set": {"status": DisputeStatus.RESOLVED.value, "is_open": False, "ruling": ruling, "updated_at": now},
            "$push": {"timeline": {"at": now, "actor": "ADMIN", "event": "RULED", "note": payload.note}},
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This dispute has already been ruled on")

    # Execute the escrow split on the underlying deal.
    claimant_side = dispute["claimant"]["side"].lower()
    respondent_side = dispute["respondent"]["side"].lower()
    split_note = (
        f"Arbitration {dispute['case_number']}: BDT {to_claimant:,} to the {claimant_side}, "
        f"BDT {to_respondent:,} to the {respondent_side}."
    )
    if dispute.get("booking_id"):
        escrow_status = (
            EscrowStatus.REFUNDED if to_respondent == 0 else EscrowStatus.RELEASED if to_claimant == 0 else EscrowStatus.SPLIT
        ).value
        changes: dict = {"escrow_status": escrow_status, "updated_at": now}
        booking = await db.bookings.find_one({"_id": dispute["booking_id"]})
        if booking and booking["status"] in OPEN_BOOKING_STATUSES:
            # A ruling settles the deposit, so an unfinished request can't go on to a handshake.
            changes.update(status=BookingStatus.CANCELLED.value, is_open=False, qr=None)
            qr = booking.get("qr") or {}
            if qr.get("nonce") and not qr.get("used_at"):
                await log_qr_event(booking, "REVOKED", qr["nonce"], f"Closed by arbitration {dispute['case_number']}")
        await db.bookings.update_one(
            {"_id": dispute["booking_id"]},
            {"$set": changes, "$push": {"escrow_ledger": {"at": now, "status": escrow_status, "note": split_note}}},
        )
    else:
        await db.offers.update_one(
            {"_id": dispute["offer_id"]},
            {"$set": {"settlement": {"case_number": dispute["case_number"], "buyer_amount": to_claimant, "seller_amount": to_respondent, "settled_at": now}}},
        )

    if penalized:
        await penalize(penalized["id"])
    await log_action(
        admin, "DISPUTE_RULED", f"{dispute['case_number']}: {split_note}", penalized["id"] if penalized else None,
        dispute_id=str(dispute["_id"]), outcome=payload.outcome.value, fault=payload.fault.value,
    )
    return await _dispute_out(updated)
