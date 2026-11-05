import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import find_for_party, get_db, parse_object_id, serialize_doc
from app.core.sanitizers import clean_text
from app.core.security import get_current_user, require_roles
from app.utils.file_security import PHOTO_TYPES, private_file_response, store_upload
from app.schemas.booking import LEASE_STATUSES, BookingStatus, booking_to_out
from app.schemas.marketplace import DHAKA_TZ
from app.schemas.operations import (
    MAX_CONDITION_PHOTOS,
    MAX_PHOTOS_PER_UPLOAD,
    MAX_TICKET_PHOTOS,
    NEXT_TICKET_STATUS,
    PHOTO_WINDOW_HOURS,
    InvoiceBatch,
    InvoiceConfirm,
    InvoiceGenerate,
    InvoiceOut,
    InvoicePay,
    InvoiceStatus,
    LeaseOut,
    LeaseReviews,
    MoveOutNoticeIn,
    PaymentRejection,
    ReviewIn,
    ReviewOut,
    ReviewSaved,
    SkippedLease,
    TicketCategory,
    TicketComment,
    TicketOut,
    TicketPriority,
    TicketStatus,
    TicketStatusChange,
    TrustSummary,
    UserReviews,
    add_months,
)
from app.schemas.rental import ListingCategory, find_room
from app.schemas.user import Role
from app.services.listings import RENT_ONLY
from app.services.move_outs import process_due_move_outs
from app.services.receipt_pdf import build_receipt_pdf
from app.services.trust import recalculate_trust

router = APIRouter(prefix="/api/operations", tags=["operations"])

TENANT_ROLES = (Role.BACHELOR_TENANT, Role.FAMILY_TENANT)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _now().astimezone(DHAKA_TZ).date()


def _side(booking: dict, user: dict) -> str:
    return "TENANT" if booking["tenant_id"] == user["_id"] else "OWNER"


def _party(snapshot: dict) -> dict:
    return {"id": snapshot["id"], "full_name": snapshot["full_name"]}


async def _load_lease(booking_id: str | ObjectId, user: dict, statuses=LEASE_STATUSES) -> dict:
    """A QR-confirmed booking the user is a party to. Someone else's lease is a 403."""
    oid = booking_id if isinstance(booking_id, ObjectId) else parse_object_id(booking_id)
    return await find_for_party(get_db().bookings, {"_id": oid, "status": {"$in": list(statuses)}}, user["_id"], "lease")


def _require_tenant(booking: dict, user: dict, action: str) -> None:
    if booking["tenant_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Only the tenant can {action}")


def _require_owner(booking: dict, user: dict, action: str) -> None:
    if booking["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Only the owner can {action}")


def _require_active(booking: dict, action: str) -> None:
    if booking["status"] != BookingStatus.CONFIRMED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This lease has ended, so you can no longer {action}")


async def _store_photos(files: list[UploadFile], folder: Path) -> list[dict]:
    """Store several images; if any one is rejected, remove the ones already written."""
    stored: list[dict] = []
    try:
        for upload in files:
            stored.append(await store_upload(upload, folder, PHOTO_TYPES))
    except HTTPException:
        for item in stored:
            Path(item["storage_path"]).unlink(missing_ok=True)
        raise
    now = _now()
    return [{**item, "id": item.pop("file_id"), "uploaded_at": now} for item in stored]


def _photo_file(photos: list[dict], photo_id: str):
    photo = next((p for p in photos if p["id"] == photo_id), None)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return private_file_response(photo)


# ================================================================ Leases (shared by the lease dashboard)


def _unit_service_charge(listing: dict, unit: dict) -> int:
    """A sublet tenant's service charge: their seat's or room's, per seat they hold."""
    return (find_room(listing, unit["room_id"]) or {}).get("service_charge", 0) * unit["seats"]


def _photo_deadline(booking: dict) -> datetime:
    # The 48 hours start at move-in day or at the handshake, whichever is later.
    move_in_start = datetime.combine(date.fromisoformat(booking["move_in_date"]), time(0), DHAKA_TZ)
    return max(booking["confirmed_at"], move_in_start) + timedelta(hours=PHOTO_WINDOW_HOURS)


