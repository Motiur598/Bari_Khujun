"""Seed a demo dataset for local development: rentals, sales, and one account per role.

Usage (from /backend):
    python -m app.scripts.seed_demo          # (re)create demo accounts, listings and title documents
    python -m app.scripts.seed_demo --clear  # remove everything the seed created

All demo accounts use the password demo-pass-123:
    demo.owner@barikhujun.com    OWNER            lists flats, seats and properties for sale
    demo.sublet@barikhujun.com   BACHELOR_TENANT  sublets seats in a flat they rent
    demo.student@barikhujun.com  BACHELOR_TENANT  looking for a seat
    demo.family@barikhujun.com   FAMILY_TENANT    looking for a family flat
    demo.buyer@barikhujun.com    BUYER            making offers on properties
    demo.admin@barikhujun.com    ADMIN            reviews KYC and property titles
    demo.owner2@barikhujun.com   OWNER            a second landlord with one seat listing
    demo.student2@barikhujun.com BACHELOR_TENANT  another seat seeker
    demo.buyer2@barikhujun.com   BUYER            another buyer

`python seed.py` (in backend/) builds on this with ready-made scenarios for the admin governance center.
"""

import argparse
import asyncio
import random
import shutil
from datetime import datetime, timezone
from io import BytesIO

from reportlab.pdfgen import canvas

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.core.security import hash_password
from app.schemas.marketplace import SaleListingIn, SaleStatus, TitleDocType, TitleStatus, sale_listing_fields
from app.schemas.rental import ListingIn, RentalStatus, listing_fields
from app.schemas.user import KycStatus, Role
from app.scripts.demo_photos import demo_photos, room
from app.services.listings import full_address, photo_folder
from app.utils.file_security import listing_photo_paths, render_listing_photo

DEMO_PASSWORD = "demo-pass-123"
# key: (email, full name, role, phone, NID number)
DEMO_ACCOUNTS = {
    "owner": ("demo.owner@barikhujun.com", "Kamrul Hasan", Role.OWNER, "+8801711000001", "1990267345128"),
    "sublet": ("demo.sublet@barikhujun.com", "Tanvir Rahman", Role.BACHELOR_TENANT, "+8801711000002", "2001845567301"),
    "student": ("demo.student@barikhujun.com", "Nusrat Jahan", Role.BACHELOR_TENANT, "+8801711000003", "2003456781234"),
    "family": ("demo.family@barikhujun.com", "Farhana Akter", Role.FAMILY_TENANT, "+8801711000004", "1988123409876"),
    "buyer": ("demo.buyer@barikhujun.com", "Imtiaz Chowdhury", Role.BUYER, "+8801711000005", "1985567812345"),
    "admin": ("demo.admin@barikhujun.com", "Bari Khujun Admin", Role.ADMIN, "+8801711000000", None),
    "owner2": ("demo.owner2@barikhujun.com", "Rashed Karim", Role.OWNER, "+8801711000006", "1979345612087"),
    "student2": ("demo.student2@barikhujun.com", "Arif Hossain", Role.BACHELOR_TENANT, "+8801711000007", "2002118745390"),
    "buyer2": ("demo.buyer2@barikhujun.com", "Sabrina Islam", Role.BUYER, "+8801711000008", "1991076543218"),
}


def _location(area: str, line: str, lat: float, lng: float) -> dict:
    """`area` is "Uttara", or "Uttara|Sector 4" for an area and its sub-area. The address gets the area and city."""
    area_name, _, sub_area = area.partition("|")
    location = {"city": "Dhaka", "area_name": area_name, "sub_area": sub_area or None, "formatted_address": line,
                "geo": {"type": "Point", "coordinates": [lng, lat]}}
    return {**location, "formatted_address": full_address(location)}


