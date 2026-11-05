import re
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Request, Response, UploadFile, status

from app.core.database import get_db, parse_object_id
from app.core.limiter import PHOTO_UPLOAD_LIMIT, VIDEO_UPLOAD_LIMIT, limiter, user_or_ip
from app.core.security import get_current_user, require_roles
from app.data.areas import POPULAR_AREAS
from app.data.landmarks import LANDMARKS
from app.schemas.booking import BookingStatus
from app.schemas.rental import (
    AreaSummary,
    Landmark,
    ListingCategory,
    ListingIn,
    ListingOut,
    ListingSearchParams,
    ListingSearchResult,
    ROOM_ID_PATTERN,
    RentalStatus,
    RoomType,
    SearchSort,
    listing_fields,
    listing_to_out,
)
from app.schemas.user import Role
from app.services.governance import check_rapid_relist
from app.services.listings import (
    LISTER_LOOKUP,
    PHOTO_ID_PATTERN,
    OPEN_RENTALS,
    RENT_ONLY,
    SALE_ONLY,
    area_filter,
    add_listing_photos,
    area_pattern,
    delete_listing_with_deals,
    listing_photo_response,
    listing_video_response,
    load_listing_doc,
    load_own_listing,
    make_cover_photo,
    region_filter,
    remove_listing_photo,
    remove_listing_video,
    remove_photo_files,
    resolve_center,
    search_target_area,
    set_listing_video,
)

router = APIRouter(prefix="/api/rentals", tags=["rentals"])

MAX_COMPARE = 4

# None keeps $nearSphere's nearest-first order.
_SORT_STAGES = {
    SearchSort.DISTANCE: None,
    SearchSort.RENT_ASC: {"effective_rent": 1, "_id": 1},
    SearchSort.RENT_DESC: {"effective_rent": -1, "_id": 1},
    SearchSort.NEWEST: {"created_at": -1},
}


def _search_filter(params: ListingSearchParams) -> dict:
    # Rented flats and full seat listings never show up in search.
    query: dict = {**OPEN_RENTALS, **region_filter(params.division, params.district, params.upazila)}
    if params.category:
        query["category"] = {"$in": [c.value for c in params.category]}
    for field, low, high in (
        ("effective_rent", params.min_rent, params.max_rent),
        ("building.floor_level", params.min_floor, params.max_floor),
    ):
        bounds = {op: value for op, value in (("$gte", low), ("$lte", high)) if value is not None}
        if bounds:
            query[field] = bounds
    if params.elevator:
        query["building.has_elevator"] = True
    if params.generator:
        query["building.has_generator_backup"] = True
    if params.meter_type is not None:
        query["house_rules.meter_type"] = params.meter_type.value
    if params.smoking_allowed is not None:
        query["house_rules.smoking_allowed"] = params.smoking_allowed
    if params.area_name:
        query.update(area_filter(params.area_name))
    return query


async def _load_listing_out(listing_id: ObjectId | str) -> ListingOut:
    return listing_to_out(await load_listing_doc(listing_id, RENT_ONLY))


def _check_category_allowed(user: dict, payload: ListingIn) -> None:
    # Bachelor tenants may only sublet seats in a flat they already rent.
    if user["role"] == Role.BACHELOR_TENANT and payload.category != ListingCategory.BACHELOR_SEAT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bachelor tenants can only sublet seats")
    # A sublet prices its seat or rooms itself; an owner's seat listing splits the whole flat's rent.
    if user["role"] == Role.BACHELOR_TENANT and payload.sublet is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say whether you're letting a seat or rooms, and their rent")
    if user["role"] != Role.BACHELOR_TENANT and payload.sublet is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only bachelor tenants sublet a seat or rooms")


@router.get("", response_model=ListingSearchResult)
@router.get("/search", response_model=ListingSearchResult)
async def search_listings(params: Annotated[ListingSearchParams, Query()]):
    """Search rentals. With `area_name` and/or a centre (`landmark`, or `lat` + `lng` with `radius_km`), only places
    in that target area come back: a whole-word, case-insensitive area-name match, a $nearSphere radius, or both."""
    center = resolve_center(params.landmark, params.lat, params.lng)
    sort = params.sort or (SearchSort.DISTANCE if center else SearchSort.NEWEST)
    docs, total = await search_target_area(_search_filter(params), center, params.radius_km, _SORT_STAGES[sort], params.limit)
    return ListingSearchResult(
        items=[listing_to_out(doc) for doc in docs],
        total=total,
        area_name=params.area_name,
        center=center,
        radius_km=params.radius_km if center else None,
    )


