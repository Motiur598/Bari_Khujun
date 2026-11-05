"""Bangladesh's divisions, districts and upazilas/thanas: the step-by-step location filter and the map's labels."""

import gzip
from functools import cache
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse, Response

from app.core.database import get_db
from app.services.bd_admin import PLACES_FILE, admin_units, find_unit, locate, unit_id
from app.services.listings import OPEN_RENTALS, SALE_ONLY

router = APIRouter(prefix="/api/locations", tags=["locations"])

# The place list and outlines only change with a new data file, so browsers may keep them for a while.
LIST_CACHE = {"Cache-Control": "public, max-age=3600"}
BOUNDARY_CACHE = {"Cache-Control": "public, max-age=86400"}
UNIT_ID_PATTERN = r"^[a-z0-9-]+(/[a-z0-9-]+){0,2}$"


@cache
def _unit_list() -> list[dict]:
    return [{key: value for key, value in unit.items() if key != "geometry"} for unit in admin_units()]


@cache
def _local_places_gzip() -> bytes:
    return PLACES_FILE.read_bytes()


@router.get("")
async def list_locations():
    """Every division, district and upazila/thana without its outline: id, level, name, aliases (older spellings),
    division and district it belongs to, a label point [lng, lat] and a bounding box [west, south, east, north]."""
    return JSONResponse(_unit_list(), headers=LIST_CACHE)


@router.get("/places")
async def list_local_places(request: Request):
    """Towns, unions, neighbourhoods and villages for the map's labels below the upazila level:
    {"attribution", "places": [[name, lng, lat, rank], ...]}, rank 1 (towns) to 4 (hamlets). The file is stored
    gzipped, so it is sent as it is (about 100 KB) to clients that accept gzip."""
    headers = {**LIST_CACHE, "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        return Response(_local_places_gzip(), media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(gzip.decompress(_local_places_gzip()), media_type="application/json", headers=headers)


@router.get("/counts")
async def location_counts(mode: Annotated[Literal["rent", "sale"], Query()] = "rent"):
    """How many listings a tenant (rent) or buyer (sale) could take in each division, district and upazila, by id."""
    rows = await get_db().listings.aggregate(
        [
            {"$match": {**(OPEN_RENTALS if mode == "rent" else SALE_ONLY), "location.division": {"$ne": None}}},
            {"$group": {"_id": ["$location.division", "$location.district", "$location.upazila"], "n": {"$sum": 1}}},
        ]
    ).to_list(None)
    counts: dict[str, int] = {}
    for row in rows:
        division, district, upazila = row["_id"]
        for key in {unit_id(division), unit_id(division, district), unit_id(division, district, upazila)}:
            counts[key] = counts.get(key, 0) + row["n"]
    return counts


@router.get("/at")
async def locate_point(
    lat: Annotated[float, Query(ge=20, le=27)],
    lng: Annotated[float, Query(ge=87, le=93)],
):
    """The division, district and upazila/thana a point is in."""
    place = locate(lng, lat)
    if place is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That spot isn't inside Bangladesh")
    return {**place, "id": unit_id(place["division"], place["district"], place["upazila"])}


@router.get("/boundary/{location_id:path}")
async def location_boundary(location_id: Annotated[str, Path(pattern=UNIT_ID_PATTERN)]):
    """A place's outline as a GeoJSON Feature, for drawing on the map."""
    unit = find_unit(location_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Place not found")
    feature = {"type": "Feature", "properties": {"id": unit["id"], "name": unit["name"], "level": unit["level"]}, "geometry": unit["geometry"]}
    return JSONResponse(feature, headers=BOUNDARY_CACHE)
