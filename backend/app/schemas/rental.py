import math
from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.database import serialize_doc
from app.services.bd_admin import with_admin_area
from app.schemas.user import KycStatus, Role
from app.core.sanitizers import RequestModel, SafeText


class ListingCategory(StrEnum):
    FAMILY_FLAT = "FAMILY_FLAT"
    BACHELOR_FLAT = "BACHELOR_FLAT"
    BACHELOR_SEAT = "BACHELOR_SEAT"


class RentalStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"


class MeterType(StrEnum):
    PREPAID = "PREPAID"
    POSTPAID = "POSTPAID"


class GuestPolicy(StrEnum):
    NOT_ALLOWED = "NOT_ALLOWED"
    DAYTIME_ONLY = "DAYTIME_ONLY"
    ALLOWED = "ALLOWED"


class OccupationType(StrEnum):
    STUDENT = "STUDENT"
    PROFESSIONAL = "PROFESSIONAL"


class Habit(StrEnum):
    EARLY_RISER = "EARLY_RISER"
    NIGHT_OWL = "NIGHT_OWL"
    NON_SMOKER = "NON_SMOKER"
    SMOKER = "SMOKER"
    QUIET = "QUIET"
    SOCIAL = "SOCIAL"
    TIDY = "TIDY"
    COOKS = "COOKS"
    WORKS_FROM_HOME = "WORKS_FROM_HOME"


class SearchSort(StrEnum):
    DISTANCE = "distance"
    RENT_ASC = "rent_asc"
    RENT_DESC = "rent_desc"
    NEWEST = "newest"


Taka = Annotated[int, Field(ge=0, le=10_000_000)]


# Listings are in Bangladesh. The box also catches swapped coordinates and an unset (0, 0) pin.
BANGLADESH_LNG = (88.0, 92.7)
BANGLADESH_LAT = (20.5, 26.7)


class GeoPoint(RequestModel):
    """GeoJSON point. Note the GeoJSON order: [longitude, latitude]."""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def coordinates_in_bangladesh(cls, value: tuple[float, float]) -> tuple[float, float]:
        lng, lat = value
        if not (BANGLADESH_LNG[0] <= lng <= BANGLADESH_LNG[1] and BANGLADESH_LAT[0] <= lat <= BANGLADESH_LAT[1]):
            raise ValueError("The map pin must be in Bangladesh, as [longitude, latitude]")
        return value


class ListingLocation(RequestModel):
    """Where a property is: the pinned point (indexed 2dsphere at `location.geo`) and the address shown with it.

    `area_name` is the area tenants filter by ("Uttara"), `sub_area` the part of it ("Sector 7"), and
    `formatted_address` the full address ("House 12, Road 4, Sector 7, Uttara, Dhaka").
    """

    city: SafeText = Field(default="Dhaka", min_length=2, max_length=60)
    area_name: SafeText = Field(min_length=2, max_length=60)
    sub_area: SafeText | None = Field(default=None, max_length=60)
    formatted_address: SafeText = Field(min_length=3, max_length=200)
    geo: GeoPoint

    @field_validator("sub_area")
    @classmethod
    def blank_sub_area_is_none(cls, value: str | None) -> str | None:
        return value or None


class Pricing(RequestModel):
    # Monthly amounts in BDT for the whole flat; seat listings split these per seat. A bachelor tenant's sublet
    # prices its seat or rooms itself (see SubletIn), so it has no whole-flat rent and only uses deposit_months.
    base_rent: Annotated[int, Field(gt=0, le=10_000_000)] | None = None
    service_charge: Taka = 0
    deposit_months: int = Field(default=2, ge=0, le=12)
    utility_estimate: Taka = 0
    maid_estimate: Taka = 0


class Building(RequestModel):
    floor_level: int = Field(ge=0, le=80, description="0 is the ground floor")
    total_floors: int = Field(ge=1, le=80)
    has_elevator: bool = False
    has_generator_backup: bool = False
    bedrooms: int = Field(ge=1, le=12)
    bathrooms: int = Field(ge=1, le=12)
    size_sqft: int | None = Field(default=None, ge=80, le=20_000)

    @model_validator(mode="after")
    def floor_within_building(self) -> "Building":
        if self.floor_level >= self.total_floors:
            raise ValueError("floor_level must be below total_floors (ground floor is 0)")
        return self