def _listing(category, title, area, line, lat, lng, rent, *, floor, floors, beds, baths, guests, smoking,
             meter, gate=None, lift=False, gen=False, service=0, deposit=2, utility=0, maid=0, sqft=None,
             seats=None, sublet=None, description="", available="2026-11-01") -> ListingIn:
    return ListingIn.model_validate({
        "category": category,
        "title": title,
        "description": description,
        "location": _location(area, line, lat, lng),
        "pricing": {"base_rent": rent, "service_charge": service, "deposit_months": deposit,
                    "utility_estimate": utility, "maid_estimate": maid},
        "building": {"floor_level": floor, "total_floors": floors, "has_elevator": lift,
                     "has_generator_backup": gen, "bedrooms": beds, "bathrooms": baths, "size_sqft": sqft},
        "house_rules": {"gate_closing_time": gate, "guest_policy": guests, "smoking_allowed": smoking,
                        "meter_type": meter},
        "seats": seats,
        "sublet": sublet,
        "available_from": available,
    })


def _mate(name, kind, institution, *habits):
    return {"display_name": name, "occupation_type": kind, "institution": institution, "habits": list(habits)}


def _room(name, kind, rent, *, seats=1, service=0, utility=0, maid=0):
    """A room in a bachelor tenant's sublet: SINGLE, or SHARED with `seats` seats. Amounts are per seat."""
    return {"name": name, "room_type": kind, "seats": seats, "seat_rent": rent,
            "service_charge": service, "utility_estimate": utility, "maid_estimate": maid}


