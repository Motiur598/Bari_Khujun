"""Build app/data/bd_places.json.gz: English names for the map below the upazila/thana level.

The frontend draws these over the base map (PlaceLabels), so every part of Bangladesh has local names when zoomed in,
not just Dhaka city, whose neighbourhoods the Esri map already names (so it gets none of these: they would crowd it).

- Union councils: geoBoundaries' Bangladesh ADM4 (from BBS and OCHA ROAP, CC BY 3.0 IGO). City wards ("Ward No-12")
  and municipalities ("Jessore Paurashava") are left out: those names don't tell anyone where they are.
- Towns, suburbs, quarters, neighbourhoods, villages and hamlets: OpenStreetMap (ODbL) through the Overpass API, where
  they have an English or Latin-script name.

A place is kept only inside a Bangladesh upazila, a name repeated within 2 km is kept once, and a place named like the
upazila it is in is dropped (the upazila label already says it). Names are compared without their vowels, so spelling
variants ("Bogra" and "Bogura", "Halishahar" and "HaliShohor") count as the same name.

Run from backend/ (downloads about 15 MB; the public Overpass servers are sometimes busy, so it retries):
    python -m app.scripts.build_place_names
    python -m app.scripts.build_place_names --unions adm4.geojson --osm overpass.json   # from saved downloads
"""

import argparse
import gzip
import json
import math
import re
import time
import unicodedata
import urllib.parse
import urllib.request

from app.services.bd_admin import PLACES_FILE, locate

UNIONS_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/BGD/ADM4/geoBoundaries-BGD-ADM4_simplified.geojson"
)
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
OSM_KINDS = "city|town|suburb|quarter|neighbourhood|village|hamlet"
# Nodes need their coordinates; ways and relations only a centre. The box is Bangladesh plus its borderlands.
OVERPASS_QUERY = f"""[out:json][timeout:240][bbox:20.5,88.0,26.7,92.7];
node["place"~"^({OSM_KINDS})$"];out qt;
(way["place"~"^({OSM_KINDS})$"];relation["place"~"^({OSM_KINDS})$"];);out tags center qt;"""
USER_AGENT = "BariKhujun-place-names/1.0"

# The map names rank 1 from zoom 10, 2 from 11, 3 from 12 and 4 from 14.
RANKS = {"city": 1, "town": 1, "union": 2, "suburb": 2, "quarter": 2, "neighbourhood": 3, "village": 3, "hamlet": 4}
SAME_PLACE_KM = 2
MAX_NAME = 28
LATIN = re.compile(r"^[\x20-\x7eÀ-ɏ]+$")
NOT_A_PLACE = re.compile(r"\bward\b|paurashava|pourashava|municipality|corporation", re.IGNORECASE)
# "Block F" or "Sector 13" only means something close in, next to the estate's own name.
ESTATE_PART = re.compile(r"^(block|sector|section|road|lane)\s*[-\w]{1,3}$", re.IGNORECASE)
# Dhaka district's upazilas outside the city; the rest are city thanas, which the Esri map names in detail.
DHAKA_OUTSIDE_CITY = {"Dhamrai", "Dohar", "Keraniganj", "Nawabganj", "Savar"}
ATTRIBUTION = "Unions: geoBoundaries BGD ADM4 (BBS, OCHA ROAP; CC BY 3.0 IGO). Other places: (c) OpenStreetMap contributors (ODbL)."


