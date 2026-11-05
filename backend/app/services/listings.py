"""Query helpers shared by the rentals and marketplace routers (both live in the `listings` collection)."""

import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from bson import ObjectId
from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.database import get_db, parse_object_id
from app.data.landmarks import LANDMARKS_BY_ID
from app.schemas.booking import OPEN_BOOKING_STATUSES, BookingStatus, EscrowStatus
from app.schemas.marketplace import OfferEventType, OfferStatus
from app.schemas.rental import SUBLET_RENT_EXPR, RentalStatus, RoomType, SearchCenter, SubletType, find_room
from app.services.bd_admin import with_admin_area
from app.services.governance import log_qr_event
from app.utils.file_security import (
    listing_photo_paths,
    listing_video_path,
    public_photo_response,
    public_video_response,
    store_listing_photo,
    store_listing_video,
)

MAX_LISTING_PHOTOS = 10
# Each room a bachelor tenant sublets has its own photos, on top of the listing's.
MAX_ROOM_PHOTOS = 4
# Listing photo ids are uuid4 hex; checked before any file path is built from one.
PHOTO_ID_PATTERN = r"^[0-9a-f]{32}$"

# Listings created before sale support have no listing_mode, so "not SALE" means rental.
# Listings of banned users are suspended and hidden from every public and owner-facing query.
RENT_ONLY = {"listing_mode": {"$ne": "SALE"}, "suspended": {"$ne": True}}
SALE_ONLY = {"listing_mode": "SALE", "suspended": {"$ne": True}}

# What a tenant can still take: not rented, and seat listings with a free seat. Every rental search starts here.
OPEN_RENTALS = {
    **RENT_ONLY,
    "rental_status": {"$ne": "RENTED"},
    "$or": [{"category": {"$ne": "BACHELOR_SEAT"}}, {"seats.available_seats": {"$gte": 1}}],
}

# The pinned point of every listing (2dsphere-indexed at startup).
GEO_KEY = "location.geo"
# The Earth radius MongoDB's spherical geometry uses, so a $centerSphere circle matches $nearSphere's $maxDistance.
EARTH_RADIUS_KM = 6378.1

LISTER_FIELDS = {"full_name": 1, "role": 1, "kyc_status": 1, "trust_score": 1, "review_count": 1, "rating_average": 1}
LISTER_LOOKUP = [
    {"$lookup": {"from": "users", "localField": "lister_id", "foreignField": "_id", "as": "lister", "pipeline": [{"$project": LISTER_FIELDS}]}},
    {"$set": {"lister": {"$first": "$lister"}}},
]


def change_room_seats(room_id: str, delta: int, now: datetime) -> list[dict]:
    """Update pipeline that adds `delta` free seats to one of a sublet's rooms (kept within 0 and the room's seats),
    then refreshes the listing's free-seat total, its search price and whether it's RENTED. Shared by the QR handshake
    and the move-out job."""
    return [
        {
            "$set": {
                "sublet.rooms": {
                    "$map": {
                        "input": "$sublet.rooms",
                        "in": {
                            "$cond": [
                                {"$eq": ["$$this.id", room_id]},
                                {
                                    "$mergeObjects": [
                                        "$$this",
                                        {"available_seats": {"$max": [0, {"$min": ["$$this.seats", {"$add": ["$$this.available_seats", delta]}]}]}},
                                    ]
                                },
                                "$$this",
                            ]
                        },
                    }
                },
                "updated_at": now,
            }
        },
        {"$set": {"seats.available_seats": {"$sum": "$sublet.rooms.available_seats"}, "effective_rent": SUBLET_RENT_EXPR}},
        {
            "$set": {
                "rental_status": {
                    "$cond": [{"$lte": ["$seats.available_seats", 0]}, RentalStatus.RENTED.value, RentalStatus.AVAILABLE.value]
                }
            }
        },
    ]


def resolve_center(landmark_id: str | None, lat: float | None, lng: float | None) -> SearchCenter | None:
    if landmark_id is not None:
        landmark = LANDMARKS_BY_ID.get(landmark_id)
        if landmark is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown landmark")
        return SearchCenter(lat=landmark["lat"], lng=landmark["lng"], label=landmark["name"])
    if lat is not None and lng is not None:
        return SearchCenter(lat=lat, lng=lng, label="Dropped pin")
    return None