OWNER_LISTINGS = [
    _listing("BACHELOR_SEAT", "Two seats in a quiet student flat near Azimpur", "Azimpur", "House 14, Azimpur Road",
             23.7272, 90.3866, 22000, floor=3, floors=5, beds=3, baths=2, guests="DAYTIME_ONLY", smoking=False,
             meter="PREPAID", gate="23:00", utility=3200, maid=2400, deposit=1,
             seats={"total_seats": 5, "available_seats": 2, "flatmates": [
                 _mate("Arif", "STUDENT", "University of Dhaka", "EARLY_RISER", "NON_SMOKER", "QUIET"),
                 _mate("Sajid", "STUDENT", "BUET", "NIGHT_OWL", "NON_SMOKER"),
                 _mate("Rumi", "STUDENT", "Dhaka Medical College", "TIDY", "COOKS")]},
             description="Ten minutes' walk to Nilkhet and the DU campus. Shared kitchen, rooftop access."),
    _listing("BACHELOR_SEAT", "Seat in shared room, Katabon", "Katabon", "Road 2, Katabon",
             23.7380, 90.3870, 16000, floor=4, floors=6, beds=2, baths=1, guests="NOT_ALLOWED", smoking=False,
             meter="POSTPAID", gate="22:30", utility=2400, maid=1600, deposit=1,
             seats={"total_seats": 4, "available_seats": 1, "flatmates": [
                 _mate("Imran", "STUDENT", "University of Dhaka", "QUIET", "NON_SMOKER"),
                 _mate("Fahim", "STUDENT", "Dhaka College", "SOCIAL")]}),
    _listing("BACHELOR_FLAT", "2-bed bachelor flat in Bashundhara Block B", "Bashundhara R/A|Block B", "Road 6, Block B",
             23.8205, 90.4270, 26000, floor=5, floors=8, beds=2, baths=2, lift=True, gen=True, service=3000,
             guests="ALLOWED", smoking=True, meter="PREPAID", sqft=950,
             description="Lift and full generator backup. Walk to NSU and IUB."),
    _listing("BACHELOR_SEAT", "Single seat for a working professional, Mirpur 10", "Mirpur|Mirpur 10", "Senpara Parbata, Mirpur 10",
             23.8075, 90.3700, 24000, floor=6, floors=9, beds=3, baths=2, lift=True, gen=True, service=1500,
             guests="ALLOWED", smoking=False, meter="PREPAID", utility=3600, maid=3000, deposit=1,
             seats={"total_seats": 4, "available_seats": 1, "flatmates": [
                 _mate("Nayeem", "PROFESSIONAL", "Software engineer, Banani", "WORKS_FROM_HOME", "NON_SMOKER"),
                 _mate("Rakib", "PROFESSIONAL", "Bank officer, Motijheel", "EARLY_RISER", "TIDY"),
                 _mate("Shuvo", "PROFESSIONAL", "Pharmacist", "QUIET")]}),
    _listing("BACHELOR_FLAT", "Bachelor flat on Tajmahal Road", "Mohammadpur", "Tajmahal Road, Block C",
             23.7600, 90.3620, 18000, floor=2, floors=5, beds=2, baths=1, guests="DAYTIME_ONLY", smoking=True,
             meter="POSTPAID", gate="23:30", sqft=780),
    _listing("BACHELOR_FLAT", "Furnished 1-bed studio in Niketan", "Niketan", "Road 7, Block D, Niketan",
             23.7765, 90.4140, 32000, floor=7, floors=10, beds=1, baths=1, lift=True, gen=True, service=4000,
             guests="ALLOWED", smoking=False, meter="PREPAID", sqft=620, deposit=3,
             description="Five minutes to Gulshan 1 offices. Furnished, with internet included."),
    _listing("FAMILY_FLAT", "3-bed family flat with lake view, Dhanmondi", "Dhanmondi", "Road 9/A, Dhanmondi",
             23.7465, 90.3725, 55000, floor=6, floors=10, beds=3, baths=3, lift=True, gen=True, service=6000,
             guests="ALLOWED", smoking=False, meter="POSTPAID", sqft=1650, deposit=3),
    _listing("FAMILY_FLAT", "Bright 3-bed in Lalmatia, near schools", "Lalmatia", "Block D, Lalmatia",
             23.7560, 90.3660, 38000, floor=3, floors=6, beds=3, baths=2, lift=True, gen=False, service=2500,
             guests="ALLOWED", smoking=False, meter="PREPAID", sqft=1350),
    _listing("FAMILY_FLAT", "Affordable 2-bed family flat, Mirpur 2", "Mirpur|Mirpur 2", "Road 4, Mirpur 2",
             23.8055, 90.3610, 20000, floor=1, floors=5, beds=2, baths=2, guests="ALLOWED", smoking=False,
             meter="PREPAID", gate="23:00", sqft=900),
    _listing("FAMILY_FLAT", "Spacious 4-bed duplex in Banani", "Banani", "Road 17, Banani",
             23.7940, 90.4030, 120000, floor=8, floors=12, beds=4, baths=4, lift=True, gen=True, service=15000,
             guests="ALLOWED", smoking=False, meter="POSTPAID", sqft=3200, deposit=3),
    _listing("FAMILY_FLAT", "3-bed family flat in Uttara Sector 4", "Uttara|Sector 4", "Road 12, Sector 4, Uttara",
             23.8640, 90.4000, 30000, floor=4, floors=7, beds=3, baths=2, lift=True, gen=True, service=2000,
             guests="ALLOWED", smoking=False, meter="PREPAID", sqft=1400),
    _listing("FAMILY_FLAT", "2-bed family flat, Aftabnagar", "Aftabnagar", "Block F, Aftabnagar",
             23.7670, 90.4380, 22000, floor=2, floors=6, beds=2, baths=2, guests="ALLOWED", smoking=False,
             meter="PREPAID", gate="23:30", sqft=1050),
    _listing("FAMILY_FLAT", "Family flat near Malibagh rail gate", "Malibagh", "DIT Road, Malibagh",
             23.7480, 90.4140, 25000, floor=5, floors=6, beds=3, baths=2, guests="DAYTIME_ONLY", smoking=False,
             meter="POSTPAID", gate="23:00", sqft=1200),
]

OWNER2_LISTINGS = [
    _listing("BACHELOR_SEAT", "Three seats in a new flat on Ring Road", "Mohammadpur", "Ring Road, Shyamoli end",
             23.7700, 90.3600, 18000, floor=5, floors=7, beds=3, baths=2, lift=True, gen=False, guests="DAYTIME_ONLY",
             smoking=False, meter="PREPAID", gate="23:00", utility=2400, maid=1800, deposit=1,
             seats={"total_seats": 4, "available_seats": 3, "flatmates": [
                 _mate("Jubayer", "STUDENT", "Dhaka College", "QUIET")]},
             description="Newly painted. Advance accepted by bKash only."),
]

