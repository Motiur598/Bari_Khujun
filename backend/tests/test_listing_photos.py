"""Listing photos: uploaded by the lister, re-encoded (upright, no metadata, resized), served publicly and cached."""

import io

import pytest
from bson import ObjectId
from PIL import Image
from support import jpeg_bytes

from app.services.listings import MAX_LISTING_PHOTOS, photo_folder

pytestmark = pytest.mark.anyio


def image_bytes(size=(800, 600), fmt="JPEG", mode="RGB", exif=None) -> bytes:
    buffer = io.BytesIO()
    image = Image.new(mode, size, (180, 140, 100, 128) if mode == "RGBA" else (180, 140, 100))
    image.save(buffer, fmt, **({"exif": exif} if exif else {}))
    return buffer.getvalue()


def gps_exif() -> bytes:
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (23.0, 52.0, 22.0), 3: "E", 4: (90.0, 23.0, 54.0)}  # GPSInfo
    exif[0x0110] = "Owner's phone"  # camera model
    return exif.tobytes()


async def upload(client, account, listing_id, *files, base="/rentals"):
    return await client.post(
        f"{base}/{listing_id}/photos", files=[("files", (name, content, "image/jpeg")) for name, content in files], headers=account.auth
    )


class TestUpload:
    async def test_photos_are_re_encoded_resized_and_stripped(self, client, make, db):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        big = image_bytes((3000, 2000), exif=gps_exif())

        response = await upload(client, owner, listing_id, ("room.jpg", big), ("alpha.png", image_bytes(fmt="PNG", mode="RGBA")))

        assert response.status_code == 200, response.text
        photos = response.json()["photos"]
        assert [(p["width"], p["height"]) for p in photos] == [(1600, 1067), (800, 600)]
        stored = Image.open(photo_folder(listing_id) / f"{photos[0]['id']}.jpg")
        assert stored.format == "JPEG" and not stored.getexif()  # GPS and camera details are gone
        thumb = Image.open(photo_folder(listing_id) / f"{photos[0]['id']}_thumb.jpg")
        assert max(thumb.size) == 640

    async def test_webp_from_a_phone_is_accepted(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        response = await upload(client, owner, listing_id, ("room.webp", image_bytes(fmt="WEBP")))
        assert response.status_code == 200 and len(response.json()["photos"]) == 1

    @pytest.mark.parametrize(
        "name, content",
        [("shell.jpg", b"<?php echo 'probe'; ?>"), ("doc.jpg", b"%PDF-1.4\n%%EOF"), ("empty.jpg", b"")],
        ids=["script", "pdf", "empty"],
    )
    async def test_non_images_are_rejected_and_nothing_is_kept(self, client, make, db, name, content):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        response = await upload(client, owner, listing_id, ("good.jpg", jpeg_bytes()), (name, content))
        assert response.status_code == 400
        assert (await db.listings.find_one({"_id": ObjectId(listing_id)})).get("photos", []) == []
        folder = photo_folder(listing_id)
        assert not folder.exists() or not any(folder.iterdir())  # the good photo was cleaned up too

    async def test_huge_resolution_is_refused(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        bomb = image_bytes((8000, 6000), fmt="PNG")  # 48 megapixels in a small file
        response = await upload(client, owner, listing_id, ("bomb.png", bomb))
        assert response.status_code == 400

    async def test_at_most_ten_photos(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        many = [(f"{i}.jpg", jpeg_bytes()) for i in range(MAX_LISTING_PHOTOS)]
        assert (await upload(client, owner, listing_id, *many)).status_code == 200
        assert (await upload(client, owner, listing_id, ("one-more.jpg", jpeg_bytes()))).status_code == 400

    async def test_only_the_lister_can_change_photos(self, client, make):
        owner, stranger = await make.account("OWNER"), await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        photo_id = (await upload(client, owner, listing_id, ("a.jpg", jpeg_bytes()))).json()["photos"][0]["id"]

        assert (await upload(client, stranger, listing_id, ("b.jpg", jpeg_bytes()))).status_code == 403
        assert (await client.delete(f"/rentals/{listing_id}/photos/{photo_id}", headers=stranger.auth)).status_code == 403
        assert (await client.post(f"/rentals/{listing_id}/photos", files=[("files", ("c.jpg", jpeg_bytes(), "image/jpeg"))])).status_code == 401


class TestServing:
    async def test_photos_are_public_and_cacheable(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        photo_id = (await upload(client, owner, listing_id, ("a.jpg", image_bytes((1200, 900))))).json()["photos"][0]["id"]

        full = await client.get(f"/rentals/{listing_id}/photos/{photo_id}")
        thumb = await client.get(f"/rentals/{listing_id}/photos/{photo_id}", params={"size": "thumb"})

        assert (full.status_code, full.headers["content-type"], full.headers["cache-control"]) == (
            200, "image/jpeg", "public, max-age=31536000, immutable",
        )
        assert Image.open(io.BytesIO(full.content)).size == (1200, 900)
        assert Image.open(io.BytesIO(thumb.content)).size == (640, 480)
        assert full.headers["x-content-type-options"] == "nosniff"

    async def test_unknown_and_malformed_photo_ids(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        assert (await client.get(f"/rentals/{listing_id}/photos/{'a' * 32}")).status_code == 404
        assert (await client.get(f"/rentals/{listing_id}/photos/..%2F..%2Fsecret")).status_code in (404, 422)
        assert (await client.get(f"/rentals/{listing_id}/photos/not-a-photo-id")).status_code == 422

    async def test_api_json_is_still_not_cached(self, client):
        response = await client.get("/rentals/landmarks")
        assert response.headers["cache-control"] == "no-store"


class TestManaging:
    async def test_cover_delete_and_cleanup(self, client, make, db):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner)
        photos = (await upload(client, owner, listing_id, ("a.jpg", jpeg_bytes()), ("b.jpg", jpeg_bytes()))).json()["photos"]
        first, second = photos[0]["id"], photos[1]["id"]

        covered = await client.post(f"/rentals/{listing_id}/photos/{second}/cover", headers=owner.auth)
        assert [p["id"] for p in covered.json()["photos"]] == [second, first]

        deleted = await client.delete(f"/rentals/{listing_id}/photos/{second}", headers=owner.auth)
        assert [p["id"] for p in deleted.json()["photos"]] == [first]
        assert not (photo_folder(listing_id) / f"{second}.jpg").exists()

        assert (await client.delete(f"/rentals/{listing_id}", headers=owner.auth)).status_code == 204
        assert not photo_folder(listing_id).exists()

    async def test_sale_listings_have_photos_too(self, client, make):
        owner = await make.account("OWNER")
        listing_id = await make.sale_listing(owner, "Dhanmondi", 90.3742, 23.7461)
        response = await upload(client, owner, listing_id, ("flat.jpg", jpeg_bytes()), base="/marketplace/sale-listings")
        assert response.status_code == 200
        photo_id = response.json()["photos"][0]["id"]
        assert (await client.get(f"/marketplace/sale-listings/{listing_id}/photos/{photo_id}")).status_code == 200
        listed = (await client.get("/marketplace/sale-listings", params={"area_name": "Dhanmondi"})).json()["items"]
        assert any(item["id"] == listing_id and item["photos"] for item in listed)