def area_pattern(name: str) -> str:
    """Regex matching `name` as whole words with any spacing: "Mirpur" matches "Mirpur 10", but "Mirpur 1" doesn't.

    Used case-insensitively. Every word is escaped, so user input can't inject regex syntax.
    """
    return r"(?<!\w)" + r"\s+".join(re.escape(word) for word in name.split()) + r"(?!\w)"


def area_filter(name: str) -> dict:
    return {"location.area_name": {"$regex": area_pattern(name), "$options": "i"}}


def region_filter(division: str | None, district: str | None, upazila: str | None) -> dict:
    """Exact (case-insensitive) match on the division, district and upazila the server stored for each listing."""
    return {
        f"location.{level}": {"$regex": f"^{re.escape(value.strip())}$", "$options": "i"}
        for level, value in (("division", division), ("district", district), ("upazila", upazila))
        if value
    }


async def backfill_sublets() -> int:
    """Give bachelor tenants' sublets saved before sublets were priced room by room the shape they have now. They
    priced the whole flat and split it per seat; at the per-seat figures they showed, one free seat (or none) becomes
    a single-seat sublet, and more become one shared room. Their open requests, rent offers and tenants are pointed at
    that seat or room. A no-op once done."""
    db = get_db()
    updated = 0
    async for listing in db.listings.find({"category": "BACHELOR_SEAT", "is_sublet": True, "sublet": None}):
        seats, pricing = listing["seats"], listing["pricing"]
        split = seats.get("split") or {}

        def share(key: str, split_key: str) -> int:
            return split.get(split_key, math.ceil((pricing.get(key) or 0) / seats["total_seats"]))

        prices = {
            "seat_rent": share("base_rent", "per_seat_rent"),
            "service_charge": share("service_charge", "per_seat_service_charge"),
            "utility_estimate": share("utility_estimate", "per_seat_utility"),
            "maid_estimate": share("maid_estimate", "per_seat_maid"),
        }
        free = seats["available_seats"]
        if free <= 1:
            # The shared room's size wasn't recorded; 2 is the usual, and the tenant can correct it.
            room = {"name": "Shared room", "room_type": RoomType.SEAT.value, "seats": 1, "available_seats": free, "room_size": 2}
            let_type = SubletType.SEAT
        else:
            size = min(free, 6)
            room = {"name": "Room 1", "room_type": RoomType.SHARED.value, "seats": size, "available_seats": size}
            let_type = SubletType.ROOMS
        room = {**room, **prices, "id": uuid4().hex, "photos": []}
        await db.listings.update_one(
            {"_id": listing["_id"]},
            {
                "$set": {
                    "sublet": {"let_type": let_type.value, "rooms": [room]},
                    "pricing": {"base_rent": None, "service_charge": 0, "utility_estimate": 0, "maid_estimate": 0, "deposit_months": pricing["deposit_months"]},
                    "seats": {"total_seats": room["seats"], "available_seats": room["available_seats"], "flatmates": seats.get("flatmates", [])},
                    "effective_rent": room["seat_rent"],
                }
            },
        )
        unit = {"room_id": room["id"], "room_name": room["name"], "seats": 1, "whole_room": False}
        await db.bookings.update_many({"listing_id": listing["_id"], "unit": None}, {"$set": {"unit": unit}})
        await db.rent_offers.update_many({"listing_id": listing["_id"], "unit": None}, {"$set": {"unit": unit, "listed_rent": room["seat_rent"]}})
        updated += 1
    return updated


async def backfill_admin_areas() -> int:
    """Give listings saved before divisions/districts/upazilas were tracked theirs. A no-op once all have them."""
    db = get_db()
    updated = 0
    async for listing in db.listings.find({"location.geo": {"$exists": True}, "location.district": {"$exists": False}}, {"location": 1}):
        await db.listings.update_one({"_id": listing["_id"]}, {"$set": {"location": with_admin_area(listing["location"])}})
        updated += 1
    return updated