class HouseRules(RequestModel):
    # None means the gate stays open all night.
    gate_closing_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    guest_policy: GuestPolicy
    smoking_allowed: bool
    meter_type: MeterType


class Flatmate(RequestModel):
    display_name: SafeText = Field(min_length=1, max_length=40)
    occupation_type: OccupationType
    institution: SafeText = Field(min_length=2, max_length=100, description="University or workplace")
    habits: list[Habit] = Field(default=[], max_length=6)

    @field_validator("habits")
    @classmethod
    def habits_consistent(cls, habits: list[Habit]) -> list[Habit]:
        if Habit.SMOKER in habits and Habit.NON_SMOKER in habits:
            raise ValueError("A flatmate cannot be both SMOKER and NON_SMOKER")
        return list(dict.fromkeys(habits))


class SeatsIn(RequestModel):
    total_seats: int = Field(ge=2, le=20)
    available_seats: int = Field(ge=0, le=20)
    flatmates: list[Flatmate] = Field(default=[], max_length=20)

    @model_validator(mode="after")
    def seat_counts_consistent(self) -> "SeatsIn":
        if self.available_seats > self.total_seats:
            raise ValueError("available_seats cannot exceed total_seats")
        if len(self.flatmates) > self.total_seats - self.available_seats:
            raise ValueError("More flatmates listed than occupied seats")
        return self


class SeatSplit(BaseModel):
    per_seat_rent: int
    per_seat_service_charge: int
    per_seat_utility: int
    per_seat_maid: int
    per_seat_total: int


class SeatsOut(BaseModel):
    total_seats: int
    available_seats: int
    flatmates: list[Flatmate] = []
    # The owner's whole-flat costs divided per seat. Sublets price their seat or rooms directly, so they have none.
    split: SeatSplit | None = None


# ---------------------------------------------------------------- a bachelor tenant's sublet: one seat, or rooms
#
# A bachelor tenant lets either one seat in a shared room of the flat they rent, or one or more rooms. Each room is a
# single room (one tenant takes it) or a shared room with 2+ seats (a tenant takes one seat, or the whole room while
# every seat in it is free). Each is priced on its own, with optional charges, instead of splitting the flat's rent.
#
# Stored as `sublet.rooms`, one entry per thing that can be let, the single seat included (as a SEAT entry), so
# asking for, confirming and moving out of a seat or room work the same way. `seats.total_seats` and
# `seats.available_seats` add the entries up, so searches and the seat lock treat sublets like any seat listing.


class SubletType(StrEnum):
    SEAT = "SEAT"
    ROOMS = "ROOMS"


class RoomType(StrEnum):
    SINGLE = "SINGLE"  # one tenant takes the room
    SHARED = "SHARED"  # 2+ seats: one seat, or the whole room while every seat is free
    SEAT = "SEAT"  # the one seat of a single-seat sublet, in a shared room


# Room ids, like listing photo ids, are uuid4 hex.
ROOM_ID_PATTERN = r"^[0-9a-f]{32}$"
MAX_ROOM_SEATS = 6


class SubletCharges(RequestModel):
    # Monthly, per seat (for a single room, for the room). Optional: 0 means none.
    service_charge: Taka = 0
    utility_estimate: Taka = 0
    maid_estimate: Taka = 0


class SubletSeatIn(SubletCharges):
    room_size: int = Field(ge=2, le=MAX_ROOM_SEATS, description="Seats in the shared room, this one included")
    seat_rent: Annotated[int, Field(gt=0, le=10_000_000)]


