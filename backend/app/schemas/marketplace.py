from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

from app.core.database import serialize_doc
from app.services.bd_admin import with_admin_area
from app.schemas.rental import Building, ListerSummary, ListingLocation, ListingPhoto, ListingVideo, PlacedLocation, SearchCenter
from app.core.sanitizers import RequestModel, SafeText

# Bangladesh has no daylight saving time, so a fixed offset is exact (and avoids needing tzdata on Windows).
DHAKA_TZ = timezone(timedelta(hours=6), "Asia/Dhaka")


# ---------------------------------------------------------------- Feature 6: sale listings


class PropertyType(StrEnum):
    APARTMENT = "APARTMENT"
    HOUSE = "HOUSE"


class HandoverStatus(StrEnum):
    READY_FLAT = "READY_FLAT"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"


class SaleStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNDER_OFFER = "UNDER_OFFER"


class SaleTerms(RequestModel):
    asking_price: int = Field(gt=0, le=10_000_000_000, description="BDT")
    price_negotiable: bool = True
    parking_slots: int = Field(default=0, ge=0, le=20)
    handover_status: HandoverStatus
    expected_handover: date | None = None
    blueprint_url: AnyHttpUrl | None = None

    @field_validator("blueprint_url")
    @classmethod
    def blueprint_over_https(cls, url: AnyHttpUrl | None) -> AnyHttpUrl | None:
        # The app's Content-Security-Policy only loads images over https (plain http only for local development).
        if url is not None and url.scheme != "https" and url.host not in ("localhost", "127.0.0.1"):
            raise ValueError("Floor plan links must start with https://")
        return url

    @model_validator(mode="after")
    def handover_date_matches_status(self) -> "SaleTerms":
        if self.handover_status == HandoverStatus.UNDER_CONSTRUCTION and self.expected_handover is None:
            raise ValueError("Under-construction listings need an expected_handover date")
        if self.handover_status == HandoverStatus.READY_FLAT:
            self.expected_handover = None
        return self


class SaleListingIn(RequestModel):
    property_type: PropertyType
    title: SafeText = Field(min_length=5, max_length=120)
    description: SafeText = Field(default="", max_length=2000)
    location: ListingLocation
    building: Building
    sale: SaleTerms

    @model_validator(mode="after")
    def size_is_required(self) -> "SaleListingIn":
        if self.building.size_sqft is None:
            raise ValueError("Sale listings need building.size_sqft")
        return self


# ---------------------------------------------------------------- Feature 7: title vault


class TitleDocType(StrEnum):
    MUTATION_RECORD = "MUTATION_RECORD"
    DEED_SUMMARY = "DEED_SUMMARY"
    TAX_RECEIPT = "TAX_RECEIPT"


class TitleStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TitleDocumentOut(BaseModel):
    doc_type: TitleDocType
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class TitleVaultOut(BaseModel):
    listing_id: str
    title_status: TitleStatus
    title_review_note: str | None = None
    documents: list[TitleDocumentOut]
    missing: list[TitleDocType]


class TitleReviewRequest(RequestModel):
    status: Literal[TitleStatus.VERIFIED, TitleStatus.REJECTED]
    note: SafeText | None = Field(default=None, max_length=500)


class SaleListingOut(BaseModel):
    id: str
    lister_id: str
    lister: ListerSummary | None = None
    listing_mode: Literal["SALE"] = "SALE"
    property_type: PropertyType
    title: str
    description: str
    location: PlacedLocation
    photos: list[ListingPhoto] = []
    video: ListingVideo | None = None
    building: Building
    sale: SaleTerms
    price_per_sqft: int
    sale_status: SaleStatus
    # The public "Verified Title" badge is shown only when this is VERIFIED.
    title_status: TitleStatus
    title_documents_on_file: list[TitleDocType]
    distance_km: float | None = None
    created_at: datetime
    updated_at: datetime


class SaleSort(StrEnum):
    DISTANCE = "distance"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    PPSF_ASC = "ppsf_asc"
    NEWEST = "newest"