def _names(text: str, part: str) -> bool:
    return re.search(area_pattern(part), text, re.IGNORECASE) is not None


def area_label(location: dict) -> str:
    """"Sector 7, Uttara", or just "Gulshan 1" when the sub-area already names its area."""
    sub_area, area = location.get("sub_area"), location["area_name"]
    if not sub_area:
        return area
    return sub_area if _names(sub_area, area) else f"{sub_area}, {area}"


def full_address(location: dict) -> str:
    """The full address, adding the sub-area, area or city when `formatted_address` doesn't already name it."""
    text = location["formatted_address"]
    for part in (location.get("sub_area"), location["area_name"], location["city"]):
        if part and not _names(text, part):
            text = f"{text}, {part}"
    return text


def _distance_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * 1000 * math.asin(math.sqrt(a))


async def search_target_area(
    query: dict, center: SearchCenter | None, radius_km: float, sort: dict | None, limit: int
) -> tuple[list[dict], int]:
    """Listings matching `query` inside the searcher's target area, and how many there are in all.

    With a centre, $nearSphere keeps only listings within `radius_km` of it, nearest first; `sort` (None for nearest
    first) re-orders them. Counts can't use $nearSphere, so the total uses the same circle via $geoWithin/$centerSphere.
    Each listing comes back with its lister's summary, and `distance_m` from the centre.
    """
    find_query, count_query = dict(query), dict(query)
    if center is not None:
        point = [center.lng, center.lat]
        find_query[GEO_KEY] = {
            "$nearSphere": {"$geometry": {"type": "Point", "coordinates": point}, "$maxDistance": radius_km * 1000}
        }
        count_query[GEO_KEY] = {"$geoWithin": {"$centerSphere": [point, radius_km / EARTH_RADIUS_KM]}}
    cursor = get_db().listings.find(find_query)
    if sort:
        cursor = cursor.sort(list(sort.items()))
    docs = await cursor.limit(limit).to_list(limit)
    total = await get_db().listings.count_documents(count_query)

    lister_ids = list({doc["lister_id"] for doc in docs})
    listers = {user["_id"]: user async for user in get_db().users.find({"_id": {"$in": lister_ids}}, LISTER_FIELDS)}
    for doc in docs:
        doc["lister"] = listers.get(doc["lister_id"])
        if center is not None:
            lng, lat = doc["location"]["geo"]["coordinates"]
            doc["distance_m"] = _distance_m(center.lng, center.lat, lng, lat)
    return docs, total


async def load_listing_doc(listing_id: str | ObjectId, mode_filter: dict, with_lister: bool = True) -> dict:
    oid = listing_id if isinstance(listing_id, ObjectId) else parse_object_id(listing_id)
    pipeline = [{"$match": {"_id": oid, **mode_filter}}, *(LISTER_LOOKUP if with_lister else [])]
    docs = await get_db().listings.aggregate(pipeline).to_list(1)
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return docs[0]