def fetch(url: str, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def download_osm() -> dict:
    body = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode()
    for attempt in range(5):
        for url in OVERPASS_URLS:
            try:
                result = json.loads(fetch(url, body))
                if result.get("elements"):
                    return result
                print(f"{url}: no places ({result.get('remark', 'empty answer')})")
            except (OSError, ValueError) as err:  # busy servers answer 502/504 or an HTML page
                print(f"{url}: {err}")
        time.sleep(15 * 2**attempt)
    raise SystemExit("The Overpass servers are busy. Try again later.")


def clean(name: str | None) -> str | None:
    """A label-ready name, or None for one that is missing, too long, not in Latin script or not a place."""
    if not name or not LATIN.match(name):
        return None
    # "Tushbandar;Tushbhandar" and "Bainna Para / Kader Para" are alternatives: the first is enough for a label.
    name = " ".join(name.split(";")[0].split(" / ")[0].split())
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()  # "Nalām" becomes "Nalam"
    name = re.sub(r"\s*\(part\)$|\s+U/C$", "", name, flags=re.IGNORECASE)
    if not name or len(name) > MAX_NAME or "," in name or '"' in name or NOT_A_PLACE.search(name):
        return None
    # "Babu bazar" becomes "Babu Bazar"; mixed case ("SagorPara") is left alone.
    return " ".join(word[:1].upper() + word[1:] if word.islower() else word for word in name.split())


def label_point(geometry: dict) -> tuple[float, float]:
    """The centroid of the largest outer ring, to hang a union's name on."""
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    best_area, best_point = -1.0, (0.0, 0.0)
    for polygon in polygons:
        ring = polygon[0]
        area = cx = cy = 0.0
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            cross = x1 * y2 - x2 * y1
            area += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        if area and abs(area) > best_area:
            best_area, best_point = abs(area), (cx / (3 * area), cy / (3 * area))
    return best_point


def candidates(unions: dict, osm: dict):
    """(name, lng, lat, rank) for every union and named OSM place, before filtering."""
    for feature in unions["features"]:
        yield feature["properties"]["shapeName"], *label_point(feature["geometry"]), RANKS["union"]
    for element in osm["elements"]:
        tags = element.get("tags", {})
        point = element.get("center") or element
        if "lat" in point and tags.get("place") in RANKS:
            yield tags.get("name:en") or tags.get("name"), point["lon"], point["lat"], RANKS[tags["place"]]


def km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    return math.hypot((lng2 - lng1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)), (lat2 - lat1) * 110.57)


def spelling_key(name: str) -> str:
    """The name without vowels, h, w, y or doubled letters, so transliterations of one Bengali name match."""
    plain = re.sub(r"[^a-z0-9]", "", name.lower())
    key = re.sub(r"(.)\1+", r"\1", re.sub(r"[aeiouhwy]", "", plain))
    return key if len(key) >= 2 else plain


def build(unions: dict, osm: dict) -> list[list]:
    rows, seen = [], {}
    for raw_name, lng, lat, rank in sorted(candidates(unions, osm), key=lambda place: place[3]):
        name = clean(raw_name)
        if not name:
            continue
        key = spelling_key(name)
        if any(km(lng, lat, *other) < SAME_PLACE_KM for other in seen.get(key, ())):
            continue
        where = locate(lng, lat, nearest_km=0)
        if where is None or (where["district"] == "Dhaka" and where["upazila"] not in DHAKA_OUTSIDE_CITY):
            continue
        upazila = where["upazila"].removesuffix(" Sadar")
        if key == spelling_key(upazila):
            continue
        seen.setdefault(key, []).append((lng, lat))
        rows.append([name, round(lng, 5), round(lat, 5), 4 if ESTATE_PART.match(name) else rank])
    return sorted(rows, key=lambda row: (row[3], row[0]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unions", help="a saved copy of the geoBoundaries ADM4 GeoJSON (else it is downloaded)")
    parser.add_argument("--osm", help="a saved Overpass JSON answer to this script's query (else it is downloaded)")
    args = parser.parse_args()

    unions = json.load(open(args.unions, encoding="utf-8")) if args.unions else json.loads(fetch(UNIONS_URL))
    osm = json.load(open(args.osm, encoding="utf-8")) if args.osm else download_osm()
    rows = build(unions, osm)
    payload = json.dumps({"attribution": ATTRIBUTION, "places": rows}, ensure_ascii=False, separators=(",", ":"))
    PLACES_FILE.write_bytes(gzip.compress(payload.encode(), mtime=0))
    by_rank = {rank: sum(1 for row in rows if row[3] == rank) for rank in sorted(set(RANKS.values()))}
    print(f"Wrote {len(rows)} places to {PLACES_FILE} ({PLACES_FILE.stat().st_size // 1024} KB), by rank: {by_rank}")


if __name__ == "__main__":
    main()
