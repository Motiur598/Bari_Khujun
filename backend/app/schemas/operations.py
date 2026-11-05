import calendar
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.booking import BookingOut, DepositMethod
from app.schemas.user import KycStatus, Role
from app.core.sanitizers import RequestModel, SafeText

Side = Literal["TENANT", "OWNER"]


class Party(BaseModel):
    id: str
    full_name: str


def add_months(day: date, months: int) -> date:
    """Same day-of-month `months` later, clamped to the month's end (31 Jan + 1 month = 28/29 Feb)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


# ---------------------------------------------------------------- Feature 17: move-in log and move-out notice

PHOTO_WINDOW_HOURS = 48
MAX_CONDITION_PHOTOS = 30
MAX_PHOTOS_PER_UPLOAD = 10


class StoredPhoto(BaseModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime


class ConditionPhoto(StoredPhoto):
    room: str
    caption: str | None = None


class MoveOutNoticeIn(RequestModel):
    move_out_date: date
    reason: SafeText | None = Field(default=None, max_length=300)


class MoveOut(BaseModel):
    notice_given_at: datetime
    move_out_date: date
    reason: str | None = None


class NoticeWindow(BaseModel):
    earliest: date
    latest: date


class LeaseOut(BookingOut):
    viewer_side: Side
    total_seats: int | None = None  # set for seat listings, where bills are split per seat
    # Set for a sublet's tenant: the seats they hold (all of a shared room's, for a whole room). Bills on a sublet are
    # entered as one seat's share and charged per seat held.
    seats_held: int | None = None
    service_charge_share: int
    move_in_photos: list[ConditionPhoto] = []
    photo_deadline: datetime
    can_upload_photos: bool
    move_out: MoveOut | None = None
    notice_window: NoticeWindow | None = None  # only while the tenant can still give notice
    ended_at: datetime | None = None


# ---------------------------------------------------------------- Feature 16: invoices


class InvoiceStatus(StrEnum):
    UNPAID = "UNPAID"
    PAYMENT_SUBMITTED = "PAYMENT_SUBMITTED"
    PAID = "PAID"


class InvoiceGenerate(RequestModel):
    listing_id: str
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Billing month, YYYY-MM")
    # Whole-flat meter bills; shared flats split them per seat. On a sublet, one seat's share, charged per seat held.
    electricity: int = Field(default=0, ge=0, le=1_000_000)
    gas: int = Field(default=0, ge=0, le=1_000_000)
    water: int = Field(default=0, ge=0, le=1_000_000)
    due_date: date | None = None
    note: SafeText | None = Field(default=None, max_length=300)


class InvoiceLine(BaseModel):
    key: Literal["rent", "service_charge", "electricity", "gas", "water"]
    label: str
    flat_amount: int | None = None  # the whole-flat figure, when this line was split per seat
    amount: int


class InvoicePayment(BaseModel):
    method: DepositMethod
    reference: str
    recorded_by: Side
    recorded_at: datetime


class InvoiceEvent(BaseModel):
    at: datetime
    actor: Side
    event: Literal["ISSUED", "PAYMENT_SUBMITTED", "PAYMENT_REJECTED", "PAID"]
    note: str | None = None


class InvoiceOut(BaseModel):
    id: str
    number: str
    booking_id: str
    listing_id: str
    listing_title: str
    owner: Party
    tenant: Party
    period: str
    lines: list[InvoiceLine]
    total: int
    split_seats: int | None = None
    due_date: date
    status: InvoiceStatus
    overdue: bool = False
    payment: InvoicePayment | None = None
    receipt_number: str | None = None
    paid_at: datetime | None = None
    note: str | None = None
    history: list[InvoiceEvent]
    created_at: datetime
    updated_at: datetime


class SkippedLease(BaseModel):
    booking_id: str
    tenant_name: str
    reason: str


class InvoiceBatch(BaseModel):
    created: list[InvoiceOut]
    skipped: list[SkippedLease]


class InvoicePay(RequestModel):
    method: DepositMethod
    reference: SafeText = Field(min_length=3, max_length=60)


class InvoiceConfirm(RequestModel):
    # Only used when the owner records a payment the tenant didn't submit (e.g. cash in hand).
    method: DepositMethod = DepositMethod.CASH
    reference: SafeText | None = Field(default=None, max_length=60)


class PaymentRejection(RequestModel):
    note: SafeText = Field(min_length=3, max_length=300)


# ---------------------------------------------------------------- Feature 18: maintenance tickets

MAX_TICKET_PHOTOS = 5


class TicketCategory(StrEnum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    GAS = "GAS"
    APPLIANCE = "APPLIANCE"
    OTHER = "OTHER"


class TicketPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


# Tickets only move forward, one step at a time.
NEXT_TICKET_STATUS = {TicketStatus.OPEN: TicketStatus.IN_PROGRESS, TicketStatus.IN_PROGRESS: TicketStatus.RESOLVED}


class TicketUpdate(BaseModel):
    at: datetime
    actor: Side
    status: TicketStatus | None = None
    note: str | None = None


class TicketOut(BaseModel):
    id: str
    booking_id: str
    listing_id: str
    listing_title: str
    tenant: Party
    owner: Party
    category: TicketCategory
    priority: TicketPriority
    title: str
    description: str
    photos: list[StoredPhoto]
    status: TicketStatus
    updates: list[TicketUpdate]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class TicketStatusChange(RequestModel):
    status: Literal[TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED]
    note: SafeText | None = Field(default=None, max_length=500)


class TicketComment(RequestModel):
    note: SafeText = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------- Feature 19: reviews and trust score

# Every user starts at 100. Reviews are blended with three imaginary five-star reviews, so one bad
# review moves the score noticeably without wiping it out: one 1-star review gives 80, two give 68.
TRUST_PRIOR_REVIEWS = 3


def trust_score_from(ratings: list[int]) -> int:
    return round(100 * (TRUST_PRIOR_REVIEWS * 5 + sum(ratings)) / (5 * (TRUST_PRIOR_REVIEWS + len(ratings))))


class ReviewIn(RequestModel):
    booking_id: str
    rating: int = Field(ge=1, le=5)
    comment: SafeText = Field(default="", max_length=1000)


class ReviewOut(BaseModel):
    id: str
    booking_id: str
    listing_title: str
    reviewer: Party
    reviewee: Party
    reviewer_side: Side
    rating: int
    comment: str
    created_at: datetime
    updated_at: datetime


class TrustSummary(BaseModel):
    user_id: str
    full_name: str
    role: Role
    kyc_status: KycStatus
    trust_score: int
    review_count: int = 0
    rating_average: float | None = None


class ReviewSaved(BaseModel):
    review: ReviewOut
    reviewee: TrustSummary


class UserReviews(BaseModel):
    summary: TrustSummary
    reviews: list[ReviewOut]


class LeaseReviews(BaseModel):
    can_review: bool
    mine: ReviewOut | None = None
    theirs: ReviewOut | None = None
