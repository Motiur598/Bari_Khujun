"""Bari Khujun demo seed: accounts, Dhaka listings, and ready-made scenarios for every module.

Usage (from backend/, with MongoDB running):
    python seed.py          # wipe the previous demo data and seed everything again
    python seed.py --clear  # only wipe the demo data

What you get (all passwords are demo-pass-123):
  - Owners, bachelor and family tenants, buyers and an admin (see app/scripts/seed_demo.py for the list).
  - 17 rentals and 16 sale listings across Dhaka.
  - A booking ready for QR scanning: demo.student has an approved request on the Katabon seat. Paste the printed
    token into the scanner on the student's dashboard.
  - An active family lease with move-in photos, plus a deposit dispute the owner has answered with claim photos,
    waiting in the admin's arbitration court.
  - A scammer-radar alert: demo.owner2 issued three handshake codes in a row that nobody has scanned.
  - An accepted bayna offer, so demo.buyer can raise a BAYNA_BREACH dispute.

Scenarios run through the real endpoint functions, so they follow the same rules (and write the same audit
trail) as the app does.
"""

import argparse
import asyncio
import io
import struct
import zlib
from datetime import date, datetime, timedelta, timezone

from fastapi import BackgroundTasks, UploadFile

from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.core.limiter import limiter
from app.routers import admin_governance, marketplace, operations, qr_handshake
from app.schemas.booking import BookingCreate, DepositMethod, ScanRequest
from app.schemas.governance import DisputeType
from app.schemas.marketplace import DHAKA_TZ, OfferCreate, OfferResponse, OfferType
from app.scripts.seed_demo import DEMO_ACCOUNTS, DEMO_PASSWORD, clear_demo_data, seed_base, seed_nationwide
from app.services.governance import check_qr_spam


def _png(width: int, height: int, pixel) -> bytes:
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