class SaleSearchParams(RequestModel):
    property_type: list[PropertyType] = []
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    min_size: int | None = Field(default=None, ge=0)
    min_bedrooms: int | None = Field(default=None, ge=0)
    handover_status: HandoverStatus | None = None
    min_parking: int | None = Field(default=None, ge=0)
    verified_title: bool = Field(default=False, description="Only listings with an admin-verified title")
    # Narrow to a division, district and/or upazila/thana (names as in /api/locations).
    division: SafeText | None = Field(default=None, max_length=60)
    district: SafeText | None = Field(default=None, max_length=60)
    upazila: SafeText | None = Field(default=None, max_length=60)
    # The buyer's target area. Given alone it filters by area name; with a point it must match both.
    area_name: SafeText | None = Field(default=None, min_length=2, max_length=60, description="Whole-word, case-insensitive")
    landmark: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9-]+$")
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=2, gt=0, le=50)
    sort: SaleSort | None = None
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def valid_ranges(self) -> "SaleSearchParams":
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be given together")
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price cannot exceed max_price")
        if self.sort == SaleSort.DISTANCE and self.landmark is None and self.lat is None:
            raise ValueError("Sorting by distance needs a landmark or lat/lng")
        return self


class SaleSearchResult(BaseModel):
    items: list[SaleListingOut]
    total: int
    area_name: str | None = None
    center: SearchCenter | None = None
    radius_km: float | None = None


def sale_listing_fields(payload: SaleListingIn) -> dict:
    fields = {**payload.model_dump(mode="json"), "listing_mode": "SALE"}
    fields["location"] = with_admin_area(fields["location"])
    fields["price_per_sqft"] = round(payload.sale.asking_price / payload.building.size_sqft)
    return fields


def sale_listing_to_out(doc: dict) -> SaleListingOut:
    data = serialize_doc(doc)
    data["title_documents_on_file"] = [d["doc_type"] for d in doc.get("title_documents", [])]
    if "distance_m" in data:
        data["distance_km"] = round(data.pop("distance_m") / 1000, 2)
    return SaleListingOut.model_validate(data)


# ---------------------------------------------------------------- Feature 8: price analysis


class Comparable(BaseModel):
    id: str
    title: str
    area: str
    price_per_sqft: int
    distance_km: float


class NeighborhoodStats(BaseModel):
    radius_km: float
    count: int
    average_ppsf: int
    median_ppsf: int
    min_ppsf: int
    max_ppsf: int


class PriceAnalysis(BaseModel):
    listing_id: str
    asking_price: int
    size_sqft: int
    price_per_sqft: int
    neighborhood: NeighborhoodStats | None
    difference_pct: float | None
    verdict: Literal["BELOW_MARKET", "AT_MARKET", "ABOVE_MARKET", "NOT_ENOUGH_DATA"]
    comparables: list[Comparable]


# ---------------------------------------------------------------- Feature 9: offers


class OfferType(StrEnum):
    PURCHASE = "PURCHASE"
    TOKEN_MONEY = "TOKEN_MONEY"  # bayna: an advance that secures the deal before the sale deed


class OfferStatus(StrEnum):
    AWAITING_SELLER = "AWAITING_SELLER"
    AWAITING_BUYER = "AWAITING_BUYER"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


OPEN_OFFER_STATUSES = (OfferStatus.AWAITING_SELLER, OfferStatus.AWAITING_BUYER)