SUBLET_LISTINGS = [
    _listing("BACHELOR_SEAT", "Subletting one seat in my Bashundhara flat", "Bashundhara R/A|Block C", "Road 3, Block C",
             23.8178, 90.4310, None, floor=4, floors=7, beds=3, baths=2, lift=True, gen=True,
             guests="ALLOWED", smoking=False, meter="PREPAID", deposit=1,
             sublet={"let_type": "SEAT",
                     "seat": {"room_size": 2, "seat_rent": 7000, "service_charge": 500, "utility_estimate": 1000, "maid_estimate": 750},
                     "flatmates": [_mate("Tanvir", "STUDENT", "North South University", "NIGHT_OWL", "SOCIAL"),
                                   _mate("Mehedi", "STUDENT", "IUB", "NON_SMOKER", "COOKS")]},
             description="I hold the lease; looking for one more flatmate from NSU or IUB."),
    _listing("BACHELOR_SEAT", "Two seats near BRAC University, Merul Badda", "Badda|Merul Badda", "Lane 5, Merul Badda",
             23.7720, 90.4285, None, floor=3, floors=5, beds=2, baths=2, guests="DAYTIME_ONLY", smoking=False,
             meter="PREPAID", gate="00:00", deposit=1,
             sublet={"let_type": "ROOMS",
                     "rooms": [_room("Big room", "SHARED", 4500, seats=2, utility=650, maid=500)],
                     "flatmates": [_mate("Sami", "STUDENT", "BRAC University", "QUIET", "TIDY")]},
             description="Take one seat, or the whole room with a friend."),
    _listing("BACHELOR_SEAT", "Single room and a shared room near Kawran Bazar", "Farmgate", "Tejturi Bazar West",
             23.7560, 90.3900, None, floor=5, floors=6, beds=3, baths=2, guests="ALLOWED", smoking=True,
             meter="POSTPAID", deposit=1,
             sublet={"let_type": "ROOMS",
                     "rooms": [_room("Single room", "SINGLE", 7000, utility=1000, maid=800),
                               _room("Shared room", "SHARED", 4200, seats=2, utility=700, maid=500)],
                     "flatmates": [_mate("Ashik", "PROFESSIONAL", "Journalist, Kawran Bazar", "NIGHT_OWL", "SMOKER")]}),
]


def _sale(kind, title, area, line, lat, lng, price, sqft, *, beds, baths, floor, floors, parking=1,
          handover="READY_FLAT", expected=None, lift=True, gen=True, blueprint=False, description="") -> SaleListingIn:
    return SaleListingIn.model_validate({
        "property_type": kind,
        "title": title,
        "description": description,
        "location": _location(area, line, lat, lng),
        "building": {"floor_level": floor, "total_floors": floors, "has_elevator": lift, "has_generator_backup": gen,
                     "bedrooms": beds, "bathrooms": baths, "size_sqft": sqft},
        "sale": {"asking_price": price, "price_negotiable": True, "parking_slots": parking, "handover_status": handover,
                 "expected_handover": expected,
                 "blueprint_url": f"{settings.app_base_url}/blueprints/demo-3-bed.svg" if blueprint else None},
    })


