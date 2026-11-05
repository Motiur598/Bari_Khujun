from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.operations import ConditionPhoto, Party, StoredPhoto
from app.core.sanitizers import RequestModel, SafeText


# ---------------------------------------------------------------- scammer radar and audit log


class AuditSubject(BaseModel):
    id: str
    full_name: str
    role: str | None = None


class AuditEntry(BaseModel):
    id: str
    kind: Literal["ALERT", "ACTION"]
    severity: Literal["HIGH", "MEDIUM", "LOW", "INFO"]
    rule: str
    subject: AuditSubject | None = None
    message: str
    evidence: dict[str, Any] = {}
    hits: int = 1
    status: Literal["OPEN", "RESOLVED"]
    actor: Party | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime


class AlertResolve(RequestModel):
    note: SafeText = Field(min_length=3, max_length=500)


class RadarRun(BaseModel):
    new_alerts: int


# ---------------------------------------------------------------- QR audit trail


class QrEvent(BaseModel):
    event: Literal["ISSUED", "CONFIRMED", "SCAN_REJECTED", "REVOKED"]
    nonce_fp: str | None = None
    detail: str | None = None
    at: datetime


class QrHandshakeRow(BaseModel):
    booking_id: str
    listing_id: str
    listing_title: str
    owner: Party
    tenant: Party
    booking_status: str
    code_state: Literal["ACTIVE", "EXPIRED", "USED", "NONE"]
    codes_issued: int
    last_event_at: datetime
    expires_at: datetime | None = None
    confirmed_at: datetime | None = None
    lease_number: str | None = None
    events: list[QrEvent]


class QrRevoke(RequestModel):
    reason: SafeText = Field(min_length=3, max_length=300)


# ---------------------------------------------------------------- cascading ban


class BanRequest(RequestModel):
    reason: SafeText = Field(min_length=3, max_length=500)


class KycDecision(RequestModel):
    note: SafeText = Field(min_length=3, max_length=500, description="Why, for the audit trail")


class BanResult(BaseModel):
    user_id: str
    full_name: str
    listings_suspended: int
    bookings_cancelled: int
    qr_codes_revoked: int
    offers_closed: int
    visits_cancelled: int


class Overview(BaseModel):
    open_alerts: int
    open_disputes: int
    pending_titles: int
    active_qr_codes: int
    banned_users: int


# ---------------------------------------------------------------- arbitration court


class DisputeType(StrEnum):
    DEPOSIT_DEDUCTION = "DEPOSIT_DEDUCTION"  # owner kept some or all of a tenant's deposit
    FAKE_TO_LET = "FAKE_TO_LET"  # the listing wasn't real or wasn't the owner's to let
    BAYNA_BREACH = "BAYNA_BREACH"  # the seller broke a bayna (token money) agreement


class DisputeStatus(StrEnum):
    OPEN = "OPEN"  # waiting for the other side
    UNDER_REVIEW = "UNDER_REVIEW"  # both sides heard; with the arbitrator
    RESOLVED = "RESOLVED"


class RulingOutcome(StrEnum):
    REFUND_TENANT = "REFUND_TENANT"  # everything in escrow goes back to the claimant (tenant or buyer)
    PAY_OWNER = "PAY_OWNER"  # everything goes to the respondent (owner or seller)
    CUSTOM_SPLIT = "CUSTOM_SPLIT"


class Fault(StrEnum):
    CLAIMANT = "CLAIMANT"
    RESPONDENT = "RESPONDENT"
    NONE = "NONE"


Side = Literal["TENANT", "OWNER", "BUYER", "SELLER"]


class DisputeParty(Party):
    side: Side


class EvidencePhoto(StoredPhoto):
    pass


class DisputeResponseOut(BaseModel):
    statement: str
    claimed_deduction: int | None = None
    photos: list[EvidencePhoto] = []
    responded_at: datetime


class RulingOut(BaseModel):
    outcome: RulingOutcome
    claimant_amount: int
    respondent_amount: int
    fault: Fault
    penalized: Party | None = None
    penalty_points: int = 0
    note: str
    ruled_by: Party
    ruled_at: datetime


class TimelineEntry(BaseModel):
    at: datetime
    actor: Literal["CLAIMANT", "RESPONDENT", "ADMIN", "SYSTEM"]
    event: str
    note: str | None = None


class DisputeOut(BaseModel):
    id: str
    case_number: str
    type: DisputeType
    status: DisputeStatus
    booking_id: str | None = None
    offer_id: str | None = None
    listing_id: str
    listing_title: str
    claimant: DisputeParty
    respondent: DisputeParty
    escrow_amount: int
    claimed_amount: int
    description: str
    claimant_photos: list[EvidencePhoto] = []
    response: DisputeResponseOut | None = None
    ruling: RulingOut | None = None
    timeline: list[TimelineEntry]
    # The tenant's move-in log, so an arbitrator can compare it with the owner's claim photos.
    baseline_photos: list[ConditionPhoto] = []
    created_at: datetime
    updated_at: datetime


class EligibleSubject(BaseModel):
    kind: Literal["BOOKING", "OFFER"]
    id: str
    label: str
    counterpart: str
    escrow_amount: int
    types: list[DisputeType]


class RulingIn(RequestModel):
    outcome: RulingOutcome
    claimant_amount: int | None = Field(default=None, ge=0)
    respondent_amount: int | None = Field(default=None, ge=0)
    fault: Fault
    note: SafeText = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def custom_split_needs_amounts(self) -> "RulingIn":
        if self.outcome == RulingOutcome.CUSTOM_SPLIT and (self.claimant_amount is None or self.respondent_amount is None):
            raise ValueError("A custom split needs both claimant_amount and respondent_amount")
        return self
