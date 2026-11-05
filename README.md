# Bari Khujun

Smart rental (bachelor & family), property buy/sell and QR-handshake platform.

```
backend/   FastAPI + Motor (MongoDB) + Pydantic v2 + PyJWT
frontend/  React (Vite) + TailwindCSS + React Router v6 + Axios + Lucide
```

## Prerequisites

- Python 3.11+ and Node 20+
- MongoDB running at `mongodb://localhost:27017`

## Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements.txt
cp .env.example .env            # then fill in MONGO_URI, JWT_AUTH_SECRET and QR_HANDSHAKE_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"   # run twice: one value per secret
uvicorn app.main:app --reload --port 8000
```

The server won't start without `.env`. `MONGO_URI` and both secrets are required, with no built-in defaults; each secret must be at least 32 characters, and the two must differ.

API docs: http://localhost:8000/docs

Create an admin (admins cannot self-register):

```bash
python -m app.scripts.create_admin --email admin@barikhujun.com --name "Site Admin"
```

### Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

`tests/test_security_guardrails.py` replays six attacks through the real API and checks both the response and the database afterwards: privilege escalation through mass assignment, NoSQL operator injection, QR replay and cross-tenant hijacking, five simultaneous scans racing for the last seat, IDOR on leases, invoices and KYC files, and disguised executables uploaded as ID photos. `tests/test_kyc_auto_verify.py` covers the automated ID check; it runs the photo checks for real and stands in for the OCR and face models (`tests/kyc_support.py`).

The suite runs the app in-process against a local MongoDB. It uses its own `barikhujun_test` database (set `TEST_MONGO_URI` to change it; the name must end in `_test`), which it empties first and drops afterwards. Uploads go to a temporary folder, secrets are generated per run, and `.env` isn't needed.

## Frontend

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173, proxies /api to :8000 (API_PROXY_TARGET changes that)
```

**Maps.** Every map is kept to Bangladesh and has three styles in its corner:

- **Map** (default): Esri's World Street Map, with English road and town names. It needs no API key and is fine for development and non-commercial use.
- **Detailed:** OpenStreetMap's own tiles. Far more roads, shops and landmarks, mostly named in Bengali.
- **Satellite:** Esri imagery with roads on top, for finding the exact building.

Esri's map names much of the country sparsely, so the app draws its own English names on top: divisions at country zoom, districts at regional zoom, and upazilas/thanas from city zoom down to the street. Zooming in further adds about 7,600 local names across all 64 districts: towns from zoom 10, unions and suburbs from 11, neighbourhoods and villages from 12, and hamlets from 14. Bigger places go first, and no name is drawn over another. Dhaka city gets none of them, because Esri already names its neighbourhoods. For a commercial launch, either get an ArcGIS Location Platform account, or set `VITE_MAP_TILE_URL` (and `VITE_MAP_TILE_ATTRIBUTION`) in `frontend/.env.local` to another provider.