async def _lease_out(booking: dict, user: dict) -> LeaseOut:
    listing = await get_db().listings.find_one({"_id": booking["listing_id"]}, {"category": 1, "seats": 1, "pricing": 1, "sublet": 1}) or {}
    unit = booking.get("unit")
    # Bills are split per seat on an owner's seat listing; a sublet's are entered per seat by the lister.
    seats = (listing.get("seats") or {}) if listing.get("category") == ListingCategory.BACHELOR_SEAT and unit is None else {}
    side = _side(booking, user)
    deadline = _photo_deadline(booking)
    active = booking["status"] == BookingStatus.CONFIRMED
    today = _today()
    data = {
        **booking_to_out(booking).model_dump(),
        "viewer_side": side,
        "total_seats": seats.get("total_seats"),
        "seats_held": unit["seats"] if unit else None,
        "service_charge_share": (
            _unit_service_charge(listing, unit) if unit
            else (seats.get("split") or {}).get("per_seat_service_charge", (listing.get("pricing") or {}).get("service_charge", 0))
        ),
        "move_in_photos": serialize_doc(booking.get("move_in_photos", [])),
        "photo_deadline": deadline,
        "can_upload_photos": side == "TENANT" and active and _now() <= deadline,
        "move_out": booking.get("move_out"),
        "notice_window": (
            {"earliest": add_months(today, 1), "latest": add_months(today, 2)}
            if side == "TENANT" and active and not booking.get("move_out") else None
        ),
        "ended_at": booking.get("ended_at"),
    }
    return LeaseOut.model_validate(data)


@router.get("/leases", response_model=list[LeaseOut])
async def my_leases(
    side: Annotated[str | None, Query(pattern="^(tenant|owner)$")] = None,
    user: dict = Depends(get_current_user),
):
    parties = {"tenant": [{"tenant_id": user["_id"]}], "owner": [{"owner_id": user["_id"]}]}
    query = {
        "status": {"$in": list(LEASE_STATUSES)},
        "$or": parties.get(side, parties["tenant"] + parties["owner"]),
    }
    docs = await get_db().bookings.find(query).sort([("status", 1), ("confirmed_at", -1)]).to_list(200)
    return [await _lease_out(doc, user) for doc in docs]


@router.get("/leases/{booking_id}", response_model=LeaseOut)
async def get_lease(booking_id: str, user: dict = Depends(get_current_user)):
    return await _lease_out(await _load_lease(booking_id, user), user)


# ================================================================ Feature 17: move-in photos and move-out notice


