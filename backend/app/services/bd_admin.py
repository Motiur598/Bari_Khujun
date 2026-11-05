"""Bangladesh's divisions, districts and upazilas/thanas, and which of them a point falls in.

The data (app/data/bd_admin.json.gz) is built from geoBoundaries' Bangladesh ADM1-ADM3 outlines, which come from the
Bangladesh Bureau of Statistics and OCHA ROAP (ADM1 CC0; ADM2 and ADM3 CC BY 3.0 IGO). Names use the current official
spellings (Chattogram, Barishal, Cumilla, Bogura, Jashore...); the older ones are kept as `aliases`.

Below the upazilas, app/data/bd_places.json.gz names towns, unions, neighbourhoods and villages for the map's labels
(built by app/scripts/build_place_names.py).
"""

import gzip
import json
import math
import re
from functools import cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "bd_admin.json.gz"
PLACES_FILE = DATA_FILE.with_name("bd_places.json.gz")
LEVELS = ("division", "district", "upazila")
# A pin in a gap between two simplified outlines (a river bank, the coast) still gets the nearest upazila.
NEAREST_UPAZILA_KM = 8


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def unit_id(division: str, district: str | None = None, upazila: str | None = None) -> str:
    return "/".join(slug(part) for part in (division, district, upazila) if part)


@cache
def admin_units() -> tuple[dict, ...]:
    """Every division, district and upazila: id, level, name, aliases, division, district, center, bbox, geometry."""
    return tuple(json.loads(gzip.decompress(DATA_FILE.read_bytes()))["units"])


@cache
def _units_by_id() -> dict[str, dict]:
    return {unit["id"]: unit for unit in admin_units()}


def find_unit(unit_id_: str) -> dict | None:
    return _units_by_id().get(unit_id_)


def _in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _contains(geometry: dict, x: float, y: float) -> bool:
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return any(_in_ring(x, y, poly[0]) and not any(_in_ring(x, y, hole) for hole in poly[1:]) for poly in polygons)


def _km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    return math.hypot((lng2 - lng1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)), (lat2 - lat1) * 110.57)


def locate(lng: float, lat: float, nearest_km: float = NEAREST_UPAZILA_KM) -> dict | None:
    """{division, district, upazila} for a point, or None when it isn't in Bangladesh. A point outside every outline
    takes the upazila whose centre is within `nearest_km` (0: only points inside an outline count)."""
    upazilas = [unit for unit in admin_units() if unit["level"] == "upazila"]
    for unit in upazilas:
        west, south, east, north = unit["bbox"]
        if west <= lng <= east and south <= lat <= north and _contains(unit["geometry"], lng, lat):
            return {"division": unit["division"], "district": unit["district"], "upazila": unit["name"]}
    nearest = min(upazilas, key=lambda unit: _km(lng, lat, *unit["center"]))
    if _km(lng, lat, *nearest["center"]) <= nearest_km:
        return {"division": nearest["division"], "district": nearest["district"], "upazila": nearest["name"]}
    return None


def with_admin_area(location: dict) -> dict:
    """A listing's location plus the division, district and upazila its pin is in (server-owned, never from the client)."""
    lng, lat = location["geo"]["coordinates"]
    return {**location, **(locate(lng, lat) or {"division": None, "district": None, "upazila": None})}