class SubletRoomIn(SubletCharges):
    # Sent back for rooms that already exist, so their photos and tenants stay with them. New rooms get one.
    id: str | None = Field(default=None, pattern=ROOM_ID_PATTERN)
    name: SafeText = Field(min_length=1, max_length=40, description='e.g. "Room 1", "Master bedroom"')
    room_type: Literal[RoomType.SINGLE, RoomType.SHARED]
    seats: int = Field(default=1, ge=1, le=MAX_ROOM_SEATS)
    seat_rent: Annotated[int, Field(gt=0, le=10_000_000, description="The room's rent, or each seat's in a shared room")]

    @model_validator(mode="after")
    def seats_match_type(self) -> "SubletRoomIn":
        if self.room_type == RoomType.SINGLE and self.seats != 1:
            raise ValueError(f"{self.name}: a single room has one seat")
        if self.room_type == RoomType.SHARED and self.seats < 2:
            raise ValueError(f"{self.name}: a shared room has at least 2 seats")
        return self


class SubletIn(RequestModel):
    let_type: SubletType
    seat: SubletSeatIn | None = None
    rooms: list[SubletRoomIn] = Field(default=[], max_length=12)
    flatmates: list[Flatmate] = Field(default=[], max_length=20)

    @model_validator(mode="after")
    def matches_let_type(self) -> "SubletIn":
        if self.let_type == SubletType.SEAT and (self.seat is None or self.rooms):
            raise ValueError("A single-seat sublet needs the seat's details and no rooms")
        if self.let_type == SubletType.ROOMS:
            if self.seat is not None or not self.rooms:
                raise ValueError("Add at least one room")
            ids = [room.id for room in self.rooms if room.id]
            if len(ids) != len(set(ids)):
                raise ValueError("Each room can only be listed once")
        return self


class ListingIn(RequestModel):
    category: ListingCategory
    title: SafeText = Field(min_length=5, max_length=120)
    description: SafeText = Field(default="", max_length=2000)
    location: ListingLocation
    pricing: Pricing
    building: Building
    house_rules: HouseRules
    seats: SeatsIn | None = None
    # Bachelor tenants sublet with this instead of `seats` (the router checks who sends which).
    sublet: SubletIn | None = None
    available_from: date

    @model_validator(mode="after")
    def seats_match_category(self) -> "ListingIn":
        if self.category == ListingCategory.BACHELOR_SEAT:
            if (self.seats is None) == (self.sublet is None):
                raise ValueError("BACHELOR_SEAT listings need seat details")
        elif self.seats is not None or self.sublet is not None:
            raise ValueError("Seat details only apply to BACHELOR_SEAT listings")
        if self.sublet is not None:
            if len(self.sublet.rooms) > self.building.bedrooms:
                raise ValueError(f"The flat has {self.building.bedrooms} bedroom(s), so at most that many rooms can be let")
            # The seat or each room has its own rent and charges; whole-flat figures don't apply.
            self.pricing = Pricing(deposit_months=self.pricing.deposit_months)
        elif self.pricing.base_rent is None:
            raise ValueError("Enter the monthly rent")
        return self


class PlacedLocation(ListingLocation):
    """A stored location: what the lister sent, plus the division, district and upazila/thana the server found the pin
    in (None outside Bangladesh's mapped areas)."""

    model_config = ConfigDict(extra="ignore")

    division: str | None = None
    district: str | None = None
    upazila: str | None = None


class ListingPhoto(BaseModel):
    """Served at .../photos/{id} (and ?size=thumb); the first photo is the cover."""

    id: str
    width: int
    height: int


class ListingVideo(BaseModel):
    """The one walkthrough video a listing can have, served at .../video/{id}."""

    id: str
    size_bytes: int
    duration_seconds: float | None = None


class SubletRoomOut(BaseModel):
    id: str
    name: str
    room_type: RoomType
    seats: int
    available_seats: int
    seat_rent: int
    service_charge: int = 0
    utility_estimate: int = 0
    maid_estimate: int = 0
    # SEAT only: the shared room's seats, this one included.
    room_size: int | None = None
    photos: list[ListingPhoto] = []


class SubletOut(BaseModel):
    let_type: SubletType
    rooms: list[SubletRoomOut]