class OfferEventType(StrEnum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


def check_token_amount(offer_type: OfferType, amount: int | None, token_amount: int | None) -> None:
    if offer_type == OfferType.PURCHASE and token_amount is not None:
        raise ValueError("Purchase offers do not carry token money")
    if offer_type == OfferType.TOKEN_MONEY:
        if token_amount is None:
            raise ValueError("Token-money offers need token_amount (the bayna)")
        if amount is not None and token_amount >= amount:
            raise ValueError("token_amount must be less than the offered price")


class OfferCreate(RequestModel):
    listing_id: str
    offer_type: OfferType
    amount: int = Field(gt=0, le=10_000_000_000, description="Proposed purchase price in BDT")
    token_amount: int | None = Field(default=None, gt=0, description="Bayna paid on signing, for TOKEN_MONEY")
    note: SafeText | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def token_matches_type(self) -> "OfferCreate":
        check_token_amount(self.offer_type, self.amount, self.token_amount)
        return self


class OfferResponse(RequestModel):
    action: Literal["ACCEPT", "REJECT", "COUNTER", "WITHDRAW"]
    amount: int | None = Field(default=None, gt=0, le=10_000_000_000)
    token_amount: int | None = Field(default=None, gt=0)
    note: SafeText | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def counter_needs_amount(self) -> "OfferResponse":
        if self.action == "COUNTER" and self.amount is None:
            raise ValueError("A counter-offer needs an amount")
        if self.action != "COUNTER" and (self.amount is not None or self.token_amount is not None):
            raise ValueError("Only counter-offers carry amounts")
        return self


class OfferEvent(BaseModel):
    at: datetime
    actor: Literal["BUYER", "SELLER", "SYSTEM"]
    event: OfferEventType
    amount: int | None = None
    token_amount: int | None = None
    note: str | None = None


class OfferParty(BaseModel):
    id: str
    full_name: str


class OfferOut(BaseModel):
    id: str
    listing_id: str
    listing_title: str
    asking_price: int
    buyer: OfferParty
    seller: OfferParty
    offer_type: OfferType
    status: OfferStatus
    amount: int
    token_amount: int | None = None
    history: list[OfferEvent]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- Feature 10: visit slots

SLOT_MINUTES = 30
VISIT_DAY_START_HOUR = 9  # first slot 09:00 Dhaka time
VISIT_DAY_END_HOUR = 20  # last slot starts 19:30
VISIT_BOOKING_WINDOW_DAYS = 30


class VisitMode(StrEnum):
    IN_PERSON = "IN_PERSON"
    VIDEO = "VIDEO"


class VisitStatus(StrEnum):
    BOOKED = "BOOKED"  # holds the slot (the unique slot indexes only count BOOKED visits)
    CANCELLED = "CANCELLED"


class VisitApproval(StrEnum):
    """The host's answer to a booked visit, given from the chat card. A declined visit is also CANCELLED."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    RESCHEDULE_PROPOSED = "RESCHEDULE_PROPOSED"  # the host moved it; waiting for the visitor to accept
    DECLINED = "DECLINED"


def _on_slot_grid(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("starts_at needs a timezone offset, e.g. 2026-11-02T10:30:00+06:00")
    local = value.astimezone(DHAKA_TZ)
    if local.minute % SLOT_MINUTES or local.second or local.microsecond:
        raise ValueError(f"Visits start on {SLOT_MINUTES}-minute boundaries")
    if not VISIT_DAY_START_HOUR <= local.hour < VISIT_DAY_END_HOUR:
        raise ValueError(f"Visits run {VISIT_DAY_START_HOUR}:00–{VISIT_DAY_END_HOUR}:00 Dhaka time")
    return value.astimezone(timezone.utc)


class VisitCreate(RequestModel):
    listing_id: str
    starts_at: datetime = Field(description="Slot start with a timezone offset, on a :00 or :30 boundary")
    mode: VisitMode
    note: SafeText | None = Field(default=None, max_length=300)

    @field_validator("starts_at")
    @classmethod
    def on_slot_grid(cls, value: datetime) -> datetime:
        return _on_slot_grid(value)


class VisitStatusUpdate(RequestModel):
    """APPROVED, RESCHEDULE_PROPOSED (with a new `starts_at`) and DECLINED come from the host. The visitor sends
    APPROVED only to accept a time the host proposed."""

    status: Literal[VisitApproval.APPROVED, VisitApproval.RESCHEDULE_PROPOSED, VisitApproval.DECLINED]
    starts_at: datetime | None = None

    @field_validator("starts_at")
    @classmethod
    def on_slot_grid(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _on_slot_grid(value)

    @model_validator(mode="after")
    def new_time_for_reschedule(self) -> "VisitStatusUpdate":
        if (self.status == VisitApproval.RESCHEDULE_PROPOSED) != (self.starts_at is not None):
            raise ValueError("starts_at is required to propose a new time, and only then")
        return self


class VisitParty(BaseModel):
    id: str
    full_name: str
    phone: str


class VisitOut(BaseModel):
    id: str
    listing_id: str
    listing_title: str
    listing_mode: Literal["RENT", "SALE"]
    host: VisitParty
    visitor: VisitParty
    starts_at: datetime
    ends_at: datetime
    mode: VisitMode
    status: VisitStatus
    approval: VisitApproval = VisitApproval.PENDING
    original_starts_at: datetime | None = None
    note: str | None = None
    cancelled_by: Literal["HOST", "VISITOR", "ADMIN"] | None = None
    created_at: datetime


class SlotOut(BaseModel):
    starts_at: datetime
    ends_at: datetime
    available: bool
    reason: Literal["PAST", "TAKEN", "YOURS"] | None = None


class DaySlots(BaseModel):
    listing_id: str
    date: date
    timezone: str = "Asia/Dhaka"
    slots: list[SlotOut]
