from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.database import serialize_doc
from app.schemas.rental import ROOM_ID_PATTERN, ListingCategory, RentalStatus
from app.schemas.user import KycStatus
from app.core.sanitizers import RequestModel, SafeText


class DepositMethod(StrEnum):
    BKASH = "BKASH"
    NAGAD = "NAGAD"
    ROCKET = "ROCKET"
    BANK_TRANSFER = "BANK_TRANSFER"
    CASH = "CASH"


DEPOSIT_METHOD_LABELS = {
    DepositMethod.BKASH: "bKash",
    DepositMethod.NAGAD: "Nagad",
    DepositMethod.ROCKET: "Rocket",
    DepositMethod.BANK_TRANSFER: "bank transfer",
    DepositMethod.CASH: "cash",
}


class BookingStatus(StrEnum):
    PENDING_OWNER = "PENDING_OWNER"  # tenant asked; owner hasn't answered
    APPROVED = "APPROVED"  # owner approved and issued a handshake QR
    CONFIRMED = "CONFIRMED"  # tenant scanned the QR; lease generated
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ENDED = "ENDED"  # tenant moved out after giving notice


# Confirmed and ended leases both count as a real, QR-verified tenancy (reviews need one of these).
LEASE_STATUSES = ("CONFIRMED", "ENDED")


OPEN_BOOKING_STATUSES = (BookingStatus.PENDING_OWNER, BookingStatus.APPROVED)


class EscrowStatus(StrEnum):
    PENDING_OWNER = "PENDING_OWNER"  # deposit logged, waiting for the owner
    HELD = "HELD"  # owner approved; held until the handshake
    RELEASED = "RELEASED"  # handshake done; released to the owner
    REFUNDED = "REFUNDED"  # request rejected or cancelled
    SPLIT = "SPLIT"  # divided between tenant and owner by an arbitration ruling


class UnitChoice(RequestModel):
    """For a bachelor tenant's sublet: which room (none needed for a single-seat sublet), and for a shared room, one
    seat in it or (while all its seats are free) the whole room."""

    room_id: str | None = Field(default=None, pattern=ROOM_ID_PATTERN)
    whole_room: bool = False


class BookingCreate(UnitChoice):
    listing_id: str
    move_in_date: date
    deposit_amount: int = Field(gt=0, le=10_000_000, description="Advance paid, in BDT")
    payment_method: DepositMethod
    payment_reference: SafeText = Field(min_length=3, max_length=60, description="bKash/Nagad TrxID or bank reference")
    message: SafeText | None = Field(default=None, max_length=500)


class Deposit(BaseModel):
    amount: int
    method: DepositMethod
    reference: str


class EscrowEntry(BaseModel):
    at: datetime
    status: EscrowStatus
    note: str


class BookingParty(BaseModel):
    id: str
    full_name: str
    phone: str
    kyc_status: KycStatus


class BookingListing(BaseModel):
    title: str
    category: ListingCategory
    area: str


class BookingUnit(BaseModel):
    """What a sublet booking covers: `seats` of the room (all of them when `whole_room`, as for a single room)."""

    room_id: str
    room_name: str
    seats: int
    whole_room: bool


class BookingOut(BaseModel):
    id: str
    listing_id: str
    listing: BookingListing
    unit: BookingUnit | None = None
    owner: BookingParty
    tenant: BookingParty
    status: BookingStatus
    agreed_rent: int
    move_in_date: date
    message: str | None = None
    deposit: Deposit
    escrow_status: EscrowStatus
    escrow_ledger: list[EscrowEntry]
    qr_expires_at: datetime | None = None
    confirmed_at: datetime | None = None
    lease_number: str | None = None
    lease_verify_url: str | None = None
    created_at: datetime
    updated_at: datetime


class QrIssued(BaseModel):
    token: str
    expires_at: datetime
    booking: BookingOut


class ScanRequest(RequestModel):
    token: str = Field(min_length=20, max_length=4000)


class ListingAvailability(BaseModel):
    rental_status: RentalStatus
    available_seats: int | None = None


class ScanResult(BaseModel):
    booking: BookingOut
    listing: ListingAvailability
    cancelled_requests: int


class LeaseVerification(BaseModel):
    valid: bool
    lease_number: str | None = None
    property_title: str | None = None
    area: str | None = None
    owner_name: str | None = None
    tenant_name: str | None = None
    agreed_rent: int | None = None
    deposit_amount: int | None = None
    move_in_date: date | None = None
    confirmed_at: datetime | None = None


def unit_label(unit: dict | None) -> str | None:
    """"1 seat in Room 2", "Single room: Room 1" or "Whole room: Room 2 (2 seats)"."""
    if unit is None:
        return None
    if not unit["whole_room"]:
        return f"1 seat in {unit['room_name']}"
    if unit["seats"] == 1:
        return f"Single room: {unit['room_name']}"
    return f"Whole room: {unit['room_name']} ({unit['seats']} seats)"


def booking_to_out(doc: dict) -> BookingOut:
    data = serialize_doc(doc)
    qr = data.get("qr") or {}
    lease = data.get("lease") or {}
    # A QR expiry is only meaningful while the code can still be scanned.
    data["qr_expires_at"] = qr.get("expires_at") if data["status"] == BookingStatus.APPROVED else None
    data["lease_number"] = lease.get("number")
    if lease.get("signature"):
        data["lease_verify_url"] = f"{settings.app_base_url}/verify-lease/{data['id']}?sig={lease['signature']}"
    return BookingOut.model_validate(data)
