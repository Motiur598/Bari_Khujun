"""Bangladesh-wide locations: every listing gets its division, district and upazila from its pin, and searches can be
narrowed by them."""

import pytest
from bson import ObjectId
from support import Factory, location, rental_payload

from app.services.bd_admin import admin_units, locate
from app.services.listings import backfill_admin_areas

pytestmark = pytest.mark.anyio

RAJSHAHI_UNIVERSITY = (88.6400, 24.3690)  # Matihar thana, Rajshahi
UPOSHOHOR = (88.6180, 24.3740)  # Boalia thana, Rajshahi
GEC_CIRCLE = (91.8210, 22.3590)  # Chattogram


@pytest.fixture(scope="module")
def make(client, db):
    return Factory(client, db)


@pytest.fixture(scope="module")
async def nationwide(make):
    owner = await make.account("OWNER")
    ids = {
        "binodpur": await make.flat_listing(owner, "Binodpur", *RAJSHAHI_UNIVERSITY),
        "uposhohor": await make.flat_listing(owner, "Uposhohor", *UPOSHOHOR),
        "gec": await make.flat_listing(owner, "GEC Circle", *GEC_CIRCLE),
        "rajshahi_sale": await make.sale_listing(owner, "Uposhohor", 88.6185, 24.3745),
    }
    return {"owner": owner, **ids}


class TestLocate:
    @pytest.mark.parametrize(
        "point, expected",
        [
            ((90.3984, 23.8728), ("Dhaka", "Dhaka", "Uttara")),
            (RAJSHAHI_UNIVERSITY, ("Rajshahi", "Rajshahi", "Matihar")),
            (UPOSHOHOR, ("Rajshahi", "Rajshahi", "Boalia")),
            ((91.8690, 24.8960), ("Sylhet", "Sylhet", "Sylhet Sadar")),
        ],
        ids=["uttara", "rajshahi-university", "uposhohor", "zindabazar"],
    )
    def test_points_land_in_the_right_upazila(self, point, expected):
        place = locate(*point)
        assert (place["division"], place["district"], place["upazila"]) == expected

    @pytest.mark.parametrize("point", [(90.5, 21.0), (88.36, 22.57)], ids=["bay-of-bengal", "kolkata"])
    def test_points_outside_bangladesh_have_no_place(self, point):
        assert locate(*point) is None

    def test_the_data_has_every_unit_with_modern_names(self):
        levels = [unit["level"] for unit in admin_units()]
        assert (levels.count("division"), levels.count("district"), levels.count("upazila")) == (8, 64, 544)
        chattogram = next(unit for unit in admin_units() if unit["id"] == "chattogram")
        assert "Chittagong" in chattogram["aliases"]


class TestListings:
    async def test_a_listing_gets_its_division_district_and_upazila(self, client, nationwide):
        listing = (await client.get(f"/rentals/{nationwide['binodpur']}")).json()
        location = listing["location"]
        assert (location["division"], location["district"], location["upazila"]) == ("Rajshahi", "Rajshahi", "Matihar")

    async def test_the_client_cannot_set_them(self, client, nationwide):
        place = {**location("Binodpur", *RAJSHAHI_UNIVERSITY), "district": "Dhaka"}
        payload = rental_payload(category="FAMILY_FLAT", place=place)
        assert (await client.post("/rentals", json=payload, headers=nationwide["owner"].auth)).status_code == 422

    async def test_old_listings_are_backfilled(self, client, nationwide, db):
        await db.listings.update_one({"_id": ObjectId(nationwide["gec"])}, {"$unset": {"location.district": "", "location.division": "", "location.upazila": ""}})
        assert await backfill_admin_areas() >= 1
        stored = (await db.listings.find_one({"_id": ObjectId(nationwide["gec"])}))["location"]
        assert (stored["division"], stored["district"]) == ("Chattogram", "Chattogram")


