"""Target-area search: listings carry `location.{city, area_name, sub_area, formatted_address, geo}`, and a search with
an area name and/or a point + radius returns only what is inside that area."""

import pytest
from support import Factory, location, rental_payload

from app.core.database import migrate_listing_locations

pytestmark = pytest.mark.anyio

# Sylhet listings sit far from every other test's listings (all in Dhaka), so radius results are exact.
ZINDABAZAR = (91.8687, 24.8949)


@pytest.fixture(scope="module")
def make(client, db):
    # Module-scoped twin of conftest's `make`, so `world` is built once for the whole module.
    return Factory(client, db)


@pytest.fixture(scope="module")
async def world(make):
    owner = await make.account("OWNER")
    for area, sub_area, lng, lat, rent in [
        ("Mirpur", "Mirpur 10", 90.3687, 23.8069, 15000),
        ("Mirpur", "Mirpur 2", 90.3610, 23.8055, 12000),
        ("Mirpurpara", None, 90.3530, 23.7950, 9000),  # starts with "Mirpur" but is another place
        ("Uttara", "Sector 7", 90.3984, 23.8728, 30000),
        ("Merul Badda", None, 90.4285, 23.7720, 14000),
        ("Zindabazar", None, *ZINDABAZAR, 20000),
        ("Zindabazar", "Dargah Gate", 91.8740, 24.8960, 10000),  # about 0.55 km east
        ("Amberkhana", None, 91.8680, 24.9175, 8000),  # about 2.5 km north
    ]:
        await make.flat_listing(owner, area, lng, lat, sub_area=sub_area, rent=rent)
    await make.sale_listing(owner, "Mirpur", 90.3690, 23.8072)
    await make.sale_listing(owner, "Zindabazar", 91.8690, 24.8952)
    return {"owner": owner}


def place_of(item: dict) -> str:
    sub_area = item["location"]["sub_area"]
    return item["location"]["area_name"] + (f" / {sub_area}" if sub_area else "")


async def search(client, path: str, **params) -> dict:
    response = await client.get(path, params={"limit": 100, **params})
    assert response.status_code == 200, response.text
    return response.json()


async def places(client, path: str, **params) -> list[str]:
    return sorted(place_of(item) for item in (await search(client, path, **params))["items"])


class TestAreaNameFilter:
    async def test_matches_the_area_in_any_case(self, client, world):
        assert await places(client, "/rentals", area_name="mirpur") == ["Mirpur / Mirpur 10", "Mirpur / Mirpur 2"]
        assert await places(client, "/rentals", area_name="MIRPUR") == ["Mirpur / Mirpur 10", "Mirpur / Mirpur 2"]
        assert await places(client, "/rentals", area_name="Uttara") == ["Uttara / Sector 7"]

    async def test_matches_whole_words_only(self, client, world):
        # "Badda" covers Merul Badda; "Mirpur" doesn't leak into Mirpurpara.
        assert await places(client, "/rentals", area_name="badda") == ["Merul Badda"]
        assert "Mirpurpara" not in await places(client, "/rentals", area_name="Mirpur")

    async def test_only_the_area_name_is_matched(self, client, world):
        # Strict area filter: a sub-area or street name is not an area.
        assert await places(client, "/rentals", area_name="Sector 7") == []
        assert await places(client, "/rentals", area_name="Mirpur 10") == []

    @pytest.mark.parametrize("pattern", [".*", "Mirpur.*", "Mirpur (", "[a-z]+"])
    async def test_area_name_is_text_not_a_regex(self, client, world, pattern):
        assert await places(client, "/rentals", area_name=pattern) == []

    async def test_echoes_the_target_area(self, client, world):
        body = await search(client, "/rentals", area_name="Mirpur")
        assert (body["area_name"], body["center"], body["radius_km"]) == ("Mirpur", None, None)


class TestRadiusFilter:
    async def test_only_listings_inside_the_circle_nearest_first(self, client, world):
        lng, lat = ZINDABAZAR
        body = await search(client, "/rentals", lat=lat, lng=lng, radius_km=1)
        assert [place_of(item) for item in body["items"]] == ["Zindabazar", "Zindabazar / Dargah Gate"]
        assert body["items"][0]["distance_km"] == 0 and 0.5 < body["items"][1]["distance_km"] <= 1
        assert (body["total"], body["radius_km"], body["center"]["lat"], body["center"]["lng"]) == (2, 1, lat, lng)

    async def test_radius_defaults_to_2_km(self, client, world):
        lng, lat = ZINDABAZAR
        body = await search(client, "/rentals", lat=lat, lng=lng)
        assert body["radius_km"] == 2
        assert "Amberkhana" not in [place_of(item) for item in body["items"]]  # 2.5 km away
        assert "Amberkhana" in await places(client, "/rentals", lat=lat, lng=lng, radius_km=3)

    async def test_another_sort_reorders_inside_the_circle(self, client, world):
        lng, lat = ZINDABAZAR
        body = await search(client, "/rentals", lat=lat, lng=lng, radius_km=3, sort="rent_asc")
        assert [item["effective_rent"] for item in body["items"]] == [8000, 10000, 20000]

    async def test_total_counts_the_whole_circle(self, client, world):
        lng, lat = ZINDABAZAR
        body = await search(client, "/rentals", lat=lat, lng=lng, radius_km=3, limit=1)
        assert (len(body["items"]), body["total"], place_of(body["items"][0])) == (1, 3, "Zindabazar")

    async def test_area_and_radius_must_both_match(self, client, world):
        lng, lat = ZINDABAZAR
        assert await places(client, "/rentals", area_name="Amberkhana", lat=lat, lng=lng, radius_km=1) == []
        assert await places(client, "/rentals", area_name="Amberkhana", lat=lat, lng=lng, radius_km=3) == ["Amberkhana"]

    async def test_lat_without_lng_is_rejected(self, client):
        assert (await client.get("/rentals", params={"lat": 23.8})).status_code == 422