**Place search and addresses.** Place search ("Dhanmondi 27", "Road 4, Uttara") and the picker's address lookup use OpenStreetMap's public Nominatim server, in English. Its [usage policy](https://operations.osmfoundation.org/policies/nominatim/) allows light use only, so the app sends at most one request a second, caches results, and only searches when someone presses Search (no search-as-you-type). For production traffic, set `VITE_NOMINATIM_URL` to another Nominatim server's base URL and add its origin to the CSP's `connect-src` in `vite.config.js`.

### Demo data

```bash
cd backend
python seed.py          # wipe the previous demo data, then seed accounts, listings and ready-made scenarios
python seed.py --clear  # remove everything the seed created
```

`python -m app.scripts.seed_demo` still seeds just the accounts and listings, with no scenarios.

`seed.py` (and `seed_demo`) create 17 rentals and 16 sale listings across Dhaka, plus 5 rentals and 2 sales in Rajshahi, Chattogram, Sylhet and Khulna, so the division and district filter has something to show. `seed.py` builds its scenarios by calling the real endpoint functions, so the same rules and audit trail apply:

- **A booking ready for QR scanning.** demo.student's request for the Katabon seat is approved, and the token is printed at the end. Sign in as demo.student, open Dashboard → Requests → *Scan the owner's QR* and paste it.
- **An active family lease** with move-in photos, plus a deposit dispute the owner has answered with claim photos. It's waiting in the admin's arbitration court.
- **A scammer-radar alert:** demo.owner2 issued three handshake codes that nobody scanned.
- **An accepted bayna offer,** so demo.buyer can raise a `BAYNA_BREACH` dispute.

Every demo account uses the password `demo-pass-123`:

| Email | Role | Use it to |
| --- | --- | --- |
| `demo.owner@barikhujun.com` | OWNER | list rentals and sales, approve requests, answer offers and disputes |
| `demo.owner2@barikhujun.com` | OWNER | the landlord the scammer radar has flagged |
| `demo.sublet@barikhujun.com` | BACHELOR_TENANT | sublet seats |
| `demo.student@barikhujun.com` | BACHELOR_TENANT | scan the seeded QR code |
| `demo.student2@barikhujun.com` | BACHELOR_TENANT | another seat seeker |
| `demo.family@barikhujun.com` | FAMILY_TENANT | the tenant in the active lease and the deposit dispute |
| `demo.buyer@barikhujun.com` | BUYER | make offers, book visits, raise a bayna dispute |
| `demo.buyer2@barikhujun.com` | BUYER | another buyer |
| `demo.admin@barikhujun.com` | ADMIN | the governance center, KYC and title reviews |

Some sale listings come with demo title documents (marked "DEMO DOCUMENT"), so the deed vault has work in it.

## Feature 1 — Auth & KYC

| Method | Path | Access |
| --- | --- | --- |
| POST | `/api/auth/register` | public (roles `OWNER`, `BACHELOR_TENANT`, `FAMILY_TENANT`, `BUYER`) |
| POST | `/api/auth/login` | public |
| GET | `/api/auth/me` | any signed-in user |
| PATCH | `/api/auth/me` | any signed-in user; body `full_name` and/or `phone` (nothing else is accepted) |
| POST | `/api/auth/logout-all` | any signed-in user; revokes every token issued so far |
| POST | `/api/auth/kyc-auto-verify` | non-admin users; multipart `doc_type`, `front`, `back` (photos of both sides) |
| GET | `/api/auth/kyc/{user_id}/documents/{doc_type}` | that user or `ADMIN`; `?side=back` for the back |
| GET | `/api/auth/kyc/pending` | `ADMIN` |
| PATCH | `/api/auth/kyc/{user_id}/review` | `ADMIN`; body `{"status": "VERIFIED" \| "REJECTED", "note": "..."}` |

**Automated ID verification.** Users photograph (or upload) both sides of a National ID, Student ID or Job ID on their profile, and the card is checked automatically (`app/utils/id_card_verifier.py`, `app/services/kyc_verification.py`):

1. **Photo mistakes**, reported in plain words with no penalty (`200`, `kyc_status: "NEEDS_RETRY"`, a `mistakes` list per side): too blurry, too dark, flash glare, card cut off or too far away, name or number unreadable, no portrait on the front, or a name that doesn't match the profile name (then the user fixes a typo in their profile or uses their own card).
2. **Duplicates.** Every account's ID number and portrait must be its own; names may repeat, since different people share names, so a name never counts towards a match. A readable card is compared with every other account's: the ID number, the front of the card (perceptual hash and a 16x16 pixel signature), and the holder's portrait, cropped from the card and compared by face recognition (OpenCV YuNet + SFace).
   - Same number, whatever the names: **revoked** at once (`403`, `kyc_status: "REVOKED"`, a generic message), 30 trust points off, and a `KYC_DUPLICATE_ID` alert for admins.
   - Same face, or a near-identical front: **held** for an admin (`202`, `kyc_status: "PENDING"`) with a `KYC_POSSIBLE_DUPLICATE` alert, because every card of a kind shares one printed design.
   - Otherwise **verified** (`200`).
3. **What users see.** Responses never include scores, hashes, coordinates, thresholds, matched accounts or model names. Admins see the evidence and both cards side by side in the Fraud Detection Center (scammer radar tab), and can approve, revoke, or restore a wrongly revoked account. A revoked user is told to appeal by emailing a video of themselves holding the card to `barikhujun.support@gmail.com`.

- `kyc_status`: `NOT_SUBMITTED` → `VERIFIED`, `PENDING` (held for an admin, who approves or rejects it) or `REVOKED` (until an admin restores it). `is_verified` is `true` exactly when `kyc_status` is `VERIFIED`.
- Photos: JPEG, PNG or WebP (checked by file signature), up to 10 MB each (the app shrinks them before upload). Only cards that pass the photo checks are kept, under `backend/uploads/kyc/<user_id>/`, never served publicly. Fingerprints are kept in `db.kyc_verifications`, which no user endpoint returns.
- Models (YuNet and SFace for faces, EasyOCR's text finder and Bengali/English reader; about 320 MB, mostly the reader) download on the first check into `backend/models/` (`VISION_MODEL_DIR`); the face models are checksum-verified. They run on this server: no photo or result is sent anywhere. A check takes about 10 seconds on a CPU (20 for the first, while the models load); checks run one at a time.
- `trust_score` defaults to 100.
- Once ID documents are under review, verified or revoked, the name is locked to them: changing it is a `409`.

## Module 1 — Rentals (Features 2–5)

| Method | Path | Access |
| --- | --- | --- |
| GET | `/api/rentals` (also `/api/rentals/search`) | public; search (filters below) |
| GET | `/api/rentals/landmarks` | public; universities and office hubs for the proximity filter |
| GET | `/api/rentals/areas` | public; popular areas (centre, radius) and every other area name in use, with rental and sale counts. With `division`, `district` and/or `upazila`, only the area names in use there |
| GET | `/api/rentals/compare?ids=…` | public; 1–4 listings in the order given |
| GET | `/api/rentals/{id}` | public |
| GET | `/api/rentals/mine` | `OWNER`, `BACHELOR_TENANT` |
| POST | `/api/rentals` | `OWNER` (any category), `BACHELOR_TENANT` (`BACHELOR_SEAT` only, flagged `is_sublet`) |
| PUT | `/api/rentals/{id}` | the lister |
| DELETE | `/api/rentals/{id}` | the lister or `ADMIN` |
| POST | `/api/rentals/{id}/photos` | the lister; multipart `files` (JPEG, PNG or WebP, 5 MB each, up to 12 per listing) |
| POST | `/api/rentals/{id}/photos/{photo_id}/cover` · DELETE `/api/rentals/{id}/photos/{photo_id}` | the lister |
| GET | `/api/rentals/{id}/photos/{photo_id}?size=thumb` | public |

- **Categories:** `FAMILY_FLAT`, `BACHELOR_FLAT`, `BACHELOR_SEAT`. Every listing has `house_rules`: `gate_closing_time` (`"HH:MM"`, or `null` for open all night), `guest_policy` (`NOT_ALLOWED` / `DAYTIME_ONLY` / `ALLOWED`), `smoking_allowed`, `meter_type` (`PREPAID` / `POSTPAID`).
- **Seat splitter:** `BACHELOR_SEAT` listings need `seats` (`total_seats`, `available_seats`, `flatmates`). The server divides the flat's rent, service charge, utility and maid estimates by `total_seats`, rounding each share up, and stores the result in `seats.split`. `effective_rent` is the per-seat rent for seats and the base rent for flats; the budget filter uses it. Full seat listings (0 free) are hidden from search.
- **Editing a listing with tenants:** seats held by tenants who confirmed through Bari Khujun can't be offered again: `available_seats` can be at most `total_seats` minus those tenants (`409` otherwise). A listing with tenants or open requests can't change category. The save only goes through if the listing hasn't changed since it was read, so a seat taken by a handshake at that moment isn't overwritten.
- **Deleting a listing:** refused (`409`) while someone rents the place, or, for a sale, while an offer on it is accepted. Otherwise open rent requests are cancelled with their deposit marked for refund (their QR codes stop working), open offers close, and upcoming visits are called off. The listing is suspended first, so no handshake or offer acceptance can complete on it in the meantime.
- **Search filters:** `category` (repeatable), `min_rent`/`max_rent`, `min_floor`/`max_floor`, `elevator=true`, `generator=true`, `meter_type`, `smoking_allowed`, plus the target area below. `sort`: `distance`, `rent_asc`, `rent_desc`, `newest`.
- **Location:** every listing (rent or sale) stores where it is in one object:

  ```json
  "location": {
    "city": "Dhaka",
    "area_name": "Uttara",
    "sub_area": "Sector 7",
    "formatted_address": "House 12, Road 4, Sector 7, Uttara, Dhaka",
    "geo": { "type": "Point", "coordinates": [90.3984, 23.8728] },
    "division": "Dhaka",
    "district": "Dhaka",
    "upazila": "Uttara"
  }
  ```

  - **`geo`:** GeoJSON, `[longitude, latitude]`. It must be inside Bangladesh, which also catches swapped coordinates and an unset `[0, 0]` pin.
  - **`area_name`:** the area tenants filter by.
  - **`sub_area`:** optional, the part of that area ("Sector 7", "Block C", "Mirpur 10").
  - **`division`, `district`, `upazila`:** set by the server from `geo` on every save (see *Bangladesh places* below). Clients don't send them; a request that does is refused with `422`. Listings saved before these existed get them at startup.
  - **Startup:** creates a 2dsphere index on `location.geo` and an index on `location.area_name`. Listings saved in the older shape (`address` beside a bare GeoJSON `location`) are converted automatically.
- **Target area** (rentals here, sales on `/api/marketplace/sale-listings` or `/api/marketplace/search`): `division`, `district`, `upazila`, `area_name`, and/or a centre (`landmark=<id>`, or `lat` + `lng`) with `radius_km` (default 2). When given, only listings in that area are returned:
  - `division`, `district` and `upazila` match the listing's stored names exactly, ignoring case (`district=Rajshahi`).
  - `area_name` is matched against `location.area_name` only (not the sub-area or address), ignoring case and as whole words. So `badda` finds "Merul Badda", but `Mirpur` doesn't find "Mirpurpara". It's plain text, never a regex.
  - A centre filters with `$nearSphere` on `location.geo` (`$maxDistance` = `radius_km` × 1000), nearest first. Another `sort` re-orders the results inside the circle. Each result gets `distance_km`. The total counts the same circle with `$geoWithin`/`$centerSphere`, because counts can't use `$nearSphere`.
  - Combined, a listing must match all of them (`district=Rajshahi&area_name=Binodpur`).

  Without a target the API returns every open listing in Bangladesh; the web app always asks for one first (see below).
- **Popular areas** (`app/data/areas.py`) have a centre and rough radius. `/api/rentals/areas` counts each one with the same whole-word rule.
- **Bangladesh places** (`app/data/bd_admin.json.gz`, `app/services/bd_admin.py`): the 8 divisions, 64 districts and 544 upazilas/thanas, with their outlines. The data is [geoBoundaries](https://www.geoboundaries.org/) BGD ADM1–3 (from BBS and OCHA; ADM1 CC0, ADM2/3 CC BY 3.0 IGO), with names updated to the current official spellings (Chattogram, Barishal, Bogura, Cumilla, Jashore, Chapai Nawabganj, Rajshahi). Older spellings ("Chittagong", "Barisal", "Bogra", "Comilla", "Jessore") are kept as aliases for search. A point is placed by its outline; a pin just off the coast or a border takes the nearest upazila within 8 km.
- **Local place names** (`app/data/bd_places.json.gz`) are only used for map labels. They cover union councils from geoBoundaries BGD ADM4 (BBS and OCHA, CC BY 3.0 IGO), plus towns, suburbs, neighbourhoods, villages and hamlets from OpenStreetMap that have an English name. The OpenStreetMap part is © OpenStreetMap contributors under the [ODbL](https://opendatacommons.org/licenses/odbl/), so the file stays under that licence. City wards ("Ward No-12") are left out. Spelling variants of one name ("Bogra", "Bogura") within 2 km are kept once, and a place named like its own upazila is skipped. To rebuild the file, run `python -m app.scripts.build_place_names` from `backend/`. It downloads about 15 MB and retries while the public Overpass servers are busy. Open data has few English neighbourhood names in some city centres, Sylhet's above all, so those stay sparser than the countryside.

  | Method | Path | Access |
  | --- | --- | --- |
  | GET | `/api/locations` | public; every division, district and upazila: `id` (`"rajshahi/rajshahi/paba"`), `level`, `name`, `aliases`, `division`, `district`, label point `center` `[lng, lat]`, `bbox` `[west, south, east, north]`. Cached for an hour |
  | GET | `/api/locations/places` | public; local names for the map labels: `{"attribution", "places": [[name, lng, lat, rank], …]}`, sorted by `rank`, 1 (towns) to 4 (hamlets). Sent gzipped (about 90 KB) to clients that accept gzip. Cached for an hour |
  | GET | `/api/locations/counts?mode=rent\|sale` | public; open listings per place id |
  | GET | `/api/locations/at?lat=…&lng=…` | public; the division, district and upazila of a point (`404` outside Bangladesh) |
  | GET | `/api/locations/boundary/{id}` | public; a place's outline as a GeoJSON Feature. Cached for a day |

- **"Where are you planning to shift?"** A bar on top of the rent and buy feeds. Until the searcher picks a target, the feed lists nothing and asks for one. The bar offers:
  - **Division › District › Upazila / thana** drop-downs, each place with how many listings it has. Each step narrows the feed, outlines the place on the map and frames it. Changing a step clears the steps under it; "All of Bangladesh" clears the search;
  - area tags: the areas with listings in the chosen place ("Areas in Matihar, Rajshahi": Binodpur), or, before a place is chosen, popular Dhaka areas (Uttara, Mirpur, Dhanmondi, Bashundhara R/A, Mohammadpur, Banani, Badda, Khilgaon, Motijheel). Tapping the chosen tag again goes back to the whole place;
  - a place search in English: divisions, districts, upazilas, areas and campuses/offices appear as you type ("rajshahi", "paba", "chittagong", "nsu"), closest match first. Search looks any road, building or neighbourhood up on OpenStreetMap ("Dhanmondi 27", "Road 11, Banani"), preferring places inside the chosen district. A found place becomes a 1–5 km circle around it, named after it;
  - a **Pick shifting spot on map** toggle. While it's on, clicking the side-by-side map searches around that point. A 1–5 km slider sets the radius, and a campus or office can be picked instead. While it's off, map clicks never move the search.

  The choice goes into the URL (`?division=Rajshahi&district=Rajshahi&upazila=Matihar`, `&area=Binodpur` on top, `?area=Dhanmondi`, `?near=pin&lat=…&lng=…&radius=2`, or `?near=nsu&radius=2`), and only listings inside it are listed and pinned on the map. Cards name the district outside Dhaka ("Binodpur, Rajshahi").
- **Location picker** (`LocationPickerMap.jsx`, in both listing editors): a Leaflet map that opens on Dhaka (`[23.8103, 90.4125]`, zoom 13). The owner pins the building with "Use my current location" (browser GPS; the map flies there), a click, or by dragging the pin.
  - **Finding the building:** search an address or place in English (the pin drops there; a division, district or upazila just moves the map), switch to **Satellite** to see the actual rooftops, then drag the pin onto the entrance.
  - **Where it is:** under the map the picker shows the pin's upazila, district and division ("Paba, Rajshahi district, Rajshahi division"), or warns when the spot is outside Bangladesh.
  - **Address lookup:** 500 ms after each pin move, the point is looked up with Nominatim (`format=jsonv2`) to fill the area, sub-area and full address.
  - **Area names:** a pin inside a popular area's circle takes that area's name, because Nominatim's Dhaka neighbourhood names are inconsistent (parts of Dhanmondi come back as "Lalmatia"). This keeps owners and tenants on the same names. Elsewhere it uses Nominatim's suburb, neighbourhood or city district, else the village or small town, else the upazila (rural spots OpenStreetMap barely knows). The city falls back to the district. The sub-area comes from the finer quarter or neighbourhood ("Sector 7", "Block M").
  - **Owner edits:** fields the owner typed are kept when the pin moves, with a one-click "Use the map's address".
  - **Publishing:** the form can't be published until the building is pinned.
- **Who posts:** house owners (Owner accounts) post flats and houses for rent, and flats, houses and land for sale. People who rent a bachelor flat and run it as a mess (Bachelor accounts) sublet its free seats or rooms. Both post with photos and a pinned location.
- **Photos:** a new listing needs at least one photo, up to 12. The first is the cover on cards, map pins and My listings; the listing page shows a gallery with a full-screen viewer.
  - **Processing:** every upload is checked by its bytes and re-encoded as JPEG. It's turned upright, capped at 1600 px with a 640 px thumbnail, and its metadata, including a phone's GPS position, is dropped. Images over 40 megapixels are refused.
  - **Serving:** photos are public and cached by browsers for good, because their names never change.
  - **Demo photos:** `seed.py` gives every demo listing drawn stand-ins marked "DEMO PHOTO".
- **Leaflet setup:** `leaflet/dist/leaflet.css` is imported in `main.jsx`. `src/lib/leafletIcons.js` points Leaflet's default marker icon at the bundled images, which Vite would otherwise break. It's loaded with the map components, so Leaflet itself stays out of the main bundle.

## Module 2 — Marketplace (Features 6–10)

All routes are under `/api/marketplace`.

| Method | Path | Access |
| --- | --- | --- |
| GET | `/sale-listings` (also `/search`) | public; filters `property_type`, `min_price`/`max_price`, `min_size`, `min_bedrooms`, `handover_status`, `min_parking`, `verified_title=true`, and the target area (`area_name`, and/or `landmark` or `lat`+`lng` with `radius_km`; see Module 1); `sort` = `distance`, `price_asc`, `price_desc`, `ppsf_asc`, `newest` |
| GET | `/sale-listings/{id}` | public |
| POST · DELETE | `/sale-listings/{id}/photos`, `/sale-listings/{id}/photos/{photo_id}` (and `/cover`) | the seller; same rules as rental photos |
| GET | `/sale-listings/{id}/photos/{photo_id}?size=thumb` | public |
| GET | `/sale-listings/mine` | `OWNER` |
| POST / PUT / DELETE | `/sale-listings[/{id}]` | `OWNER` (own listings); `ADMIN` may delete |
| GET / POST | `/sale-listings/{id}/title-documents` | seller (upload: multipart `doc_type`, `file`); admin can read |
| GET | `/sale-listings/{id}/title-documents/{doc_type}/file` | seller, `ADMIN`, or a buyer with an open or accepted offer |
| GET | `/title-reviews/pending` | `ADMIN` |
| PATCH | `/sale-listings/{id}/title-review` | `ADMIN`; body `{"status": "VERIFIED" \| "REJECTED", "note": "..."}` |
| GET | `/sale-listings/{id}/price-analysis` | public |
| POST | `/offers` | `BUYER` |
| GET | `/offers/mine?side=buyer\|seller` | signed in |
| POST | `/offers/{id}/respond` | the party whose turn it is; body `{"action": "ACCEPT" \| "REJECT" \| "COUNTER" \| "WITHDRAW", "amount", "token_amount", "note"}` |
| GET | `/listings/{id}/visit-slots?date=YYYY-MM-DD` | public (signed-in users also see their own bookings) |
| POST | `/visits` | `BACHELOR_TENANT`, `FAMILY_TENANT`, `BUYER` |
| GET | `/visits/mine` | signed in (as visitor or host) |
| POST | `/visits/{id}/cancel` | visitor or host |

- **Sale listings** live in the same `listings` collection as rentals with `listing_mode: "SALE"`. Each one stores `building.size_sqft` (required), `sale.parking_slots`, `sale.handover_status` (`READY_FLAT` / `UNDER_CONSTRUCTION` with `expected_handover`), an optional `sale.blueprint_url`, and a computed `price_per_sqft`.
- **Title vault:** the seller uploads a `MUTATION_RECORD`, `DEED_SUMMARY` and `TAX_RECEIPT` (JPEG, PNG or PDF, max 5 MB, stored privately under `backend/uploads/title/`). Any upload sets `title_status` to `PENDING`. The public "Verified title" badge only shows once an admin sets it to `VERIFIED`, and a new upload hides it again until the next review.
- **Price analysis** compares price per sq ft with other listings of the same property type within 2 km. If fewer than 3 are found it widens to 5 km, then 10 km. Within ±5% of the average counts as `AT_MARKET`. The EMI calculator runs in the browser.
- **Offers** are `PURCHASE` or `TOKEN_MONEY` (bayna, with a `token_amount` below the price). Each offer keeps a timestamped `history`. A buyer can have only one open offer per property. Accepting an offer marks the property `UNDER_OFFER` and closes every other open offer on it.
- **Visits** are 30-minute slots from 09:00 to 20:00 Dhaka time, up to 30 days ahead. Partial unique indexes on `(host_id, starts_at)` and `(visitor_id, starts_at)` stop the host and the visitor being double-booked, even when two requests arrive at once.

## Module 3 — QR handshake (Features 11–15)

All routes are under `/api/qr-handshake`.

| Method | Path | Access |
| --- | --- | --- |
| POST | `/bookings` | `FAMILY_TENANT` for family flats, `BACHELOR_TENANT` for bachelor flats and seats; body `listing_id`, `move_in_date`, `deposit_amount`, `payment_method`, `payment_reference`, `message` |
| GET | `/bookings/mine?side=tenant\|owner` | signed in |
| POST | `/bookings/{id}/reject` · `/bookings/{id}/cancel` | owner · tenant |
| POST | `/generate/{booking_id}` | owner; approves the request and returns a handshake token |
| POST | `/scan-and-confirm` | tenant; body `{"token": "..."}` |
| GET | `/bookings/{id}/lease.pdf` | owner or tenant |
| GET | `/leases/{booking_id}/verify?sig=...` | public |

- **Escrow ledger:** a request logs the advance deposit with escrow status `PENDING_OWNER`. Approval moves it to `HELD`, the handshake to `RELEASED`, and a rejection or cancellation to `REFUNDED`. Every step is written to `escrow_ledger`. No money moves; this is a record of what the tenant paid outside the app.
- **Handshake token:** an HS256 JWT valid for 24 hours (`QR_TOKEN_TTL_HOURS`). It carries `booking_id`, `property_id`, `owner_id`, `tenant_id`, `agreed_rent` and a single-use `nonce`, and its audience is `barikhujun:qr-handshake`, so it can't be used as a login token. Generating a new code changes the nonce, so older codes stop working.
- **Anti-double-booking:** the scan first burns the nonce with a conditional update, then takes a seat in one atomic update. That update decrements `seats.available_seats` and sets `rental_status: RENTED` when it reaches 0 (whole flats go straight to `RENTED`). If someone else took the last unit first, the losing booking is cancelled and refunded. Once a listing is rented, every other open request on it is cancelled and refunded. A tenant who already rents a place can't request it again (`409`).
- **Scan errors:** a spent or superseded code is a `400` (like an expired one), a code issued to another tenant is a `403`, and losing the race for the last unit is a `409`.
- **Tenant scanner** (`TenantQRScanner.jsx`): before anything is sent, the scanned or pasted text must look like a JWT (three base64url parts) with the handshake audience. It must also be unexpired and name one of the tenant's own approved requests. A confirmation dialog then shows what the code is for (place, owner, rent, move-in date, deposit and expiry), and only *Confirm and lock* calls `/scan-and-confirm`. The server still checks everything again.
- **Lease PDF** (ReportLab) shows the property, both parties' contact and KYC details (ID numbers masked to the last 4 digits), rent and deposit terms, house rules, the escrow record, and a QR stamp. The stamp links to `APP_BASE_URL/verify-lease/{booking_id}?sig=…`, an HMAC-signed public verification page. Files are stored under `backend/uploads/leases/`.

## Module 4 — Lease operations (Features 16–19)

All routes are under `/api/operations`. A lease is a booking confirmed by the QR handshake (`CONFIRMED`), and it becomes `ENDED` on its move-out date. The React **Active Lease** workspace is at `/leases/{booking_id}`, with tabs for bills, the move-in log, repairs, move-out and review. The dashboard's **Leases** tab lists every lease you're part of.

| Method | Path | Access |
| --- | --- | --- |
| GET | `/leases?side=tenant\|owner` · `/leases/{booking_id}` | lease parties |
| POST | `/leases/{booking_id}/photos` | tenant, within 48 h; multipart `room`, `caption`, `files` (1–10 images) |
| GET | `/leases/{booking_id}/photos/{photo_id}` | lease parties |
| POST | `/leases/{booking_id}/move-out-notice` | tenant; body `{"move_out_date", "reason"}` |
| POST | `/admin/process-move-outs?as_of=YYYY-MM-DD` | `ADMIN`; runs the move-out job now (it also runs every 15 min) |
| POST | `/invoices/generate` | lister; body `{"listing_id", "period": "YYYY-MM", "electricity", "gas", "water", "due_date"}` |
| GET | `/invoices?booking_id=` | lease parties |
| POST | `/invoices/{id}/pay` · `/confirm` · `/reject-payment` | tenant · owner · owner |
| GET | `/invoices/{id}/receipt.pdf` | lease parties, once paid |
| POST | `/tickets` | tenant on an active lease; multipart `booking_id`, `category`, `priority`, `title`, `description`, `photos` (≤5) |
| GET | `/tickets?booking_id=&status=` | lease parties |
| POST | `/tickets/{id}/status` · `/tickets/{id}/comments` | owner · either party |
| PUT | `/reviews` | a party to a `CONFIRMED` or `ENDED` lease; body `{"booking_id", "rating": 1-5, "comment"}` |
| GET | `/reviews/user/{user_id}` · `/reviews/lease/{booking_id}` | public · lease parties |

- **Invoices:** generating bills every tenant on the listing for that month. Each invoice has rent (`agreed_rent`), service charge, electricity, gas and water. Shared flats split each whole-flat bill across all `total_seats`, rounding up, like the listing's seat split. The due date defaults to the 10th of the month, or a week from today if the 10th has passed. One invoice per lease per month. A tenant who moved out is still billed for the month they left. Payment flow:
  - The tenant sends a transaction ID (`PAYMENT_SUBMITTED`).
  - The owner either confirms it (`PAID`, receipt PDF) or sends it back with a note (`UNPAID`).
  - The owner can also record a cash payment directly.
- **Move-in log:** the upload window closes 48 hours after move-in day or the handshake, whichever is later. Each photo is stored with the server's timestamp and a SHA-256 fingerprint, and photos can't be edited or deleted.
- **Move-out notice:** the date must be 1 to 2 calendar months from today. The listing shows `reopens_on` straight away. On that date a background job ends the lease and puts the seat back (`available_seats + 1`) or reopens the flat.
- **Repairs:** tickets go `OPEN → IN_PROGRESS → RESOLVED`, one step at a time, and only the owner moves them. Both parties can add notes, and every change is logged with a timestamp.
- **Trust score:** reviews are allowed only between the two parties of a QR-confirmed lease, one per side per lease, and can be updated. On every save the reviewee's score is recalculated as `round(100 × (15 + Σratings) / (5 × (3 + n)))`. That's the average rating blended with three imaginary 5-star reviews, so everyone starts at 100 and one 1-star review gives 80.

## Feature 20 — Fraud detection and dispute arbitration

The admin's **Governance** center (`/admin/governance`, `AdminGovernanceCenter.jsx`) has tabs for the scammer radar, the QR audit trail, the deed vault, the arbitration court and KYC reviews. Tenants, buyers and owners handle their side of a dispute in the dashboard's **Disputes** tab.

| Method | Path | Access |
| --- | --- | --- |
| GET | `/api/admin/governance/overview` | `ADMIN`; counters for the header |
| GET | `/api/admin/governance/alerts?kind=ALERT\|ACTION&status=OPEN\|RESOLVED` | `ADMIN`; `security_audit_logs` |
| POST | `/api/admin/governance/alerts/{id}/resolve` · `/radar/run` | `ADMIN` |
| GET | `/api/admin/governance/qr-handshakes?state=ACTIVE\|EXPIRED\|USED\|NONE` | `ADMIN`; every handshake with its event log |
| POST | `/api/admin/governance/qr-handshakes/{booking_id}/revoke` | `ADMIN`; body `{"reason"}` |
| GET | `/api/admin/governance/deed-vault?status=PENDING\|VERIFIED\|REJECTED\|NOT_SUBMITTED\|ALL` | `ADMIN`; approve or reject with the Feature 7 `title-review` endpoint |
| GET | `/api/admin/governance/disputes?status=` | `ADMIN` |
| POST | `/api/admin/governance/disputes/{id}/rule` | `ADMIN`; body `{"outcome": "REFUND_TENANT" \| "PAY_OWNER" \| "CUSTOM_SPLIT", "claimant_amount", "respondent_amount", "fault": "CLAIMANT" \| "RESPONDENT" \| "NONE", "note"}` |
| POST | `/api/admin/governance/users/{user_id}/ban-scammer` | `ADMIN`; body `{"reason"}` |
| GET | `/api/disputes/eligible` · `/api/disputes/mine` · `/api/disputes/{id}` | tenants and buyers · parties · parties or `ADMIN` |
| POST | `/api/disputes` | tenant or buyer; multipart `type`, `booking_id` or `offer_id`, `claimed_amount`, `description`, `photos` |
| POST | `/api/disputes/{id}/response` | the other party, once; multipart `statement`, `claimed_deduction`, `photos` |
| GET | `/api/disputes/{id}/photos/{photo_id}` · `/api/disputes/{id}/baseline/{photo_id}` | parties or `ADMIN` |
| POST | `/api/rentals/{id}/relist` | lister; puts a rented whole flat back on the market |

- **Scammer radar.** Every QR event is logged to `qr_handshake_logs`: `ISSUED`, `CONFIRMED`, `SCAN_REJECTED` and `REVOKED`, each with a fingerprint of the code's nonce. The radar writes a `HIGH` alert to `security_audit_logs` in two cases:
  - an owner issued 3 or more codes in 48 hours and none of them were scanned;
  - a listing went back on the market (`/relist`, or more free seats) within 48 hours of a QR-confirmed handshake on it.

  Rule 1 runs as a background task after every QR issue and on a 15-minute timer (`RADAR_CHECK_MINUTES`). Rule 2 runs when the listing changes. A repeat hit within 48 hours updates the open alert rather than adding a new one.
- **Disputes.** There are three types:
  - `DEPOSIT_DEDUCTION`: the tenant on a QR-confirmed lease.
  - `FAKE_TO_LET`: the tenant on any booking.
  - `BAYNA_BREACH`: the buyer on an accepted token-money offer.

  The money being argued over is the booking deposit or the bayna, and there is one open dispute per deal. The case file shows the tenant's move-in photos (Feature 17) next to the owner's claim photos.
- **Rulings.** A ruling pays the escrow out as `REFUND_TENANT`, `PAY_OWNER` or `CUSTOM_SPLIT` (the amounts must add up to the escrow).
  - For a booking it's written to the escrow ledger, and `escrow_status` becomes `REFUNDED`, `RELEASED` or `SPLIT`. An unfinished request is also cancelled.
  - For a bayna offer it's recorded on the offer as `settlement`.
  - The party at fault loses 15 trust points. The penalty is stored separately (`trust_penalty`) and subtracted after every review recalculation, so new reviews can't wash it out.
- **Cascading ban** does all of the following:
  - Signs the user out and blocks sign-in.
  - Suspends all their listings, which disappear from every search, detail page, offer and visit endpoint.
  - Cancels their open requests on either side, refunding deposits and revoking any live QR codes.
  - Closes their open offers and cancels their upcoming visits.
  - Resolves their open alerts and records the ban in the audit log.

  Active leases are left alone so current tenants aren't affected. Admin accounts can't be banned.

## Feature 21 — Realtime chat, action cards and notifications

Every listing page has a **Chat with owner** (or seller) button that opens the chat drawer (`ChatDrawer.jsx`). The navbar has a messages button and a notification bell, both with unread counts, and live alerts pop up as toasts in the top-right corner for 6 seconds.

| Method | Path | Access |
| --- | --- | --- |
| WS | `/ws/realtime?token=<login token>` | signed in; the token is checked before the socket is accepted, and browsers may only connect from `ALLOWED_ORIGINS` |
| POST | `/api/chat/send` | signed in; body `{"property_id", "receiver_id", "content"}` (HTML is stripped with nh3; 30 a minute) |
| GET | `/api/chat/threads` · `/api/chat/threads/{property_id}/{other_user_id}` | your conversations with unread counts · one chat's header and quick actions |
| GET | `/api/chat/messages/{property_id}/{other_user_id}?before=&limit=` | your own thread only; newest page first, and reading it marks it read |
| POST | `/api/chat/messages/{property_id}/{other_user_id}/read` | for messages that arrive while the chat is open |
| POST | `/api/chat/rent-offers` · `/api/chat/rent-offers/{id}/respond` | tenant who may rent the place · the party whose turn it is |
| POST | `/api/chat/qr/send` | the listing's owner; body `{"property_id", "tenant_id"}` |
| PATCH | `/api/marketplace/visits/{id}/status` | host: `APPROVED`, `RESCHEDULE_PROPOSED` (with `starts_at`) or `DECLINED`; visitor: `APPROVED` to accept a proposed time |
| GET | `/api/notifications` · PATCH `/api/notifications/{id}/read` · POST `/api/notifications/read-all` | your own notifications |

- **Delivery.** Messages go in `chat_messages` and alerts in `notifications`, both with `is_delivered` and `is_read`. Anything sent to someone offline waits there. On every (re)connection the server first sends an `OFFLINE_SYNC_BUNDLE` with everything still unread, then marks it delivered. The app pops up only what had never been delivered ("You have 3 new messages and 1 scheduled house visit while you were away"), so a reload doesn't show it all again. Unread messages in one thread share one `NEW_MESSAGE` alert.
- **Who can write to whom.** Anyone signed in can message a listing's lister about it. The lister can reply, or write first to someone who booked a visit, asked to rent or made an offer there, but can't cold-message anyone else.
- **Reconnecting.** The app pings every 25 s and reconnects with exponential backoff (up to 30 s), and at once when the browser comes back online or the tab is shown again. A socket refused at the handshake makes the app check its session, so an expired login signs out instead of retrying forever. Open sockets re-check the account every 5 minutes (ban, sign-out everywhere, expiry).
- **Action cards** are chat messages with a `message_type` (`VISIT_REQUEST_CARD`, `OFFER_PROPOSAL_CARD`, `QR_CONFIRMATION_CARD`) and an `action_payload` (`reference_id`, `status`, `scheduled_date`, `scheduled_time`, `proposed_amount`, `qr_token`, `expires_at`, plus details per card). Each one mirrors a real record, and when that record changes both people get `CHAT_CARD_UPDATED` plus a notification. Changes made elsewhere (a deleted listing, a ban) are caught up the next time the chat is read.
  - *Visits:* booking a visit alerts the lister ("📅 New House Visit Scheduled!") and posts the request in the chat. The lister approves it, moves it to another free slot (the visitor then accepts or cancels), or declines it, which frees the slot. Visits keep `status` `BOOKED`/`CANCELLED` for the slot indexes, with the answer in `approval`.
  - *Offers:* a buyer's offer (from the chat or the listing page) appears as a card the seller can accept, counter or decline. Tenants propose a monthly rent the same way (`rent_offers`), logging their advance like a rent request. Whoever didn't make the latest proposal answers it. Accepting a rent proposal creates the rent request at the agreed rent, or updates the tenant's open one.
  - *Handshake QR:* with an open rent request in the chat, the owner can send the Module 3 handshake code into the chat (same secret, 24 h expiry and single-use nonce). The tenant confirms with one tap or scans it with a phone; only the tenant it was issued to can use it. Resending refreshes the card with a new code, and a code shown from the dashboard replaces it. The token is removed from the card as soon as it's confirmed, expired or replaced, and the card then offers the signed lease PDF to both sides.
- **Running it.** The backend needs the `websockets` package (in `requirements.txt`); without it uvicorn refuses every socket. Vite proxies `/ws` like `/api`, and `VITE_WS_URL` points the app at another socket address. Connections are tracked in the process's memory (`app/core/ws_manager.py`), so several workers need a shared broker such as Redis pub/sub first.

## Security hardening

These guardrails apply to every module.

| Layer | Where | What it does |
| --- | --- | --- |
| Rate limiting | `app/core/limiter.py` (slowapi) | Login and register: 5/minute per IP. QR generate and scan: 10/minute per account. Title-deed uploads: 5/hour per account. Automated ID checks: 12/hour per account. Over the limit returns `429` with `Retry-After`. Counters are in memory per process; set `RATE_LIMIT_STORAGE_URI=redis://…` when running several workers. Behind a reverse proxy, forward the client IP (`uvicorn --proxy-headers`), or every visitor counts as one IP. |
| NoSQL injection | `app/core/sanitizers.py` | ASGI middleware rejects (`400`) any query string or JSON body carrying MongoDB operators: `$`-keys, dotted keys, `?a[$ne]=…` smuggling, or values like `"$where"`. Handlers also build every filter from typed values. `parse_object_id` turns bad ids into `400 Invalid ID format`. |
| Mass assignment | every request model extends `RequestModel` (`extra="forbid"`) | Unknown fields are a `422`, so clients can't set `role`, `trust_score`, `kyc_status`, `is_banned`, `status`, `lister_id` and so on. Search endpoints also reject unknown query parameters. |
| Ownership (IDOR) | all routers | Every read and write of a private record includes the owner, tenant, lister or party id in the database filter itself, not just in an earlier read. Someone else's booking, lease, lease PDF, invoice, receipt or repair ticket is a `403`. Another person's KYC file is a `403` decided before any lookup, so it reveals nothing about the account. Offers, visits and disputes answer `404` to non-parties. |
| Race conditions | `qr_handshake.py`, offers, invoices, escrow | Each state change is a single `find_one_and_update` whose filter holds its preconditions. The QR scan consumes the nonce and confirms the booking in one write (filter: tenant, listing, `APPROVED`, exact nonce, unexpired); a replay or a simultaneous second scan matches nothing. The seat is then taken with a second atomic write (`rental_status: AVAILABLE`, `seats.available_seats > 0`); if that fails, the confirmation is reversed and refunded. |
| Uploads | `app/utils/file_security.py` | The type comes from the first bytes: JPEG, PNG or PDF for deeds; JPEG, PNG or WebP for photos and ID cards. Images must fully decode (Pillow). PDFs need `%%EOF` and may not contain JavaScript, launch actions or embedded files. Anything else is a `400`. Files are read in 64 KB chunks with a hard 5 MB cap (`413`), and the whole request body is capped at 55 MB before parsing. Files are saved as `<uuid4>.<ext>`, kept inside `uploads/`, never served statically, and only streamed (`Cache-Control: no-store`) to their owner, an admin, or (for deeds) a buyer with an open or accepted offer. |
| Tokens | `app/core/security.py` | Login and handshake tokens use separate secrets, audiences and an issuer, so neither can be replayed as the other. Every request re-checks `is_banned` and a per-user `token_version`. A banned account gets `403` with `"code": "ACCOUNT_BANNED"` on every request and at sign-in. A ban or `POST /api/auth/logout-all` also bumps the version, which revokes all existing tokens (`401`). Logins for unknown emails still run a bcrypt check, so response timing doesn't reveal which emails exist. |
| Headers and CORS | `app/core/middleware.py`, `main.py` | Every API response sends `nosniff`, `X-Frame-Options: DENY`, a `default-src 'none'` CSP, `Referrer-Policy`, `Permissions-Policy` and `Cache-Control: no-store`. CORS allows only the `ALLOWED_ORIGINS` list (a `*` stops the server from starting), with no credentials and only the needed methods and headers. Set `ENABLE_HSTS=true` behind HTTPS and `ENABLE_API_DOCS=false` in production. |
| XSS | `SafeText` and `clean_text` | Free text is stripped of HTML with nh3 before it's validated and saved: titles, descriptions, addresses, names, notes, reviews, dispute statements, ticket text, room captions and so on. Entity-encoded tags (`&lt;script&gt;`) are caught too, and plain characters like `<` or `&` are kept. |

**Frontend guards.** These are for usability; the API enforces the same rules on every request.

- `ProtectedRoute` checks the session and, where a route sets `allowedRoles`, the role. The lease workspace is for owners and tenants, sale editing for owners, listing management for owners and bachelor tenants, and the governance center for admins. Anyone else sees a short "not available to your account" page.
- An Axios response interceptor (`api/client.js`) ends the session on a `401` from any request that carried a token, or on a `403` marked `ACCOUNT_BANNED`. It drops the stored token, clears the signed-in user and sends them to `/login`, which says why. Other `403`s are ordinary errors and don't sign anyone out. Sign-in and sign-up requests never carry a stored token, so a wrong password stays a form error.

**Frontend hosting.** `vite.config.js` sends `X-Frame-Options: DENY` and `frame-ancestors 'none'` in development, and a `Permissions-Policy` that allows the camera (QR scanning) and geolocation (pinning a listing) for the app itself only. `vite preview` additionally sends a strict CSP (`script-src 'self'`, images over https only, `connect-src` limited to the app and Nominatim). The address lookup calls Nominatim with plain `fetch`, never the API client, so the session token is never sent to it. Whatever serves the built app in production must send the same headers. Floor-plan links must be `https://`, except `localhost` while developing.