class ListerSummary(BaseModel):
    id: str
    full_name: str
    role: Role
    kyc_status: KycStatus
    trust_score: int
    review_count: int = 0
    rating_average: float | None = None


class ListingOut(BaseModel):
    id: str
    lister_id: str
    lister: ListerSummary | None = None
    listing_mode: Literal["RENT"] = "RENT"
    rental_status: RentalStatus = RentalStatus.AVAILABLE
    is_sublet: bool
    category: ListingCategory
    title: str
    description: str
    location: PlacedLocation
    photos: list[ListingPhoto] = []
    video: ListingVideo | None = None
    pricing: Pricing
    building: Building
    house_rules: HouseRules
    seats: SeatsOut | None = None
    sublet: SubletOut | None = None
    available_from: date
    # What one tenant pays in rent each month: the per-seat rent for seats (for a sublet, its cheapest free seat or
    # room), the base rent otherwise.
    effective_rent: int
    # Earliest date a tenant who gave notice moves out, so a rented place can say when it reopens.
    reopens_on: date | None = None
    distance_km: float | None = None
    created_at: datetime
    updated_at: datetime


class ListingSearchParams(RequestModel):
    category: list[ListingCategory] = []
    min_rent: int | None = Field(default=None, ge=0)
    max_rent: int | None = Field(default=None, ge=0)
    min_floor: int | None = Field(default=None, ge=0)
    max_floor: int | None = Field(default=None, ge=0)
    elevator: bool = Field(default=False, description="Only listings with an elevator")
    generator: bool = Field(default=False, description="Only listings with generator backup")
    meter_type: MeterType | None = None
    smoking_allowed: bool | None = None
    # Narrow to a division, district and/or upazila/thana (names as in /api/locations).
    division: SafeText | None = Field(default=None, max_length=60)
    district: SafeText | None = Field(default=None, max_length=60)
    upazila: SafeText | None = Field(default=None, max_length=60)
    # The tenant's target area. Given alone it filters by area name; with a point it must match both.
    area_name: SafeText | None = Field(default=None, min_length=2, max_length=60, description="Whole-word, case-insensitive")
    landmark: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9-]+$", description="Landmark id from /api/rentals/landmarks")
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=2, gt=0, le=50)
    sort: SearchSort | None = None
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def ranges_and_center_valid(self) -> "ListingSearchParams":
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be given together")
        for low, high, name in (
            (self.min_rent, self.max_rent, "rent"),
            (self.min_floor, self.max_floor, "floor"),
        ):
            if low is not None and high is not None and low > high:
                raise ValueError(f"min_{name} cannot exceed max_{name}")
        if self.sort == SearchSort.DISTANCE and self.landmark is None and self.lat is None:
            raise ValueError("Sorting by distance needs a landmark or lat/lng")
        return self


class Landmark(BaseModel):
    id: str
    name: str
    kind: Literal["UNIVERSITY", "OFFICE_HUB"]
    area: str
    lat: float
    lng: float


class SearchCenter(BaseModel):
    lat: float
    lng: float
    label: str


class ListingSearchResult(BaseModel):
    items: list[ListingOut]
    total: int
    area_name: str | None = None
    center: SearchCenter | None = None
    radius_km: float | None = None


class AreaSummary(BaseModel):
    name: str
    # Popular areas come from app/data/areas.py; others are names owners used, centred on their listings.
    popular: bool
    lat: float
    lng: float
    radius_km: float | None = None
    rentals: int
    sales: int


def compute_seat_split(pricing: Pricing, total_seats: int) -> SeatSplit:
    # Round each share up so the seats together always cover the flat's costs.
    def share(amount: int) -> int:
        return math.ceil(amount / total_seats)

    parts = {
        "per_seat_rent": share(pricing.base_rent),
        "per_seat_service_charge": share(pricing.service_charge),
        "per_seat_utility": share(pricing.utility_estimate),
        "per_seat_maid": share(pricing.maid_estimate),
    }
    return SeatSplit(**parts, per_seat_total=sum(parts.values()))


