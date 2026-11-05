from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.sanitizers import RequestModel, SafeText
from app.schemas.booking import BookingUnit, DepositMethod, UnitChoice
from app.schemas.rental import ListingCategory, RoomType


class NotificationType(StrEnum):
    NEW_MESSAGE = "NEW_MESSAGE"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    VISIT_STATUS_CHANGED = "VISIT_STATUS_CHANGED"
    QR_UPDATE = "QR_UPDATE"
    OFFER_UPDATE = "OFFER_UPDATE"


class MessageType(StrEnum):
    TEXT = "TEXT"
    VISIT_REQUEST_CARD = "VISIT_REQUEST_CARD"
    OFFER_PROPOSAL_CARD = "OFFER_PROPOSAL_CARD"
    QR_CONFIRMATION_CARD = "QR_CONFIRMATION_CARD"


# ---------------------------------------------------------------- messages and threads


class ChatSend(RequestModel):
    property_id: str
    receiver_id: str
    content: SafeText = Field(min_length=1, max_length=2000)


class ActionPayload(BaseModel):
    """State of an action card. The first seven fields are on every card (null where they don't apply); each card
    type adds its own details (visit mode, offer type, deposit, lease readiness...)."""

    model_config = ConfigDict(extra="allow")

    reference_id: str
    status: str
    scheduled_date: date | None = None
    scheduled_time: str | None = None
    proposed_amount: int | None = None
    # Only present while the code can still be used; stripped once it is confirmed, expired or replaced.
    qr_token: str | None = None
    expires_at: datetime | None = None


class ChatMessageOut(BaseModel):
    id: str
    thread_id: str
    property_id: str
    sender_id: str
    receiver_id: str
    content: str
    message_type: MessageType = MessageType.TEXT
    action_payload: ActionPayload | None = None
    created_at: datetime
    is_delivered: bool
    is_read: bool


class MessagePage(BaseModel):
    items: list[ChatMessageOut]
    has_more: bool


class ChatUser(BaseModel):
    id: str
    full_name: str
    role: str
    online: bool


class ThreadListing(BaseModel):
    id: str
    title: str
    listing_mode: Literal["RENT", "SALE"]
    lister_id: str


class ThreadOut(BaseModel):
    thread_id: str
    property_id: str
    listing: ThreadListing | None
    other_user: ChatUser
    last_message: ChatMessageOut
    unread_count: int


class OpenBooking(BaseModel):
    id: str
    status: str
    agreed_rent: int
    deposit_amount: int


class ThreadRoom(BaseModel):
    id: str
    name: str
    room_type: RoomType
    seats: int
    available_seats: int
    seat_rent: int


class ThreadListingDetail(ThreadListing):
    category: ListingCategory | None = None
    effective_rent: int | None = None
    asking_price: int | None = None
    available: bool
    # A bachelor tenant's sublet: its seat or rooms, one of which a rent proposal is for.
    rooms: list[ThreadRoom] | None = None


class ThreadContext(BaseModel):
    """Everything the chat window needs besides the messages: who is on the other end and which quick actions the
    viewer may use. The server checks the same rules again when an action is taken."""

    thread_id: str
    listing: ThreadListingDetail
    other_user: ChatUser
    viewer_is_lister: bool
    can_make_offer: bool
    can_send_qr: bool
    open_booking: OpenBooking | None = None


# ---------------------------------------------------------------- notifications


class NotificationOut(BaseModel):
    id: str
    recipient_id: str
    sender_id: str | None = None
    property_id: str | None = None
    type: NotificationType
    title: str
    message: str
    metadata: dict = {}
    is_delivered: bool
    is_read: bool
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread_count: int


# ---------------------------------------------------------------- chat actions


class RentOfferStatus(StrEnum):
    AWAITING_OWNER = "AWAITING_OWNER"
    AWAITING_TENANT = "AWAITING_TENANT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


OPEN_RENT_OFFER_STATUSES = (RentOfferStatus.AWAITING_OWNER, RentOfferStatus.AWAITING_TENANT)


class RentOfferCreate(UnitChoice):
    listing_id: str
    amount: int = Field(gt=0, le=10_000_000, description="Proposed monthly rent in BDT")
    move_in_date: date
    # The same advance a plain rent request logs, so an accepted offer turns straight into a booking.
    deposit_amount: int = Field(gt=0, le=10_000_000, description="Advance paid, in BDT")
    payment_method: DepositMethod
    payment_reference: SafeText = Field(min_length=3, max_length=60, description="bKash/Nagad TrxID or bank reference")
    note: SafeText | None = Field(default=None, max_length=500)


class RentOfferResponse(RequestModel):
    action: Literal["ACCEPT", "REJECT", "COUNTER", "WITHDRAW"]
    amount: int | None = Field(default=None, gt=0, le=10_000_000)
    deposit_amount: int | None = Field(default=None, gt=0, le=10_000_000)
    note: SafeText | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def counter_needs_amount(self) -> "RentOfferResponse":
        if self.action == "COUNTER" and self.amount is None:
            raise ValueError("A counter-offer needs an amount")
        if self.action != "COUNTER" and (self.amount is not None or self.deposit_amount is not None):
            raise ValueError("Only counter-offers carry amounts")
        return self


class RentOfferEvent(BaseModel):
    at: datetime
    actor: Literal["TENANT", "OWNER", "SYSTEM"]
    event: str
    amount: int | None = None
    deposit_amount: int | None = None
    note: str | None = None


class RentOfferParty(BaseModel):
    id: str
    full_name: str


class RentOfferOut(BaseModel):
    id: str
    listing_id: str
    listing_title: str
    unit: BookingUnit | None = None
    listed_rent: int
    owner: RentOfferParty
    tenant: RentOfferParty
    status: RentOfferStatus
    amount: int
    deposit_amount: int
    move_in_date: date
    booking_id: str | None = None
    history: list[RentOfferEvent]
    created_at: datetime
    updated_at: datetime


class ChatQrSend(RequestModel):
    property_id: str
    tenant_id: str