WALL = (233, 228, 214)
# Move-in baseline: clean wall and floor. Owner's claim: the same wall with a damp stain and a broken tile.
BASELINE_WALL = _png(320, 240, lambda x, y: WALL if y < 180 else (176, 160, 140))
BASELINE_KITCHEN = _png(320, 240, lambda x, y: (205, 210, 214) if (x // 40 + y // 40) % 2 else (160, 168, 176))
CLAIM_WALL = _png(320, 240, lambda x, y: (150, 140, 120) if (x - 210) ** 2 / 2 + (y - 90) ** 2 < 1400 else WALL if y < 180 else (176, 160, 140))
CLAIM_KITCHEN = _png(
    320, 240,
    lambda x, y: (60, 60, 60) if abs((x - 120) - (y - 100)) < 3 and 80 < x < 160 else (205, 210, 214) if (x // 40 + y // 40) % 2 else (160, 168, 176),
)


async def _user(user_id) -> dict:
    return await get_db().users.find_one({"_id": user_id})


async def _rental(title_prefix: str) -> dict:
    return await get_db().listings.find_one({"title": {"$regex": f"^{title_prefix}"}, "listing_mode": {"$ne": "SALE"}})


def _request(listing: dict, days_ahead: int, amount: int, reference: str, message: str | None = None) -> BookingCreate:
    move_in = datetime.now(timezone.utc).astimezone(DHAKA_TZ).date() + timedelta(days=days_ahead)
    return BookingCreate(
        listing_id=str(listing["_id"]), move_in_date=move_in, deposit_amount=amount,
        payment_method=DepositMethod.BKASH, payment_reference=reference, message=message,
    )


async def ready_for_scan(users: dict) -> str:
    """demo.student asks for the Katabon seat and the owner approves; the QR token is printed for scanning."""
    listing = await _rental("Seat in shared room, Katabon")
    booking = await qr_handshake.request_to_rent(
        _request(listing, 5, 4000, "BKSEED0001", "Final-year DU student, non-smoker."), user=users["student"]
    )
    issued = await qr_handshake.generate_handshake_qr(request=None, booking_id=booking.id, background_tasks=BackgroundTasks(), user=users["owner"])
    return issued.token


async def disputed_lease(users: dict) -> str:
    """A family lease with move-in photos, then a deposit dispute the owner has answered with claim photos."""
    family, owner = users["family"], users["owner"]
    listing = await _rental("Bright 3-bed in Lalmatia")
    booking = await qr_handshake.request_to_rent(_request(listing, 1, 76000, "BKSEED0002"), user=family)
    issued = await qr_handshake.generate_handshake_qr(request=None, booking_id=booking.id, background_tasks=BackgroundTasks(), user=owner)
    await qr_handshake.scan_and_confirm(request=None, payload=ScanRequest(token=issued.token), user=family)
    await operations.upload_condition_photos(
        booking.id, room="Living room", files=[_upload("living-room-wall.png", BASELINE_WALL)],
        caption="North wall, freshly painted, no marks", user=family,
    )
    await operations.upload_condition_photos(
        booking.id, room="Kitchen", files=[_upload("kitchen-floor.png", BASELINE_KITCHEN)],
        caption="Floor tiles intact", user=family,
    )
    dispute = await admin_governance.raise_dispute(
        dispute_type=DisputeType.DEPOSIT_DEDUCTION,
        claimed_amount=76000,
        description="The owner says he will keep the whole two-month deposit for 'damage'. The wall and floor were "
                    "exactly like this when we moved in; our move-in photos show it.",
        booking_id=booking.id,
        user=family,
    )
    await admin_governance.respond_to_dispute(
        dispute.id,
        statement="There is a large damp stain on the living-room wall and a cracked kitchen tile that were not there "
                  "before. Repainting and retiling cost BDT 30,000.",
        claimed_deduction=30000,
        photos=[_upload("wall-stain.png", CLAIM_WALL), _upload("cracked-tile.png", CLAIM_KITCHEN)],
        user=owner,
    )
    return dispute.case_number


async def qr_spam(users: dict) -> int:
    """demo.owner2 approves three seat requests in a row and nobody scans: the radar flags it HIGH."""
    owner2 = users["owner2"]
    listing = await _rental("Three seats in a new flat on Ring Road")
    for key, reference in (("student2", "BKSEED0101"), ("sublet", "BKSEED0102"), ("student", "BKSEED0103")):
        booking = await qr_handshake.request_to_rent(_request(listing, 7, 4500, reference), user=users[key])
        await qr_handshake.generate_handshake_qr(request=None, booking_id=booking.id, background_tasks=BackgroundTasks(), user=owner2)
    await check_qr_spam(owner2["_id"])
    return await get_db().security_audit_logs.count_documents({"kind": "ALERT", "subject_user_id": owner2["_id"]})


async def accepted_bayna(users: dict) -> str:
    """demo.buyer's token-money offer on the Mirpur 11 flat, accepted by the owner."""
    listing = await get_db().listings.find_one({"title": {"$regex": "^Compact 2-bed starter flat"}})
    offer = await marketplace.create_offer(
        OfferCreate(listing_id=str(listing["_id"]), offer_type=OfferType.TOKEN_MONEY, amount=6_000_000,
                    token_amount=500_000, note="Bayna ready this week"),
        user=users["buyer"],
    )
    await marketplace.respond_to_offer(offer.id, OfferResponse(action="ACCEPT", note="Agreed"), user=users["owner"])
    return listing["title"]


async def main(clear_only: bool) -> None:
    # Scenarios call the endpoint functions directly, outside any HTTP request, so per-request rate limits don't apply.
    limiter.enabled = False
    await connect_to_mongo()
    try:
        print(f"Removed {await clear_demo_data()} demo listings and their deals")
        if clear_only:
            return
        ids = await seed_base()
        print(f"Added {await seed_nationwide(ids)} listings outside Dhaka (Rajshahi, Chattogram, Sylhet, Khulna).")
        users = {key: await _user(user_id) for key, user_id in ids.items()}

        token = await ready_for_scan(users)
        case_number = await disputed_lease(users)
        alerts = await qr_spam(users)
        bayna_listing = await accepted_bayna(users)

        print(f"\nPassword for every account: {DEMO_PASSWORD}")
        for email, name, role, *_ in DEMO_ACCOUNTS.values():
            print(f"  {email:<30} {role.value:<16} {name}")
        print(f"\nDispute {case_number} is waiting in the admin's arbitration court.")
        print(f"Scammer radar: {alerts} HIGH alert(s) raised for demo.owner2.")
        print(f"Accepted bayna offer on '{bayna_listing}' (demo.buyer can raise a BAYNA_BREACH dispute).")
        print("\nQR token ready to scan (sign in as demo.student, Dashboard > Requests > Scan the owner's QR, paste it):")
        print(token)
        print("Valid for 24 hours. Reopening the QR on the owner's dashboard issues a new code and retires this one.")
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="only remove the demo data")
    asyncio.run(main(parser.parse_args().clear))