def sublet_rent(rooms: list[dict]) -> int:
    """A sublet's search price: its cheapest seat or room still free (or at all, once everything is taken).
    Mirrors SUBLET_RENT_EXPR."""
    free = [room["seat_rent"] for room in rooms if room["available_seats"] > 0]
    return min(free or [room["seat_rent"] for room in rooms])


# sublet_rent() inside a MongoDB update pipeline, so taking or giving back a seat keeps the search price right.
SUBLET_RENT_EXPR = {
    "$ifNull": [
        {
            "$min": {
                "$map": {
                    "input": {"$filter": {"input": "$sublet.rooms", "cond": {"$gt": ["$$this.available_seats", 0]}}},
                    "in": "$$this.seat_rent",
                }
            }
        },
        {"$min": "$sublet.rooms.seat_rent"},
    ]
}


def _sublet_rooms(sublet: SubletIn, existing: dict | None, held: Counter) -> list[dict]:
    """Stored entries for a sublet. Rooms sent back with their id (and the seat, while the listing stays a single-seat
    sublet) keep their id and photos. Every seat not held by a tenant who confirmed through Bari Khujun is free."""
    stored = {room["id"]: room for room in ((existing or {}).get("sublet") or {}).get("rooms", [])}

    def entry(room_id: str | None, fields: dict) -> dict:
        kept = stored.get(room_id)
        entry_id = kept["id"] if kept else uuid4().hex
        free = max(fields["seats"] - held[entry_id], 0)
        return {**fields, "id": entry_id, "available_seats": free, "photos": kept.get("photos", []) if kept else []}

    if sublet.let_type == SubletType.SEAT:
        seat_id = next((room["id"] for room in stored.values() if room["room_type"] == RoomType.SEAT), None)
        return [entry(seat_id, {"name": "Shared room", "room_type": RoomType.SEAT.value, "seats": 1, **sublet.seat.model_dump(mode="json")})]
    return [entry(room.id, room.model_dump(mode="json", exclude={"id"})) for room in sublet.rooms]


def listing_fields(payload: ListingIn, existing: dict | None = None, held: Counter | None = None) -> dict:
    """Mongo fields for a listing, including the server-calculated seat split (or a sublet's rooms and seat totals),
    effective rent, and the division, district and upazila its pin is in. For a sublet being edited, `existing` is the
    stored listing and `held` counts the seats tenants hold in each of its rooms."""
    fields = {**payload.model_dump(mode="json", exclude={"sublet"}), "listing_mode": "RENT", "sublet": None}
    fields["location"] = with_admin_area(fields["location"])
    if payload.sublet is not None:
        rooms = _sublet_rooms(payload.sublet, existing, held or Counter())
        fields["sublet"] = {"let_type": payload.sublet.let_type.value, "rooms": rooms}
        fields["seats"] = {
            "total_seats": sum(room["seats"] for room in rooms),
            "available_seats": sum(room["available_seats"] for room in rooms),
            "flatmates": [mate.model_dump(mode="json") for mate in payload.sublet.flatmates],
        }
        fields["effective_rent"] = sublet_rent(rooms)
    elif payload.seats is not None:
        split = compute_seat_split(payload.pricing, payload.seats.total_seats)
        fields["seats"]["split"] = split.model_dump()
        fields["effective_rent"] = split.per_seat_rent
    else:
        fields["effective_rent"] = payload.pricing.base_rent
    return fields


def find_room(listing: dict, room_id: str | None) -> dict | None:
    """One of a sublet's rooms (or its seat) by id."""
    return next((room for room in ((listing.get("sublet") or {}).get("rooms") or []) if room["id"] == room_id), None)


def listing_to_out(doc: dict) -> ListingOut:
    data = serialize_doc(doc)
    if "distance_m" in data:
        data["distance_km"] = round(data.pop("distance_m") / 1000, 2)
    vacancies = data.pop("upcoming_vacancies", None) or []
    data["reopens_on"] = min((v["available_from"] for v in vacancies), default=None)
    return ListingOut.model_validate(data)