async def delete_listing_with_deals(listing: dict, owner_filter: dict, by_admin: bool) -> None:
    """Delete a listing and call off everything that hangs on it.

    Refused (409) while someone rents the place or an offer on it has been accepted. The listing is suspended first,
    so no QR handshake or offer acceptance can complete on it while this runs. Then open rent requests are cancelled
    with their deposit marked for refund (their QR codes stop working), open offers close, and upcoming visits are
    called off. `owner_filter` ({"lister_id": ...}, or {} for an admin) is part of every write to the listing.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    target = {"_id": listing["_id"], **owner_filter}
    await db.listings.update_one(target, {"$set": {"suspended": True}})

    is_sale = listing.get("listing_mode") == "SALE"
    if is_sale:
        blocker = await db.offers.find_one({"listing_id": listing["_id"], "status": OfferStatus.ACCEPTED.value}, {"_id": 1})
        reason = "You've accepted an offer on this property, so it can't be deleted while that deal stands."
    else:
        blocker = await db.bookings.find_one({"listing_id": listing["_id"], "status": BookingStatus.CONFIRMED.value}, {"_id": 1})
        reason = "Someone is renting here. You can delete the listing once their lease has ended."
    if blocker is not None:
        if not listing.get("suspended"):
            await db.listings.update_one(target, {"$unset": {"suspended": ""}})
        raise HTTPException(status.HTTP_409_CONFLICT, reason)

    if is_sale:
        await db.offers.update_many(
            {"listing_id": listing["_id"], "is_open": True},
            {
                "$set": {"status": OfferStatus.CLOSED.value, "is_open": False, "updated_at": now},
                "$push": {"history": {"at": now, "actor": "SYSTEM", "event": OfferEventType.CLOSED.value, "note": "The seller removed this listing"}},
            },
        )
    else:
        note = "The listing was removed; deposit to be refunded."
        for booking in await db.bookings.find({"listing_id": listing["_id"], "is_open": True}).to_list(None):
            cancelled = await db.bookings.update_one(
                {"_id": booking["_id"], "status": {"$in": [s.value for s in OPEN_BOOKING_STATUSES]}},
                {
                    "$set": {"status": BookingStatus.CANCELLED.value, "is_open": False, "qr": None, "escrow_status": EscrowStatus.REFUNDED.value, "updated_at": now},
                    "$push": {"escrow_ledger": {"at": now, "status": EscrowStatus.REFUNDED.value, "note": note}},
                },
            )
            qr = booking.get("qr") or {}
            if cancelled.modified_count and qr.get("nonce") and not qr.get("used_at"):
                await log_qr_event(booking, "REVOKED", qr["nonce"], "The listing was removed")
    await db.visit_slots.update_many(
        {"listing_id": listing["_id"], "status": "BOOKED", "starts_at": {"$gt": now}},
        {"$set": {"status": "CANCELLED", "cancelled_by": "ADMIN" if by_admin else "HOST", "cancelled_at": now}},
    )
    await db.listings.delete_one(target)
    await run_in_threadpool(shutil.rmtree, photo_folder(listing["_id"]), ignore_errors=True)


def photo_folder(listing_id: ObjectId) -> Path:
    return settings.upload_dir / "listing_photos" / str(listing_id)


def _photo_slot(listing: dict, room_id: str | None) -> tuple[list[dict], int, str, dict, list[dict] | None]:
    """Where photos go: on the listing itself, or on one of its sublet rooms.
    Returns (current photos, limit, update path, how to match that room, array filters)."""
    if room_id is None:
        return listing.get("photos", []), MAX_LISTING_PHOTOS, "photos", {}, None
    room = find_room(listing, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")
    return room.get("photos", []), MAX_ROOM_PHOTOS, "sublet.rooms.$[room].photos", {"id": room_id}, [{"room.id": room_id}]


async def add_listing_photos(listing: dict, owner_filter: dict, files: list[UploadFile], room_id: str | None = None) -> None:
    """Store new photos after the existing ones (the first photo is the cover), on the listing or on one of its rooms.
    At most MAX_LISTING_PHOTOS on a listing and MAX_ROOM_PHOTOS on a room."""
    photos, limit, path, room_match, array_filters = _photo_slot(listing, room_id)
    space = limit - len(photos)
    owner = "A listing" if room_id is None else "A room"
    if len(files) > space:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{owner} can have up to {limit} photos; {max(space, 0)} more fit")
    folder = photo_folder(listing["_id"])
    stored: list[dict] = []
    try:
        for upload in files:
            stored.append(await store_listing_photo(upload, folder))
    except HTTPException:
        await _remove_photo_files(folder, [photo["id"] for photo in stored])
        raise
    now = datetime.now(timezone.utc)
    # "photos.N doesn't exist" keeps the limit atomic when two uploads race.
    full = {f"photos.{limit - len(stored)}": {"$exists": False}}
    match = full if room_id is None else {"sublet.rooms": {"$elemMatch": {**room_match, **full}}}
    added = await get_db().listings.update_one(
        {"_id": listing["_id"], **owner_filter, **match},
        {"$push": {path: {"$each": [{**photo, "uploaded_at": now} for photo in stored]}}, "$set": {"updated_at": now}},
        array_filters=array_filters,
    )
    if added.matched_count == 0:
        await _remove_photo_files(folder, [photo["id"] for photo in stored])
        raise HTTPException(status.HTTP_409_CONFLICT, f"{owner} can have up to {limit} photos")


async def remove_listing_photo(listing: dict, owner_filter: dict, photo_id: str, room_id: str | None = None) -> None:
    _, _, path, room_match, array_filters = _photo_slot(listing, room_id)
    match = {"photos.id": photo_id} if room_id is None else {"sublet.rooms": {"$elemMatch": {**room_match, "photos.id": photo_id}}}
    removed = await get_db().listings.update_one(
        {"_id": listing["_id"], **owner_filter, **match},
        {"$pull": {path: {"id": photo_id}}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        array_filters=array_filters,
    )
    if removed.modified_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    await remove_photo_files(listing["_id"], [photo_id])


async def make_cover_photo(listing: dict, owner_filter: dict, photo_id: str) -> None:
    photos = listing.get("photos", [])
    chosen = next((photo for photo in photos if photo["id"] == photo_id), None)
    if chosen is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    reordered = [chosen, *(photo for photo in photos if photo["id"] != photo_id)]
    # Matching the order we read means a concurrent upload or delete isn't overwritten.
    changed = await get_db().listings.update_one(
        {"_id": listing["_id"], **owner_filter, "photos": photos},
        {"$set": {"photos": reordered, "updated_at": datetime.now(timezone.utc)}},
    )
    if changed.matched_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "The photos changed in the meantime. Reload and try again.")


def _all_photo_ids(listing: dict) -> set[str]:
    rooms = (listing.get("sublet") or {}).get("rooms") or []
    return {photo["id"] for photo in [*listing.get("photos", []), *(photo for room in rooms for photo in room.get("photos", []))]}


def listing_photo_response(listing: dict, photo_id: str, thumbnail: bool) -> FileResponse:
    """The listing's own photos and its sublet rooms' are served from the same path."""
    if photo_id not in _all_photo_ids(listing):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    full, thumb = listing_photo_paths(photo_folder(listing["_id"]), photo_id)
    return public_photo_response(thumb if thumbnail else full)


async def remove_photo_files(listing_id: ObjectId, photo_ids: list[str]) -> None:
    await _remove_photo_files(photo_folder(listing_id), photo_ids)


async def _remove_photo_files(folder: Path, photo_ids: list[str]) -> None:
    for photo_id in photo_ids:
        for path in listing_photo_paths(folder, photo_id):
            await run_in_threadpool(path.unlink, missing_ok=True)


# ---------------------------------------------------------------- the listing's one walkthrough video


async def set_listing_video(listing: dict, owner_filter: dict, upload: UploadFile) -> None:
    """Store the listing's video. A listing has one, so a new upload replaces the old."""
    folder = photo_folder(listing["_id"])
    video = await store_listing_video(upload, folder)
    now = datetime.now(timezone.utc)
    before = await get_db().listings.find_one_and_update(
        {"_id": listing["_id"], **owner_filter},
        {"$set": {"video": {**video, "uploaded_at": now}, "updated_at": now}},
        projection={"video": 1},
    )
    # The file that's no longer referenced: the old video, or the new one if the listing vanished meanwhile.
    orphan = video if before is None else before.get("video")
    if orphan:
        await run_in_threadpool(listing_video_path(folder, orphan["id"]).unlink, missing_ok=True)
    if before is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")


async def remove_listing_video(listing: dict, owner_filter: dict, video_id: str) -> None:
    removed = await get_db().listings.update_one(
        {"_id": listing["_id"], **owner_filter, "video.id": video_id},
        {"$set": {"video": None, "updated_at": datetime.now(timezone.utc)}},
    )
    if removed.modified_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    await run_in_threadpool(listing_video_path(photo_folder(listing["_id"]), video_id).unlink, missing_ok=True)


def listing_video_response(listing: dict, video_id: str) -> FileResponse:
    if (listing.get("video") or {}).get("id") != video_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return public_video_response(listing_video_path(photo_folder(listing["_id"]), video_id))


async def load_own_listing(listing_id: str, user: dict, mode_filter: dict) -> dict:
    listing = await get_db().listings.find_one({"_id": parse_object_id(listing_id), **mode_filter})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    if listing["lister_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only change your own listings")
    return listing