# (listing, title status). VERIFIED and PENDING listings get all three demo title documents.
SALE_LISTINGS = [
    (_sale("APARTMENT", "3-bed lake-facing apartment, Dhanmondi 9/A", "Dhanmondi", "Road 9/A, Dhanmondi",
           23.7461, 90.3742, 26_000_000, 1650, beds=3, baths=3, floor=5, floors=10, blueprint=True,
           description="South-facing, two balconies, one covered parking slot."), "VERIFIED"),
    (_sale("APARTMENT", "Corner apartment near Dhanmondi 27", "Dhanmondi", "Road 27 (old), Dhanmondi",
           23.7490, 90.3780, 21_000_000, 1400, beds=3, baths=2, floor=3, floors=8), "VERIFIED"),
    (_sale("APARTMENT", "Duplex penthouse, Dhanmondi 4", "Dhanmondi", "Road 4, Dhanmondi",
           23.7425, 90.3700, 34_000_000, 2000, beds=4, baths=4, floor=8, floors=10, parking=2), "PENDING"),
    (_sale("APARTMENT", "Family apartment by Lalmatia block D", "Lalmatia", "Block D, Lalmatia",
           23.7540, 90.3690, 25_000_000, 1800, beds=3, baths=3, floor=4, floors=7), "NOT_SUBMITTED"),
    (_sale("APARTMENT", "Ready 3-bed flat, Mirpur 2", "Mirpur|Mirpur 2", "Road 6, Mirpur 2",
           23.8060, 90.3650, 8_500_000, 1100, beds=3, baths=2, floor=4, floors=9, blueprint=True), "VERIFIED"),
    (_sale("APARTMENT", "Lake-side apartment, Mirpur DOHS", "Mirpur|Mirpur DOHS", "Avenue 3, Mirpur DOHS",
           23.8100, 90.3700, 9_500_000, 1250, beds=3, baths=3, floor=6, floors=10), "NOT_SUBMITTED"),
    (_sale("APARTMENT", "Compact 2-bed starter flat, Mirpur 11", "Mirpur|Mirpur 11", "Avenue 5, Mirpur 11",
           23.8150, 90.3660, 6_200_000, 950, beds=2, baths=2, floor=2, floors=6, parking=0, lift=False, gen=False),
     "NOT_SUBMITTED"),
    (_sale("HOUSE", "Four-storey family house, Mirpur 6", "Mirpur|Mirpur 6", "Road 3, Block C, Mirpur 6",
           23.8040, 90.3580, 22_000_000, 2400, beds=6, baths=5, floor=0, floors=4, parking=2), "VERIFIED"),
    (_sale("APARTMENT", "New 3-bed in Bashundhara Block D", "Bashundhara R/A|Block D", "Road 8, Block D",
           23.8190, 90.4300, 16_000_000, 1600, beds=3, baths=3, floor=5, floors=9), "VERIFIED"),
    (_sale("APARTMENT", "Under-construction tower unit, Bashundhara Block I", "Bashundhara R/A|Block I", "Road 3, Block I",
           23.8150, 90.4350, 13_000_000, 1450, beds=3, baths=2, floor=7, floors=14, handover="UNDER_CONSTRUCTION",
           expected="2027-12-31", description="Booking with 30% down; handover expected at the end of 2027."),
     "NOT_SUBMITTED"),
    (_sale("APARTMENT", "Spacious 4-bed, Bashundhara Block C", "Bashundhara R/A|Block C", "Road 10, Block C",
           23.8230, 90.4280, 21_000_000, 2000, beds=4, baths=4, floor=6, floors=10, parking=2), "PENDING"),
    (_sale("APARTMENT", "3-bed flat near Uttara Sector 7 park", "Uttara|Sector 7", "Road 18, Sector 7, Uttara",
           23.8700, 90.3950, 11_500_000, 1350, beds=3, baths=2, floor=3, floors=8), "VERIFIED"),
    (_sale("APARTMENT", "Bright corner unit, Uttara Sector 11", "Uttara|Sector 11", "Road 1, Sector 11, Uttara",
           23.8650, 90.4050, 13_500_000, 1500, beds=3, baths=3, floor=5, floors=9), "NOT_SUBMITTED"),
    (_sale("HOUSE", "Detached house with garden, Uttara Sector 4", "Uttara|Sector 4", "Road 9, Sector 4, Uttara",
           23.8680, 90.3980, 45_000_000, 3000, beds=5, baths=5, floor=0, floors=3, parking=3), "NOT_SUBMITTED"),
    (_sale("APARTMENT", "Luxury apartment, Gulshan 2", "Gulshan|Gulshan 2", "Road 59, Gulshan 2",
           23.7980, 90.4120, 85_000_000, 3200, beds=4, baths=5, floor=8, floors=14, parking=2, blueprint=True),
     "VERIFIED"),
    (_sale("APARTMENT", "Lake-view apartment, Gulshan 1", "Gulshan|Gulshan 1", "Road 32, Gulshan 1",
           23.7920, 90.4150, 70_000_000, 2800, beds=4, baths=4, floor=6, floors=12, parking=2), "NOT_SUBMITTED"),
]