@router.post("/leases/{booking_id}/photos", response_model=LeaseOut)
async def upload_condition_photos(
    booking_id: str,
    room: Annotated[str, Form(min_length=2, max_length=40)],
    files: Annotated[list[UploadFile], File()],
    caption: Annotated[str | None, Form(max_length=200)] = None,
    user: dict = Depends(get_current_user),
):
    booking = await _load_lease(booking_id, user)
    _require_tenant(booking, user, "add move-in photos")
    _require_active(booking, "add move-in photos")
    deadline = _photo_deadline(booking)
    if _now() > deadline:
        closed = deadline.astimezone(DHAKA_TZ).strftime("%d %b %Y, %I:%M %p")
        raise HTTPException(status.HTTP_409_CONFLICT, f"The 48-hour photo window closed on {closed} (Dhaka)")
    if not 1 <= len(files) <= MAX_PHOTOS_PER_UPLOAD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Upload 1 to {MAX_PHOTOS_PER_UPLOAD} photos at a time")
    if len(booking.get("move_in_photos", [])) + len(files) > MAX_CONDITION_PHOTOS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A move-in log holds at most {MAX_CONDITION_PHOTOS} photos")

    room = clean_text(room)
    if len(room) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name the room the photos show")
    photos = await _store_photos(files, settings.upload_dir / "condition" / str(booking["_id"]))
    for photo in photos:
        photo.update(room=room, caption=clean_text(caption) or None)
    # Photos are append-only: the log is evidence, so nothing can be edited or removed afterwards.
    updated = await get_db().bookings.find_one_and_update(
        {"_id": booking["_id"], "tenant_id": user["_id"], "status": BookingStatus.CONFIRMED.value},
        {"$push": {"move_in_photos": {"$each": photos}}, "$set": {"updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    return await _lease_out(updated, user)


@router.get("/leases/{booking_id}/photos/{photo_id}")
async def condition_photo(booking_id: str, photo_id: str, user: dict = Depends(get_current_user)):
    booking = await _load_lease(booking_id, user)
    return _photo_file(booking.get("move_in_photos", []), photo_id)


@router.post("/leases/{booking_id}/move-out-notice", response_model=LeaseOut)
async def give_move_out_notice(booking_id: str, payload: MoveOutNoticeIn, user: dict = Depends(get_current_user)):
    booking = await _load_lease(booking_id, user)
    _require_tenant(booking, user, "give move-out notice")
    _require_active(booking, "give notice")
    if booking.get("move_out"):
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already given notice on this lease")
    today = _today()
    earliest, latest = add_months(today, 1), add_months(today, 2)
    if not earliest <= payload.move_out_date <= latest:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Give 1 to 2 months' notice: pick a move-out date from {earliest:%d %b %Y} to {latest:%d %b %Y}",
        )
    if payload.move_out_date <= date.fromisoformat(booking["move_in_date"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Move-out has to be after the move-in date")

    now = _now()
    move_out = {"notice_given_at": now, "move_out_date": payload.move_out_date.isoformat(), "reason": payload.reason}
    updated = await get_db().bookings.find_one_and_update(
        {"_id": booking["_id"], "tenant_id": user["_id"], "status": BookingStatus.CONFIRMED.value, "move_out": {"$in": [None]}},
        {"$set": {"move_out": move_out, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already given notice on this lease")
    # Shown on the listing as "reopens on"; the move-out job frees the seat or flat on that date.
    await get_db().listings.update_one(
        {"_id": booking["listing_id"]},
        {"$push": {"upcoming_vacancies": {"booking_id": booking["_id"], "available_from": move_out["move_out_date"]}}},
    )
    return await _lease_out(updated, user)


@router.post("/admin/process-move-outs")
async def run_move_outs(
    as_of: Annotated[date | None, Query(description="Treat this date as today (defaults to today in Dhaka)")] = None,
    _admin: dict = Depends(require_roles(Role.ADMIN)),
):
    """Run the move-out job now. It also runs on a timer inside the server."""
    return {"ended": await process_due_move_outs(as_of)}


# ================================================================ Feature 16: invoices


def _invoice_out(doc: dict) -> InvoiceOut:
    data = serialize_doc(doc)
    # A submitted payment is the tenant's part done; only an invoice nobody has paid can be overdue.
    data["overdue"] = doc["status"] == InvoiceStatus.UNPAID and _today() > date.fromisoformat(doc["due_date"])
    return InvoiceOut.model_validate(data)


async def _load_invoice(invoice_id: str, user: dict) -> dict:
    return await find_for_party(get_db().invoices, {"_id": parse_object_id(invoice_id)}, user["_id"], "invoice")


def _invoice_event(actor: str, event: str, note: str | None = None) -> dict:
    return {"at": _now(), "actor": actor, "event": event, "note": note}


async def _transition_invoice(invoice: dict, expected: list[InvoiceStatus], update: dict, actor_filter: dict) -> InvoiceOut:
    """Atomic state change: the expected status and the acting party are both part of the filter."""
    updated = await get_db().invoices.find_one_and_update(
        {"_id": invoice["_id"], **actor_filter, "status": {"$in": [s.value for s in expected]}},
        update,
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The invoice changed in the meantime. Reload it.")
    return _invoice_out(updated)


@router.post("/invoices/generate", response_model=InvoiceBatch, status_code=status.HTTP_201_CREATED)
async def generate_invoices(payload: InvoiceGenerate, user: dict = Depends(get_current_user)):
    """Bill every active tenant of a listing for one month. Shared flats split each bill per seat."""
    listing = await get_db().listings.find_one({"_id": parse_object_id(payload.listing_id), **RENT_ONLY})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    if listing["lister_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the lister can bill tenants")
    year, month = map(int, payload.period.split("-"))
    period_start = date(year, month, 1)
    # Tenants who already moved out still owe the month they left in.
    leases = await get_db().bookings.find(
        {
            "listing_id": listing["_id"],
            "$or": [
                {"status": BookingStatus.CONFIRMED.value},
                {"status": BookingStatus.ENDED.value, "move_out.move_out_date": {"$gte": period_start.isoformat()}},
            ],
        }
    ).to_list(None)
    if not leases:
        raise HTTPException(status.HTTP_409_CONFLICT, "There are no tenants to bill on this listing for that month")

    # Rent is due by the 10th; a month billed late gets a week from today instead of arriving overdue.
    due_date = payload.due_date or max(date(year, month, 10), _today() + timedelta(days=7))
    sublet = listing.get("sublet") is not None
    seats = listing["seats"]["total_seats"] if listing["category"] == ListingCategory.BACHELOR_SEAT and not sublet else None

    def share(amount: int) -> int:
        # Round each seat's share up, like the listing's seat split, so the seats cover the whole bill.
        return math.ceil(amount / seats) if seats else amount

    service_flat = listing["pricing"]["service_charge"]
    created, skipped = [], []
    for lease in leases:
        tenant = lease["tenant"]
        move_in = date.fromisoformat(lease["move_in_date"])
        move_out = (lease.get("move_out") or {}).get("move_out_date")
        if (move_in.year, move_in.month) > (year, month):
            skipped.append(SkippedLease(booking_id=str(lease["_id"]), tenant_name=tenant["full_name"], reason="Moves in after this month"))
            continue
        if move_out and period_start > date.fromisoformat(move_out):
            skipped.append(SkippedLease(booking_id=str(lease["_id"]), tenant_name=tenant["full_name"], reason="Moved out before this month"))
            continue
        if (unit := lease.get("unit")) is not None:
            # A sublet's tenant: their seat's or room's service charge, and each bill as entered (one seat's share)
            # for every seat they hold.
            held = unit["seats"]
            per = f" ({held} seats)" if held > 1 else ""
            lines = [
                {"key": "rent", "label": "Rent", "flat_amount": None, "amount": lease["agreed_rent"]},
                {"key": "service_charge", "label": f"Service charge{per}", "flat_amount": None, "amount": _unit_service_charge(listing, unit)},
                {"key": "electricity", "label": f"Electricity{per}", "flat_amount": None, "amount": payload.electricity * held},
                {"key": "gas", "label": f"Gas{per}", "flat_amount": None, "amount": payload.gas * held},
                {"key": "water", "label": f"Water{per}", "flat_amount": None, "amount": payload.water * held},
            ]
        else:
            lines = [
                {"key": "rent", "label": "Rent", "flat_amount": None, "amount": lease["agreed_rent"]},
                {"key": "service_charge", "label": "Service charge", "flat_amount": service_flat if seats else None, "amount": share(service_flat)},
                {"key": "electricity", "label": "Electricity", "flat_amount": payload.electricity if seats else None, "amount": share(payload.electricity)},
                {"key": "gas", "label": "Gas", "flat_amount": payload.gas if seats else None, "amount": share(payload.gas)},
                {"key": "water", "label": "Water", "flat_amount": payload.water if seats else None, "amount": share(payload.water)},
            ]
        now = _now()
        invoice_id = ObjectId()
        invoice = {
            "_id": invoice_id,
            "number": f"BK-INV-{year}{month:02d}-{str(invoice_id)[-6:].upper()}",
            "booking_id": lease["_id"],
            "listing_id": listing["_id"],
            "listing_title": listing["title"],
            "owner_id": lease["owner_id"],
            "tenant_id": lease["tenant_id"],
            "owner": _party(lease["owner"]),
            "tenant": _party(tenant),
            "period": payload.period,
            "lines": lines,
            "total": sum(line["amount"] for line in lines),
            "split_seats": seats,
            "billed_per_seat": sublet,
            "due_date": due_date.isoformat(),
            "status": InvoiceStatus.UNPAID.value,
            "payment": None,
            "receipt_number": None,
            "paid_at": None,
            "note": payload.note,
            "history": [_invoice_event("OWNER", "ISSUED", payload.note)],
            "created_at": now,
            "updated_at": now,
        }
        try:
            await get_db().invoices.insert_one(invoice)
        except DuplicateKeyError:
            skipped.append(SkippedLease(booking_id=str(lease["_id"]), tenant_name=tenant["full_name"], reason="Already invoiced for this month"))
            continue
        created.append(_invoice_out(invoice))
    return InvoiceBatch(created=created, skipped=skipped)


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(booking_id: str | None = None, user: dict = Depends(get_current_user)):
    if booking_id is not None:
        booking = await _load_lease(booking_id, user)
        query: dict = {"booking_id": booking["_id"]}
    else:
        query = {"$or": [{"tenant_id": user["_id"]}, {"owner_id": user["_id"]}]}
    docs = await get_db().invoices.find(query).sort([("period", -1), ("created_at", -1)]).to_list(200)
    return [_invoice_out(doc) for doc in docs]


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceOut)
async def submit_payment(invoice_id: str, payload: InvoicePay, user: dict = Depends(get_current_user)):
    invoice = await _load_invoice(invoice_id, user)
    if invoice["tenant_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the tenant can submit a payment")
    if invoice["status"] != InvoiceStatus.UNPAID:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invoice isn't waiting for a payment")
    payment = {"method": payload.method.value, "reference": payload.reference.strip(), "recorded_by": "TENANT", "recorded_at": _now()}
    return await _transition_invoice(
        invoice,
        [InvoiceStatus.UNPAID],
        {
            "$set": {"status": InvoiceStatus.PAYMENT_SUBMITTED.value, "payment": payment, "updated_at": _now()},
            "$push": {"history": _invoice_event("TENANT", "PAYMENT_SUBMITTED", f"{payload.method.value} ref. {payment['reference']}")},
        },
        {"tenant_id": user["_id"]},
    )


@router.post("/invoices/{invoice_id}/confirm", response_model=InvoiceOut)
async def confirm_payment(invoice_id: str, payload: InvoiceConfirm | None = None, user: dict = Depends(get_current_user)):
    invoice = await _load_invoice(invoice_id, user)
    if invoice["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can confirm a payment")
    if invoice["status"] == InvoiceStatus.PAID:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invoice is already paid")
    now = _now()
    changes: dict = {
        "status": InvoiceStatus.PAID.value,
        "paid_at": now,
        "receipt_number": invoice["number"].replace("-INV-", "-RCT-"),
        "updated_at": now,
    }
    if invoice["status"] == InvoiceStatus.UNPAID:
        # The tenant paid outside the app (often cash); the owner records it.
        payload = payload or InvoiceConfirm()
        changes["payment"] = {
            "method": payload.method.value,
            "reference": (payload.reference or "").strip() or "Recorded by owner",
            "recorded_by": "OWNER",
            "recorded_at": now,
        }
    return await _transition_invoice(
        invoice,
        [InvoiceStatus(invoice["status"])],
        {"$set": changes, "$push": {"history": _invoice_event("OWNER", "PAID")}},
        {"owner_id": user["_id"]},
    )


@router.post("/invoices/{invoice_id}/reject-payment", response_model=InvoiceOut)
async def reject_payment(invoice_id: str, payload: PaymentRejection, user: dict = Depends(get_current_user)):
    invoice = await _load_invoice(invoice_id, user)
    if invoice["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can reject a payment")
    if invoice["status"] != InvoiceStatus.PAYMENT_SUBMITTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "There's no submitted payment to reject")
    return await _transition_invoice(
        invoice,
        [InvoiceStatus.PAYMENT_SUBMITTED],
        {
            "$set": {"status": InvoiceStatus.UNPAID.value, "payment": None, "updated_at": _now()},
            "$push": {"history": _invoice_event("OWNER", "PAYMENT_REJECTED", payload.note)},
        },
        {"owner_id": user["_id"]},
    )


@router.get("/invoices/{invoice_id}/receipt.pdf")
async def download_receipt(invoice_id: str, user: dict = Depends(get_current_user)):
    invoice = await _load_invoice(invoice_id, user)
    if invoice["status"] != InvoiceStatus.PAID:
        raise HTTPException(status.HTTP_409_CONFLICT, "A receipt is issued once the owner confirms the payment")
    pdf = await run_in_threadpool(build_receipt_pdf, invoice)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice["receipt_number"]}.pdf"'},
    )


# ================================================================ Feature 18: maintenance tickets


def _ticket_out(doc: dict) -> TicketOut:
    return TicketOut.model_validate(serialize_doc(doc))


def _ticket_parties(user: dict) -> dict:
    return {"$or": [{"owner_id": user["_id"]}, {"tenant_id": user["_id"]}]}


async def _load_ticket(ticket_id: str, user: dict) -> dict:
    return await find_for_party(get_db().maintenance_tickets, {"_id": parse_object_id(ticket_id)}, user["_id"], "repair ticket")


@router.post("/tickets", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
async def report_issue(
    booking_id: Annotated[str, Form()],
    category: Annotated[TicketCategory, Form()],
    title: Annotated[str, Form(min_length=3, max_length=120)],
    description: Annotated[str, Form(max_length=2000)] = "",
    priority: Annotated[TicketPriority, Form()] = TicketPriority.NORMAL,
    photos: Annotated[list[UploadFile], File()] = [],
    user: dict = Depends(require_roles(*TENANT_ROLES)),
):
    booking = await _load_lease(booking_id, user)
    _require_tenant(booking, user, "report a repair")
    _require_active(booking, "report repairs")
    title, description = clean_text(title), clean_text(description)
    if len(title) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the problem a short title")
    if len(photos) > MAX_TICKET_PHOTOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Attach at most {MAX_TICKET_PHOTOS} photos")

    ticket_id = ObjectId()
    stored = await _store_photos(photos, settings.upload_dir / "maintenance" / str(ticket_id)) if photos else []
    now = _now()
    ticket = {
        "_id": ticket_id,
        "booking_id": booking["_id"],
        "listing_id": booking["listing_id"],
        "listing_title": booking["listing"]["title"],
        "tenant_id": booking["tenant_id"],
        "owner_id": booking["owner_id"],
        "tenant": _party(booking["tenant"]),
        "owner": _party(booking["owner"]),
        "category": category.value,
        "priority": priority.value,
        "title": title,
        "description": description,
        "photos": stored,
        "status": TicketStatus.OPEN.value,
        "updates": [{"at": now, "actor": "TENANT", "status": TicketStatus.OPEN.value, "note": None}],
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
    }
    await get_db().maintenance_tickets.insert_one(ticket)
    return _ticket_out(ticket)


@router.get("/tickets", response_model=list[TicketOut])
async def list_tickets(
    booking_id: str | None = None,
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    user: dict = Depends(get_current_user),
):
    if booking_id is not None:
        booking = await _load_lease(booking_id, user)
        query: dict = {"booking_id": booking["_id"]}
    else:
        query = {"$or": [{"tenant_id": user["_id"]}, {"owner_id": user["_id"]}]}
    if ticket_status is not None:
        query["status"] = ticket_status.value
    docs = await get_db().maintenance_tickets.find(query).sort("created_at", -1).to_list(200)
    return [_ticket_out(doc) for doc in docs]


@router.post("/tickets/{ticket_id}/status", response_model=TicketOut)
async def advance_ticket(ticket_id: str, payload: TicketStatusChange, user: dict = Depends(get_current_user)):
    ticket = await _load_ticket(ticket_id, user)
    if ticket["owner_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can update a repair's status")
    current = TicketStatus(ticket["status"])
    if NEXT_TICKET_STATUS.get(current) != payload.status:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This ticket is already resolved" if current == TicketStatus.RESOLVED
            else f"A {current.value.replace('_', ' ').lower()} ticket can only move to {NEXT_TICKET_STATUS[current].value.replace('_', ' ').lower()}",
        )
    now = _now()
    changes = {"status": payload.status.value, "updated_at": now}
    if payload.status == TicketStatus.RESOLVED:
        changes["resolved_at"] = now
    updated = await get_db().maintenance_tickets.find_one_and_update(
        {"_id": ticket["_id"], "owner_id": user["_id"], "status": current.value},
        {"$set": changes, "$push": {"updates": {"at": now, "actor": "OWNER", "status": payload.status.value, "note": payload.note}}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The ticket changed in the meantime. Reload it.")
    return _ticket_out(updated)


@router.post("/tickets/{ticket_id}/comments", response_model=TicketOut)
async def comment_on_ticket(ticket_id: str, payload: TicketComment, user: dict = Depends(get_current_user)):
    ticket = await _load_ticket(ticket_id, user)
    actor = "TENANT" if ticket["tenant_id"] == user["_id"] else "OWNER"
    now = _now()
    updated = await get_db().maintenance_tickets.find_one_and_update(
        {"_id": ticket["_id"], **_ticket_parties(user)},
        {"$set": {"updated_at": now}, "$push": {"updates": {"at": now, "actor": actor, "status": None, "note": payload.note}}},
        return_document=ReturnDocument.AFTER,
    )
    return _ticket_out(updated)


@router.get("/tickets/{ticket_id}/photos/{photo_id}")
async def ticket_photo(ticket_id: str, photo_id: str, user: dict = Depends(get_current_user)):
    return _photo_file((await _load_ticket(ticket_id, user))["photos"], photo_id)


# ================================================================ Feature 19: reviews and trust score


def _review_out(doc: dict) -> ReviewOut:
    return ReviewOut.model_validate(serialize_doc(doc))


async def _trust_summary(user_id: ObjectId) -> TrustSummary:
    user = await get_db().users.find_one({"_id": user_id})
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return TrustSummary(
        user_id=str(user["_id"]),
        full_name=user["full_name"],
        role=user["role"],
        kyc_status=user["kyc_status"],
        trust_score=user.get("trust_score", 100),
        review_count=user.get("review_count", 0),
        rating_average=user.get("rating_average"),
    )


@router.put("/reviews", response_model=ReviewSaved)
async def save_review(payload: ReviewIn, user: dict = Depends(get_current_user)):
    """Create or update your review of the other party on a QR-confirmed lease."""
    booking = await get_db().bookings.find_one(
        {"_id": parse_object_id(payload.booking_id), "$or": [{"owner_id": user["_id"]}, {"tenant_id": user["_id"]}]}
    )
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lease not found")
    if booking["status"] not in LEASE_STATUSES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Reviews open once the tenancy is confirmed with the QR handshake"
        )
    side = _side(booking, user)
    reviewee = booking["owner"] if side == "TENANT" else booking["tenant"]
    me = booking["tenant"] if side == "TENANT" else booking["owner"]
    now = _now()
    await get_db().reviews.update_one(
        {"booking_id": booking["_id"], "reviewer_id": user["_id"]},
        {
            "$set": {"rating": payload.rating, "comment": payload.comment, "updated_at": now},
            "$setOnInsert": {
                "reviewee_id": reviewee["id"],
                "reviewer": _party(me),
                "reviewee": _party(reviewee),
                "reviewer_side": side,
                "listing_title": booking["listing"]["title"],
                "created_at": now,
            },
        },
        upsert=True,
    )
    await recalculate_trust(reviewee["id"])
    review = await get_db().reviews.find_one({"booking_id": booking["_id"], "reviewer_id": user["_id"]})
    return ReviewSaved(review=_review_out(review), reviewee=await _trust_summary(reviewee["id"]))


@router.get("/reviews/user/{user_id}", response_model=UserReviews)
async def reviews_of_user(user_id: str):
    oid = parse_object_id(user_id)
    summary = await _trust_summary(oid)
    docs = await get_db().reviews.find({"reviewee_id": oid}).sort("updated_at", -1).to_list(100)
    return UserReviews(summary=summary, reviews=[_review_out(doc) for doc in docs])


@router.get("/reviews/lease/{booking_id}", response_model=LeaseReviews)
async def reviews_for_lease(booking_id: str, user: dict = Depends(get_current_user)):
    booking = await _load_lease(booking_id, user)
    docs = await get_db().reviews.find({"booking_id": booking["_id"]}).to_list(2)
    mine = next((d for d in docs if d["reviewer_id"] == user["_id"]), None)
    theirs = next((d for d in docs if d["reviewer_id"] != user["_id"]), None)
    return LeaseReviews(
        can_review=True,
        mine=_review_out(mine) if mine else None,
        theirs=_review_out(theirs) if theirs else None,
    )
