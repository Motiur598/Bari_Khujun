"""Test helpers: accounts, listings and bookings built through the public API, plus sample files.

Imported by conftest.py after it has set up the test configuration (the app reads its settings on import).
"""

import asyncio
import io
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from bson import ObjectId
from PIL import Image

from app.core.security import hash_password

DHAKA = timezone(timedelta(hours=6))
PASSWORD = "correct-horse-battery"


@dataclass
class Account:
    id: str
    token: str
    email: str
    role: str
    full_name: str

    @property
    def oid(self) -> ObjectId:
        return ObjectId(self.id)

    @property
    def auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}


def jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (196, 172, 140)).save(buffer, "JPEG")
    return buffer.getvalue()


def location(area_name: str = "Azimpur", lng: float = 90.3855, lat: float = 23.7275, address: str = "House 12, Road 3",
             sub_area: str | None = None) -> dict:
    return {
        "city": "Dhaka",
        "area_name": area_name,
        "sub_area": sub_area,
        "formatted_address": address,
        "geo": {"type": "Point", "coordinates": [lng, lat]},
    }


def rental_payload(category: str = "BACHELOR_SEAT", title: str = "Seat in a shared room near Dhaka University",
                   place: dict | None = None, seats: dict | None = None, rent: int = 12000) -> dict:
    return {
        "category": category,
        "title": title,
        "description": "",
        "location": place or location(),
        "pricing": {"base_rent": rent, "service_charge": 900, "deposit_months": 1, "utility_estimate": 1200, "maid_estimate": 0},
        "building": {"floor_level": 2, "total_floors": 5, "has_elevator": False, "has_generator_backup": True, "bedrooms": 2, "bathrooms": 1},
        "house_rules": {"gate_closing_time": "23:00", "guest_policy": "NOT_ALLOWED", "smoking_allowed": False, "meter_type": "PREPAID"},
        "seats": seats,
        "available_from": (date.today() + timedelta(days=1)).isoformat(),
    }


class Factory:
    """Builds accounts, listings and bookings through the public API, the way a real client would."""

    def __init__(self, client: httpx.AsyncClient, db):
        self.client = client
        self.db = db

    async def account(self, role: str, name: str | None = None) -> Account:
        full_name = name or f"Test {role.title().replace('_', ' ')}"
        email = f"{role.lower()}.{uuid.uuid4().hex[:10]}@example.com"
        if role == "ADMIN":
            # Admins can't self-register; they're created server-side (like app.scripts.create_admin).
            now = datetime.now(timezone.utc)
            await self.db.users.insert_one(
                {
                    "full_name": full_name, "email": email, "phone": "+8801700000001",
                    "password_hash": hash_password(PASSWORD), "role": "ADMIN", "kyc_status": "VERIFIED",
                    "kyc_documents": [], "kyc_review_note": None, "trust_score": 100, "is_banned": False,
                    "token_version": 0, "created_at": now, "updated_at": now,
                }
            )
            response = await self.client.post("/auth/login", json={"email": email, "password": PASSWORD})
        else:
            response = await self.client.post(
                "/auth/register",
                json={"full_name": full_name, "email": email, "phone": "+8801700000000", "password": PASSWORD, "role": role},
            )
        assert response.status_code in (200, 201), response.text
        body = response.json()
        return Account(id=body["user"]["id"], token=body["access_token"], email=email, role=role, full_name=full_name)

    async def seat_listing(self, owner: Account, *, total_seats: int = 3, available_seats: int = 1) -> str:
        payload = rental_payload(
            seats={
                "total_seats": total_seats,
                "available_seats": available_seats,
                "flatmates": [{"display_name": "Rafi", "occupation_type": "STUDENT", "institution": "DU", "habits": ["QUIET"]}],
            }
        )
        response = await self.client.post("/rentals", json=payload, headers=owner.auth)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    async def flat_listing(self, owner: Account, area_name: str, lng: float, lat: float, sub_area: str | None = None,
                           rent: int = 12000) -> str:
        place = location(area_name, lng, lat, sub_area=sub_area)
        payload = rental_payload(category="FAMILY_FLAT", title=f"Family flat in {area_name}", place=place, rent=rent)
        response = await self.client.post("/rentals", json=payload, headers=owner.auth)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    async def sale_listing(self, owner: Account, area_name: str, lng: float, lat: float) -> str:
        payload = {
            "property_type": "APARTMENT",
            "title": f"Apartment for sale in {area_name}",
            "location": location(area_name, lng, lat),
            "building": {"floor_level": 3, "total_floors": 8, "bedrooms": 3, "bathrooms": 2, "size_sqft": 1400},
            "sale": {"asking_price": 14_000_000, "handover_status": "READY_FLAT"},
        }
        response = await self.client.post("/marketplace/sale-listings", json=payload, headers=owner.auth)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    @staticmethod
    def move_in_date() -> date:
        return datetime.now(DHAKA).date() + timedelta(days=7)

    async def sublet_listing(self, tenant: Account, sublet: dict, bedrooms: int = 3) -> dict:
        """A bachelor tenant's sublet of a seat or rooms. Returns the listing."""
        payload = {**rental_payload(title="Subletting in my flat near Dhaka University"), "sublet": sublet}
        payload["building"]["bedrooms"] = bedrooms
        response = await self.client.post("/rentals", json=payload, headers=tenant.auth)
        assert response.status_code == 201, response.text
        return response.json()

    async def request_to_rent(self, tenant: Account, listing_id: str, room_id: str | None = None, whole_room: bool = False) -> httpx.Response:
        """A rent request; on a sublet, for `room_id` (or, for a single-seat sublet, its seat)."""
        return await self.client.post(
            "/qr-handshake/bookings",
            json={
                "listing_id": listing_id,
                "move_in_date": self.move_in_date().isoformat(),
                "deposit_amount": 4000,
                "payment_method": "BKASH",
                "payment_reference": f"TRX{uuid.uuid4().hex[:8].upper()}",
                **({"room_id": room_id, "whole_room": whole_room} if room_id else {}),
            },
            headers=tenant.auth,
        )

    async def approved_booking(self, owner: Account, tenant: Account, listing_id: str, room_id: str | None = None,
                               whole_room: bool = False) -> tuple[str, str]:
        """A rent request the owner has approved. Returns (booking id, handshake QR token)."""
        response = await self.request_to_rent(tenant, listing_id, room_id, whole_room)
        assert response.status_code == 201, response.text
        booking_id = response.json()["id"]
        response = await self.client.post(f"/qr-handshake/generate/{booking_id}", headers=owner.auth)
        assert response.status_code == 200, response.text
        return booking_id, response.json()["token"]

    async def scan(self, tenant: Account, token: str) -> httpx.Response:
        return await self.client.post("/qr-handshake/scan-and-confirm", json={"token": token}, headers=tenant.auth)

    async def confirmed_lease(self, owner: Account, tenant: Account) -> str:
        """A QR-confirmed tenancy with its lease PDF generated. Returns the booking id."""
        listing_id = await self.seat_listing(owner)
        booking_id, token = await self.approved_booking(owner, tenant, listing_id)
        response = await self.scan(tenant, token)
        assert response.status_code == 200, response.text
        return booking_id