def _demo_pdf(text: str) -> bytes:
    buffer = BytesIO()
    page = canvas.Canvas(buffer)
    page.setFont("Helvetica-Bold", 16)
    page.drawString(72, 760, "DEMO DOCUMENT - NOT A REAL RECORD")
    page.setFont("Helvetica", 12)
    page.drawString(72, 730, text)
    page.save()
    return buffer.getvalue()


def _title_documents(listing_id, title: str) -> list[dict]:
    folder = settings.upload_dir / "title" / str(listing_id)
    folder.mkdir(parents=True, exist_ok=True)
    documents = []
    for doc_type in TitleDocType:
        content = _demo_pdf(f"{doc_type.value.replace('_', ' ').title()} for: {title}")
        path = folder / f"{doc_type.value.lower()}_demo.pdf"
        path.write_bytes(content)
        documents.append({
            "doc_type": doc_type.value, "original_filename": f"{doc_type.value.lower()}.pdf",
            "content_type": "application/pdf", "size_bytes": len(content), "storage_path": str(path),
            "uploaded_at": datetime.now(timezone.utc),
        })
    return documents


async def _upsert_demo_user(email, full_name, role, phone, nid) -> object:
    now = datetime.now(timezone.utc)
    # NID numbers are recorded (they appear masked on leases) but no file is stored for demo accounts.
    documents = [] if nid is None else [{
        "doc_type": "NID", "doc_number": nid, "original_filename": "demo-nid.pdf", "content_type": "application/pdf",
        "size_bytes": 0, "storage_path": "", "uploaded_at": now,
    }]
    await get_db().users.update_one(
        {"email": email},
        {
            "$set": {"full_name": full_name, "role": role.value, "phone": phone,
                     "password_hash": hash_password(DEMO_PASSWORD), "kyc_status": KycStatus.VERIFIED.value,
                     "kyc_documents": documents, "updated_at": now},
            "$setOnInsert": {"kyc_review_note": None, "trust_score": 100, "is_banned": False, "token_version": 0, "created_at": now},
        },
        upsert=True,
    )
    return (await get_db().users.find_one({"email": email}, {"_id": 1}))["_id"]


async def clear_demo_data() -> int:
    """Remove every record the demo seeds created (users, listings, deals and their uploaded files)."""
    db = get_db()
    emails = [email for email, *_ in DEMO_ACCOUNTS.values()]
    ids = [user["_id"] async for user in db.users.find({"email": {"$in": emails}}, {"_id": 1})]
    for user_id in ids:
        shutil.rmtree(settings.upload_dir / "kyc" / str(user_id), ignore_errors=True)
    async for dispute in db.disputes.find({"$or": [{"claimant_id": {"$in": ids}}, {"respondent_id": {"$in": ids}}]}, {"_id": 1}):
        shutil.rmtree(settings.upload_dir / "disputes" / str(dispute["_id"]), ignore_errors=True)
    await db.disputes.delete_many({"$or": [{"claimant_id": {"$in": ids}}, {"respondent_id": {"$in": ids}}]})
    await db.qr_handshake_logs.delete_many({"$or": [{"owner_id": {"$in": ids}}, {"tenant_id": {"$in": ids}}]})
    await db.security_audit_logs.delete_many({"$or": [{"subject_user_id": {"$in": ids}}, {"actor.id": {"$in": ids}}]})
    listing_ids = [doc["_id"] async for doc in db.listings.find({"lister_id": {"$in": ids}}, {"_id": 1})]
    for listing_id in listing_ids:
        shutil.rmtree(settings.upload_dir / "title" / str(listing_id), ignore_errors=True)
        shutil.rmtree(photo_folder(listing_id), ignore_errors=True)
    involving = {"$or": [{"owner_id": {"$in": ids}}, {"tenant_id": {"$in": ids}}]}
    async for booking in db.bookings.find(involving, {"_id": 1}):
        (settings.upload_dir / "leases" / f"{booking['_id']}.pdf").unlink(missing_ok=True)
        shutil.rmtree(settings.upload_dir / "condition" / str(booking["_id"]), ignore_errors=True)
    async for ticket in db.maintenance_tickets.find(involving, {"_id": 1}):
        shutil.rmtree(settings.upload_dir / "maintenance" / str(ticket["_id"]), ignore_errors=True)
    await db.maintenance_tickets.delete_many(involving)
    await db.invoices.delete_many(involving)
    await db.reviews.delete_many({"$or": [{"reviewer_id": {"$in": ids}}, {"reviewee_id": {"$in": ids}}]})
    await db.bookings.delete_many(involving)
    await db.offers.delete_many({"$or": [{"buyer_id": {"$in": ids}}, {"seller_id": {"$in": ids}}]})
    await db.visit_slots.delete_many({"$or": [{"host_id": {"$in": ids}}, {"visitor_id": {"$in": ids}}]})
    removed = (await db.listings.delete_many({"_id": {"$in": listing_ids}})).deleted_count
    await db.users.delete_many({"_id": {"$in": ids}})
    return removed