@router.get("/landmarks", response_model=list[Landmark])
async def list_landmarks():
    return LANDMARKS


@router.get("/areas", response_model=list[AreaSummary])
async def list_areas(
    division: Annotated[str | None, Query(max_length=60)] = None,
    district: Annotated[str | None, Query(max_length=60)] = None,
    upazila: Annotated[str | None, Query(max_length=60)] = None,
):
    """Popular areas, then every other area name owners have used, with how many rentals and sales match each.
    With a division, district or upazila, only the area names of listings there (no popular list)."""
    region = region_filter(division, district, upazila)
    named = await get_db().listings.aggregate(
        [
            # The same availability rules as the two searches, so each count is what that search would return.
            {"$match": {"$or": [OPEN_RENTALS, SALE_ONLY], **region}},
            {
                "$group": {
                    "_id": {"$toLower": "$location.area_name"},
                    "name": {"$first": "$location.area_name"},
                    "sales": {"$sum": {"$cond": [{"$eq": ["$listing_mode", "SALE"]}, 1, 0]}},
                    "rentals": {"$sum": {"$cond": [{"$eq": ["$listing_mode", "SALE"]}, 0, 1]}},
                    "lng": {"$avg": {"$arrayElemAt": ["$location.geo.coordinates", 0]}},
                    "lat": {"$avg": {"$arrayElemAt": ["$location.geo.coordinates", 1]}},
                }
            },
        ]
    ).to_list(None)

    areas, claimed = [], set()
    for area in [] if region else POPULAR_AREAS:
        # The search's whole-word rule, so "Mirpur" also counts "Mirpur 10".
        pattern = re.compile(area_pattern(area["name"]), re.IGNORECASE)
        hits = [entry for entry in named if pattern.search(entry["name"])]
        claimed.update(entry["_id"] for entry in hits)
        areas.append(
            AreaSummary(
                **area,
                popular=True,
                rentals=sum(entry["rentals"] for entry in hits),
                sales=sum(entry["sales"] for entry in hits),
            )
        )
    others = [
        AreaSummary(
            name=entry["name"],
            popular=False,
            lat=round(entry["lat"], 5),
            lng=round(entry["lng"], 5),
            rentals=entry["rentals"],
            sales=entry["sales"],
        )
        for entry in named
        if entry["_id"] not in claimed
    ]
    return areas + sorted(others, key=lambda area: area.name.lower())


@router.get("/mine", response_model=list[ListingOut])
async def my_listings(user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT))):
    pipeline = [{"$match": {"lister_id": user["_id"], **RENT_ONLY}}, {"$sort": {"created_at": -1}}, *LISTER_LOOKUP]
    return [listing_to_out(doc) for doc in await get_db().listings.aggregate(pipeline).to_list(None)]


@router.get("/compare", response_model=list[ListingOut])
async def compare_listings(ids: Annotated[list[str], Query(min_length=1, max_length=MAX_COMPARE)]):
    object_ids = list(dict.fromkeys(parse_object_id(listing_id) for listing_id in ids))
    pipeline = [{"$match": {"_id": {"$in": object_ids}, **RENT_ONLY}}, *LISTER_LOOKUP]
    found = {doc["_id"]: doc for doc in await get_db().listings.aggregate(pipeline).to_list(None)}
    # Keep the caller's order; silently skip listings that were deleted.
    return [listing_to_out(found[oid]) for oid in object_ids if oid in found]


@router.get("/{listing_id}", response_model=ListingOut)
async def get_listing(listing_id: str):
    return await _load_listing_out(listing_id)


@router.post("", response_model=ListingOut, status_code=status.HTTP_201_CREATED)
async def create_listing(
    payload: ListingIn,
    user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT)),
):
    _check_category_allowed(user, payload)
    now = datetime.now(timezone.utc)
    listing = {
        **listing_fields(payload),
        "rental_status": RentalStatus.AVAILABLE.value,
        "lister_id": user["_id"],
        "is_sublet": user["role"] == Role.BACHELOR_TENANT,
        "created_at": now,
        "updated_at": now,
    }
    await get_db().listings.insert_one(listing)
    return await _load_listing_out(listing["_id"])