class TestRegionSearch:
    async def ids(self, client, path, **params):
        response = await client.get(path, params={"limit": 100, **params})
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()["items"]}

    async def test_division_district_and_upazila_narrow_the_search(self, client, nationwide):
        in_division = await self.ids(client, "/rentals", division="Rajshahi")
        assert {nationwide["binodpur"], nationwide["uposhohor"]} <= in_division and nationwide["gec"] not in in_division
        assert await self.ids(client, "/rentals", division="Rajshahi", district="Rajshahi", upazila="Boalia") == {nationwide["uposhohor"]}
        assert nationwide["gec"] in await self.ids(client, "/rentals", district="chattogram")  # any case
        assert await self.ids(client, "/rentals", district="Rajsh") == set()  # whole names only

    async def test_region_and_area_name_combine(self, client, nationwide):
        assert await self.ids(client, "/rentals", district="Rajshahi", area_name="Uposhohor") == {nationwide["uposhohor"]}
        assert await self.ids(client, "/rentals", district="Chattogram", area_name="Uposhohor") == set()

    async def test_sales_too(self, client, nationwide):
        assert nationwide["rajshahi_sale"] in await self.ids(client, "/marketplace/sale-listings", district="Rajshahi")

    async def test_areas_within_a_district(self, client, nationwide):
        areas = (await client.get("/rentals/areas", params={"district": "Rajshahi"})).json()
        assert {area["name"] for area in areas} == {"Binodpur", "Uposhohor"}
        assert all(not area["popular"] for area in areas)


class TestLocationsApi:
    async def test_the_place_list(self, client):
        response = await client.get("/locations")
        units = response.json()
        assert len(units) == 616 and "geometry" not in units[0]
        assert response.headers["cache-control"] == "public, max-age=3600"
        paba = next(unit for unit in units if unit["id"] == "rajshahi/rajshahi/paba")
        assert (paba["level"], paba["division"], paba["district"]) == ("upazila", "Rajshahi", "Rajshahi")

    async def test_local_places_for_the_map(self, client):
        response = await client.get("/locations/places")
        assert response.headers["content-encoding"] == "gzip" and response.headers["cache-control"] == "public, max-age=3600"
        places = response.json()["places"]
        assert len(places) > 5000
        names = {name for name, _lng, _lat, _rank in places}
        assert {"Agrabad", "Tilagar", "Talaimari"} <= names  # Chattogram, Sylhet and Rajshahi neighbourhoods
        assert not any("Ward No" in name or "Paurashava" in name for name in names)
        assert all(locate(lng, lat) and rank in (1, 2, 3, 4) for _name, lng, lat, rank in places[:200])

    async def test_local_places_without_gzip(self, client):
        response = await client.get("/locations/places", headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in response.headers and len(response.json()["places"]) > 5000

    async def test_counts(self, client, nationwide):
        counts = (await client.get("/locations/counts", params={"mode": "rent"})).json()
        assert counts["rajshahi/rajshahi/matihar"] >= 1 and counts["rajshahi"] >= 2
        sale_counts = (await client.get("/locations/counts", params={"mode": "sale"})).json()
        assert sale_counts["rajshahi/rajshahi/boalia"] >= 1

    async def test_point_lookup(self, client):
        found = await client.get("/locations/at", params={"lat": RAJSHAHI_UNIVERSITY[1], "lng": RAJSHAHI_UNIVERSITY[0]})
        assert found.json() == {"division": "Rajshahi", "district": "Rajshahi", "upazila": "Matihar", "id": "rajshahi/rajshahi/matihar"}
        assert (await client.get("/locations/at", params={"lat": 21.0, "lng": 90.5})).status_code == 404

    async def test_boundaries(self, client):
        feature = (await client.get("/locations/boundary/rajshahi/rajshahi")).json()
        assert feature["type"] == "Feature" and feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert (await client.get("/locations/boundary/nowhere/at-all")).status_code == 404
        assert (await client.get("/locations/boundary/Rajshahi%20Division")).status_code == 422