# Outside Dhaka, so the division / district / upazila filter has something to show. seed.py adds these.
NATIONWIDE_RENTALS = [
    _listing("BACHELOR_SEAT", "Seat near Rajshahi University, Binodpur", "Binodpur", "Binodpur Bazar, Motihar",
             24.3690, 88.6400, 9000, floor=2, floors=4, beds=3, baths=2, guests="DAYTIME_ONLY", smoking=False,
             meter="PREPAID", gate="22:30", utility=1500, maid=1200, deposit=1,
             seats={"total_seats": 3, "available_seats": 1, "flatmates": [
                 _mate("Rahim", "STUDENT", "University of Rajshahi", "QUIET", "NON_SMOKER")]},
             description="Five minutes' walk to the RU main gate."),
    _listing("FAMILY_FLAT", "2-bed family flat in Uposhohor, Rajshahi", "Uposhohor", "Sector 2, Uposhohor",
             24.3740, 88.6180, 14000, floor=2, floors=5, beds=2, baths=2, guests="ALLOWED", smoking=False,
             meter="PREPAID", sqft=1050),
    _listing("FAMILY_FLAT", "3-bed flat near GEC Circle, Chattogram", "Nasirabad", "Road 2, Nasirabad Housing",
             22.3640, 91.8230, 28000, floor=4, floors=8, beds=3, baths=3, lift=True, gen=True, guests="ALLOWED",
             smoking=False, meter="POSTPAID", sqft=1500),
    _listing("BACHELOR_FLAT", "Bachelor flat in Zindabazar, Sylhet", "Zindabazar", "Lamabazar Road, Zindabazar",
             24.8960, 91.8690, 15000, floor=3, floors=5, beds=2, baths=1, guests="ALLOWED", smoking=True,
             meter="PREPAID", sqft=800),
    _listing("BACHELOR_SEAT", "Seat near KUET, Fulbarigate, Khulna", "Fulbarigate", "Teligati Road, Fulbarigate",
             22.9000, 89.5020, 10500, floor=1, floors=3, beds=3, baths=2, guests="NOT_ALLOWED", smoking=False,
             meter="PREPAID", gate="22:00", utility=1800, maid=1500, deposit=1,
             seats={"total_seats": 3, "available_seats": 2, "flatmates": [_mate("Tushar", "STUDENT", "KUET", "EARLY_RISER")]}),
]
NATIONWIDE_SALES = [
    _sale("APARTMENT", "Apartment in Khulshi, Chattogram", "Khulshi", "Road 3, Khulshi R/A", 22.3610, 91.8060,
          12_500_000, 1450, beds=3, baths=3, floor=5, floors=10),
    _sale("HOUSE", "Two-storey house near Shaheb Bazar, Rajshahi", "Shaheb Bazar", "Kumarpara, Shaheb Bazar",
          24.3660, 88.6000, 18_000_000, 2400, beds=5, baths=4, floor=0, floors=2),
]


def _store_photo(listing: dict, index: int, content: bytes) -> dict:
    photo_id = f"{listing['_id']}{index:08x}"  # 24 + 8 hex characters, like a real photo id
    width, height = render_listing_photo(content, *listing_photo_paths(photo_folder(listing["_id"]), photo_id))
    return {"id": photo_id, "width": width, "height": height, "uploaded_at": listing["created_at"]}