class TestSaleSearch:
    async def test_sale_search_filters_by_area_and_radius(self, client, world):
        assert await places(client, "/marketplace/sale-listings", area_name="mirpur") == ["Mirpur"]
        lng, lat = ZINDABAZAR
        assert await places(client, "/marketplace/sale-listings", lat=lat, lng=lng, radius_km=1) == ["Zindabazar"]


class TestSearchPaths:
    @pytest.mark.parametrize("base, alias", [("/rentals", "/rentals/search"), ("/marketplace/sale-listings", "/marketplace/search")])
    async def test_search_paths_return_the_same_results(self, client, world, base, alias):
        lng, lat = ZINDABAZAR
        for params in ({"area_name": "Mirpur"}, {"lat": lat, "lng": lng, "radius_km": 3}):
            assert await search(client, alias, **params) == await search(client, base, **params)


class TestAreasEndpoint:
    async def test_popular_areas_count_whole_word_matches(self, client, world):
        areas = {area["name"]: area for area in (await client.get("/rentals/areas")).json()}
        assert (areas["Mirpur"]["popular"], areas["Mirpur"]["rentals"], areas["Mirpur"]["sales"]) == (True, 2, 1)
        assert (areas["Uttara"]["rentals"], areas["Badda"]["rentals"]) == (1, 1)
        # Popular areas are listed even with nothing in them; they carry a centre and radius for the map.
        assert areas["Gulshan"]["popular"] and areas["Gulshan"]["radius_km"] > 0
        # Other names are listed on their own, centred on their listings; "Merul Badda" is counted under Badda.
        zinda = areas["Zindabazar"]
        assert (zinda["popular"], zinda["rentals"], zinda["sales"]) == (False, 2, 1)
        assert abs(zinda["lng"] - 91.87057) < 0.001 and abs(zinda["lat"] - 24.89537) < 0.001
        assert areas["Mirpurpara"]["popular"] is False
        assert "Merul Badda" not in areas


class TestListingLocation:
    async def test_location_is_stored_in_the_new_shape(self, client, world, db):
        listing = await db.listings.find_one({"location.area_name": "Uttara"})
        assert set(listing["location"]) == {"city", "area_name", "sub_area", "formatted_address", "geo", "division", "district", "upazila"}
        assert (listing["location"]["division"], listing["location"]["district"], listing["location"]["upazila"]) == ("Dhaka", "Dhaka", "Uttara")
        assert (listing["location"]["sub_area"], listing["location"]["geo"]) == (
            "Sector 7",
            {"type": "Point", "coordinates": [90.3984, 23.8728]},
        )
        assert "address" not in listing

    async def test_a_blank_sub_area_is_stored_as_none(self, client, world, db):
        payload = rental_payload(category="FAMILY_FLAT", place=location("Khilgaon", 90.4250, 23.7517, sub_area=""))
        response = await client.post("/rentals", json=payload, headers=world["owner"].auth)
        assert (response.status_code, response.json()["location"]["sub_area"]) == (201, None)

    async def test_listings_in_the_old_shape_are_moved_at_startup(self, client, db):
        old = {
            "listing_mode": "RENT",
            "title": "Listing saved before the upgrade",
            "address": {"line": "Road 5, Block C", "area": "Banani", "city": "Dhaka"},
            "location": {"type": "Point", "coordinates": [90.4043, 23.7937]},
        }
        inserted = await db.listings.insert_one(old)

        assert await migrate_listing_locations(db) == 1
        assert await migrate_listing_locations(db) == 0  # nothing left to move
        moved = await db.listings.find_one({"_id": inserted.inserted_id})
        await db.listings.delete_one({"_id": inserted.inserted_id})
        assert "address" not in moved
        assert moved["location"] == {
            "city": "Dhaka",
            "area_name": "Banani",
            "formatted_address": "Road 5, Block C",
            "geo": {"type": "Point", "coordinates": [90.4043, 23.7937]},
        }

    async def test_startup_indexes(self, db):
        keys = [index["key"] for index in (await db.listings.index_information()).values()]
        assert [("location.geo", "2dsphere")] in keys
        assert [("location.area_name", 1)] in keys
        assert "location_2dsphere" not in await db.listings.index_information()

    @pytest.mark.parametrize(
        "place",
        [
            {**location(), "geo": {"type": "Point", "coordinates": [0, 0]}},
            {**location(), "geo": {"type": "Point", "coordinates": [23.75, 90.40]}},
            {key: value for key, value in location().items() if key != "area_name"},
            {"type": "Point", "coordinates": [90.3855, 23.7275]},
        ],
        ids=["null-island", "swapped-lat-lng", "no-area-name", "old-bare-geojson"],
    )
    async def test_bad_locations_are_rejected(self, client, world, place):
        payload = rental_payload(category="FAMILY_FLAT", place=place)
        assert (await client.post("/rentals", json=payload, headers=world["owner"].auth)).status_code == 422

    async def test_old_address_field_is_rejected(self, client, world):
        payload = {**rental_payload(category="FAMILY_FLAT"), "address": {"line": "Road 1", "area": "Azimpur", "city": "Dhaka"}}
        assert (await client.post("/rentals", json=payload, headers=world["owner"].auth)).status_code == 422

    async def test_the_same_payload_with_a_valid_location_is_accepted(self, client, world):
        # Control for the two tests above: only the location makes them fail.
        payload = rental_payload(category="FAMILY_FLAT", place=location("Azimpur"))
        assert (await client.post("/rentals", json=payload, headers=world["owner"].auth)).status_code == 201