class SocketRejected(Exception):
    def __init__(self, code: int | None):
        super().__init__(f"WebSocket refused with close code {code}")
        self.code = code


class RealtimeSocket:
    """A client for /ws/realtime that drives the ASGI app directly, on the test's own event loop.

    httpx has no WebSocket support, and Starlette's TestClient runs the app on a second loop in another thread,
    where the shared Motor client can't be used. This speaks the ASGI WebSocket messages itself instead.
    """

    def __init__(self, app, token: str, origin: str | None = None):
        self.app = app
        self.token = token
        self.origin = origin
        self._to_app: asyncio.Queue = asyncio.Queue()
        self._from_app: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "RealtimeSocket":
        headers = [(b"host", b"testserver")]
        if self.origin:
            headers.append((b"origin", self.origin.encode()))
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "scheme": "ws",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "root_path": "",
            "path": "/ws/realtime",
            "raw_path": b"/ws/realtime",
            "query_string": urlencode({"token": self.token}).encode(),
            "headers": headers,
            "subprotocols": [],
            "state": {},
        }
        await self._to_app.put({"type": "websocket.connect"})
        self._task = asyncio.create_task(self.app(scope, self._to_app.get, self._from_app.put))
        first = await asyncio.wait_for(self._from_app.get(), 5)
        if first["type"] == "websocket.close":
            await asyncio.wait_for(self._task, 5)
            raise SocketRejected(first.get("code"))
        assert first["type"] == "websocket.accept", first
        return self

    async def receive_json(self, timeout: float = 5) -> dict:
        message = await asyncio.wait_for(self._from_app.get(), timeout)
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def receive_until(self, event_type: str, timeout: float = 5) -> dict:
        """The next event of `event_type`, skipping others (presence updates, echoes) on the way."""
        while True:
            event = await self.receive_json(timeout)
            if event["type"] == event_type:
                return event

    def drain(self) -> list[dict]:
        events = []
        while not self._from_app.empty():
            message = self._from_app.get_nowait()
            if message["type"] == "websocket.send":
                events.append(json.loads(message["text"]))
        return events

    async def send_json(self, data: dict) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def __aexit__(self, *exc) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(self._task, 5)