def _store_demo_photos(listing: dict, seed: int) -> dict:
    """$set fields giving the listing its stand-in photos, and two for each room a sublet lets."""
    photo_folder(listing["_id"]).mkdir(parents=True, exist_ok=True)
    fields = {"photos": [_store_photo(listing, index, content) for index, content in enumerate(demo_photos(seed, listing["building"]["total_floors"]))]}
    rng = random.Random(seed)
    for number, entry in enumerate(((listing.get("sublet") or {}).get("rooms")) or []):
        if entry["room_type"] != "SEAT":
            fields[f"sublet.rooms.{number}.photos"] = [_store_photo(listing, 16 + number * 4 + index, room(rng)) for index in range(2)]
    return fields


async def seed_base() -> dict:
    """Create the demo accounts, rentals and sale listings. Returns {account key: user id}."""
    now = datetime.now(timezone.utc)
    user_ids = {key: await _upsert_demo_user(*account) for key, account in DEMO_ACCOUNTS.items()}

    rentals = [
        {**listing_fields(listing), "rental_status": RentalStatus.AVAILABLE.value, "lister_id": user_ids[key],
         "is_sublet": key == "sublet", "created_at": now, "updated_at": now}
        for key, listings in (("owner", OWNER_LISTINGS), ("sublet", SUBLET_LISTINGS), ("owner2", OWNER2_LISTINGS))
        for listing in listings
    ]
    await get_db().listings.insert_many(rentals)

    for listing, title_status in SALE_LISTINGS:
        doc = {**sale_listing_fields(listing), "sale_status": SaleStatus.AVAILABLE.value,
               "title_status": title_status, "title_documents": [], "title_review_note": None,
               "lister_id": user_ids["owner"], "created_at": now, "updated_at": now}
        await get_db().listings.insert_one(doc)
        if title_status != TitleStatus.NOT_SUBMITTED:
            await get_db().listings.update_one(
                {"_id": doc["_id"]}, {"$set": {"title_documents": _title_documents(doc["_id"], listing.title)}}
            )
    # Drawn stand-in photos (marked DEMO PHOTO), so the demo listings aren't bare.
    async for index, listing in _enumerate(get_db().listings.find({"lister_id": {"$in": list(user_ids.values())}})):
        await get_db().listings.update_one({"_id": listing["_id"]}, {"$set": _store_demo_photos(listing, index)})
    print(f"Seeded {len(DEMO_ACCOUNTS)} accounts, {len(rentals)} rentals and {len(SALE_LISTINGS)} sale listings.")
    return user_ids


async def seed_nationwide(user_ids: dict) -> int:
    """Add the demo listings outside Dhaka (with stand-in photos). Returns how many."""
    now = datetime.now(timezone.utc)
    docs = [
        {**listing_fields(listing), "rental_status": RentalStatus.AVAILABLE.value, "lister_id": user_ids["owner"],
         "is_sublet": False, "created_at": now, "updated_at": now}
        for listing in NATIONWIDE_RENTALS
    ] + [
        {**sale_listing_fields(listing), "sale_status": SaleStatus.AVAILABLE.value, "title_status": TitleStatus.NOT_SUBMITTED,
         "title_documents": [], "title_review_note": None, "lister_id": user_ids["owner"], "created_at": now, "updated_at": now}
        for listing in NATIONWIDE_SALES
    ]
    await get_db().listings.insert_many(docs)
    for index, doc in enumerate(docs):
        await get_db().listings.update_one({"_id": doc["_id"]}, {"$set": _store_demo_photos(doc, 1000 + index)})
    return len(docs)


async def _enumerate(cursor):
    index = 0
    async for item in cursor:
        yield index, item
        index += 1


async def main(clear_only: bool) -> None:
    await connect_to_mongo()
    try:
        print(f"Removed {await clear_demo_data()} demo listings")
        if not clear_only:
            ids = await seed_base()
            print(f"Added {await seed_nationwide(ids)} listings outside Dhaka (Rajshahi, Chattogram, Sylhet, Khulna).")
            print(f"Demo password: {DEMO_PASSWORD}")
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="only remove the demo data")
    asyncio.run(main(parser.parse_args().clear))