@router.put("/{listing_id}", response_model=ListingOut)
async def update_listing(
    listing_id: str,
    payload: ListingIn,
    user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT)),
):
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    _check_category_allowed(user, payload)
    deals = await get_db().bookings.find(
        {"listing_id": listing["_id"], "$or": [{"status": BookingStatus.CONFIRMED.value}, {"is_open": True}]}, {"status": 1, "unit": 1}
    ).to_list(None)
    if payload.category != listing["category"] and deals:
        raise HTTPException(status.HTTP_409_CONFLICT, "This place has tenants or open requests, so what it's listed as can't change")
    if payload.sublet is not None:
        fields, removed_rooms = _sublet_fields(payload, listing, deals)
    else:
        fields, removed_rooms = listing_fields(payload), (listing.get("sublet") or {}).get("rooms", [])
    # Seat listings re-open (or close) with their free seat count; whole flats keep their status.
    if payload.seats is not None:
        # Seats held by tenants who confirmed through Bari Khujun can't be offered again.
        held = sum(1 for deal in deals if deal["status"] == BookingStatus.CONFIRMED)
        if payload.seats.available_seats > payload.seats.total_seats - held:
            most = max(payload.seats.total_seats - held, 0)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{held} seat{'s are' if held != 1 else ' is'} taken by tenants who confirmed through Bari Khujun, "
                f"so at most {most} can be free",
            )
    if fields["seats"] is not None:
        fields["rental_status"] = (
            RentalStatus.AVAILABLE.value if fields["seats"]["available_seats"] > 0 else RentalStatus.RENTED.value
        )
    # Matching on updated_at means a seat taken by a QR handshake since the checks above isn't silently overwritten.
    updated = await get_db().listings.update_one(
        {"_id": listing["_id"], "lister_id": user["_id"], "updated_at": listing.get("updated_at")},
        {"$set": {**fields, "updated_at": datetime.now(timezone.utc)}},
    )
    if updated.matched_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "This listing changed just now, perhaps a tenant confirmed a seat. Reload and try again.")
    await remove_photo_files(listing["_id"], [photo["id"] for room in removed_rooms for photo in room.get("photos", [])])
    if _reopened(listing, fields):
        await check_rapid_relist(listing, user["_id"])
    return await _load_listing_out(listing["_id"])


def _sublet_fields(payload: ListingIn, listing: dict, deals: list[dict]) -> tuple[dict, list[dict]]:
    """A sublet's new fields, and the rooms it no longer lets. A seat or room someone rents or has asked for can't be
    taken off the listing, and a room can't have fewer seats than its tenants hold; every other seat is free."""
    held: Counter = Counter()
    asked = set()
    for deal in deals:
        unit = deal.get("unit") or {}
        asked.add(unit.get("room_id"))
        if deal["status"] == BookingStatus.CONFIRMED:
            held[unit.get("room_id")] += unit.get("seats", 1)
    fields = listing_fields(payload, listing, held)
    kept = {room["id"]: room for room in fields["sublet"]["rooms"]}
    removed = [room for room in (listing.get("sublet") or {}).get("rooms", []) if room["id"] not in kept]
    for room in removed:
        if room["id"] in asked:
            what = "The seat" if room["room_type"] == RoomType.SEAT else room["name"]
            raise HTTPException(status.HTTP_409_CONFLICT, f"{what} has a tenant or an open request, so it can't be taken off the listing")
    for room in kept.values():
        if held[room["id"]] > room["seats"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{room['name']}: tenants who confirmed through Bari Khujun hold {held[room['id']]} seats, so it needs at least that many",
            )
    return fields, removed


def _reopened(before: dict, after: dict) -> bool:
    """Did this change put a rented flat, or extra seats, back on the market?"""
    if before.get("rental_status") == RentalStatus.RENTED and after.get("rental_status", before.get("rental_status")) == RentalStatus.AVAILABLE:
        return True
    seats_before = (before.get("seats") or {}).get("available_seats")
    seats_after = (after.get("seats") or {}).get("available_seats")
    return seats_before is not None and seats_after is not None and seats_after > seats_before


@router.post("/{listing_id}/relist", response_model=ListingOut)
async def relist_flat(listing_id: str, user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT))):
    """Put a rented whole flat back on the market (seat listings reopen by editing their free seats)."""
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    if listing["category"] == ListingCategory.BACHELOR_SEAT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reopen seats by editing the listing's free seat count")
    if listing.get("rental_status") != RentalStatus.RENTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This flat is already on the market")
    await get_db().listings.update_one(
        {"_id": listing["_id"], "lister_id": user["_id"], "rental_status": RentalStatus.RENTED.value},
        {"$set": {"rental_status": RentalStatus.AVAILABLE.value, "updated_at": datetime.now(timezone.utc)}},
    )
    # Scammer radar rule 2: relisting right after a QR-confirmed handshake looks like letting the flat twice.
    await check_rapid_relist(listing, user["_id"])
    return await _load_listing_out(listing["_id"])


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_listing(listing_id: str, user: dict = Depends(get_current_user)):
    if user["role"] == Role.ADMIN:
        listing = await get_db().listings.find_one({"_id": parse_object_id(listing_id), **RENT_ONLY})
        if listing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
        await delete_listing_with_deals(listing, {}, by_admin=True)
    else:
        listing = await load_own_listing(listing_id, user, RENT_ONLY)
        await delete_listing_with_deals(listing, {"lister_id": user["_id"]}, by_admin=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- listing photos (the first one is the cover)


@router.post("/{listing_id}/photos", response_model=ListingOut)
@limiter.limit(PHOTO_UPLOAD_LIMIT, key_func=user_or_ip)
async def upload_listing_photos(
    request: Request,
    listing_id: str,
    files: Annotated[list[UploadFile], File(description="JPEG, PNG or WebP, up to 5 MB each")],
    user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT)),
):
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    await add_listing_photos(listing, {"lister_id": user["_id"]}, files)
    return await _load_listing_out(listing["_id"])


@router.delete("/{listing_id}/photos/{photo_id}", response_model=ListingOut)
async def delete_listing_photo(
    listing_id: str, photo_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)], user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT))
):
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    await remove_listing_photo(listing, {"lister_id": user["_id"]}, photo_id)
    return await _load_listing_out(listing["_id"])


@router.post("/{listing_id}/rooms/{room_id}/photos", response_model=ListingOut)
@limiter.limit(PHOTO_UPLOAD_LIMIT, key_func=user_or_ip)
async def upload_room_photos(
    request: Request,
    listing_id: str,
    room_id: Annotated[str, Path(pattern=ROOM_ID_PATTERN)],
    files: Annotated[list[UploadFile], File(description="JPEG, PNG or WebP, up to 5 MB each")],
    user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT)),
):
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    await add_listing_photos(listing, {"lister_id": user["_id"]}, files, room_id=room_id)
    return await _load_listing_out(listing["_id"])


@router.delete("/{listing_id}/rooms/{room_id}/photos/{photo_id}", response_model=ListingOut)
async def delete_room_photo(
    listing_id: str,
    room_id: Annotated[str, Path(pattern=ROOM_ID_PATTERN)],
    photo_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)],
    user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT)),
):
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    await remove_listing_photo(listing, {"lister_id": user["_id"]}, photo_id, room_id=room_id)
    return await _load_listing_out(listing["_id"])


@router.post("/{listing_id}/photos/{photo_id}/cover", response_model=ListingOut)
async def make_listing_cover(
    listing_id: str, photo_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)], user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT))
):
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    await make_cover_photo(listing, {"lister_id": user["_id"]}, photo_id)
    return await _load_listing_out(listing["_id"])


@router.get("/{listing_id}/photos/{photo_id}")
async def get_listing_photo(
    listing_id: str,
    photo_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)],
    size: Annotated[Literal["full", "thumb"], Query()] = "full",
):
    """Public, like the listing itself."""
    listing = await load_listing_doc(listing_id, RENT_ONLY, with_lister=False)
    return listing_photo_response(listing, photo_id, thumbnail=size == "thumb")


# ---------------------------------------------------------------- the listing's one walkthrough video


@router.post("/{listing_id}/video", response_model=ListingOut)
@limiter.limit(VIDEO_UPLOAD_LIMIT, key_func=user_or_ip)
async def upload_listing_video(
    request: Request,
    listing_id: str,
    file: Annotated[UploadFile, File(description="MP4 or MOV, up to 100 MB and 3 minutes")],
    user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT)),
):
    """Replaces the listing's video if it already has one."""
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    await set_listing_video(listing, {"lister_id": user["_id"]}, file)
    return await _load_listing_out(listing["_id"])


@router.delete("/{listing_id}/video/{video_id}", response_model=ListingOut)
async def delete_listing_video(
    listing_id: str, video_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)], user: dict = Depends(require_roles(Role.OWNER, Role.BACHELOR_TENANT))
):
    listing = await load_own_listing(listing_id, user, RENT_ONLY)
    await remove_listing_video(listing, {"lister_id": user["_id"]}, video_id)
    return await _load_listing_out(listing["_id"])


@router.get("/{listing_id}/video/{video_id}")
async def get_listing_video(listing_id: str, video_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)]):
    """Public, like the photos."""
    listing = await load_listing_doc(listing_id, RENT_ONLY, with_lister=False)
    return listing_video_response(listing, video_id)
