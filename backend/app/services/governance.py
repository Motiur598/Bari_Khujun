"""Scammer radar and audit logging (Feature 20).

Two collections:
- `qr_handshake_logs`: one row per QR event (issued, confirmed, scan rejected, revoked), the admin's audit trail.
- `security_audit_logs`: radar alerts (kind ALERT, open until an admin resolves them) and admin actions (kind ACTION).
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.core.database import get_db

logger = logging.getLogger(__name__)

RADAR_WINDOW = timedelta(hours=48)
QR_SPAM_THRESHOLD = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def nonce_fingerprint(nonce: str) -> str:
    """Short hash of a QR nonce, so the audit trail can correlate events without storing usable secrets."""
    return hashlib.sha256(nonce.encode()).hexdigest()[:12]


async def log_qr_event(booking: dict, event: str, nonce: str | None = None, detail: str | None = None) -> None:
    await get_db().qr_handshake_logs.insert_one(
        {
            "booking_id": booking["_id"],
            "listing_id": booking["listing_id"],
            "owner_id": booking["owner_id"],
            "tenant_id": booking["tenant_id"],
            "event": event,
            "nonce_fp": nonce_fingerprint(nonce) if nonce else None,
            "detail": detail,
            "at": _now(),
        }
    )


async def log_action(admin: dict, action: str, message: str, subject_user_id: ObjectId | None = None, **evidence) -> None:
    now = _now()
    await get_db().security_audit_logs.insert_one(
        {
            "kind": "ACTION",
            "severity": "INFO",
            "rule": action,
            "subject_user_id": subject_user_id,
            "message": message,
            "evidence": evidence,
            "actor": {"id": admin["_id"], "full_name": admin["full_name"]},
            "status": "RESOLVED",
            "created_at": now,
            "updated_at": now,
        }
    )


async def raise_alert(rule: str, subject_user_id: ObjectId, message: str, severity: str = "HIGH", **evidence) -> bool:
    """Log an alert unless the same rule already has an open alert for this user inside the window.

    A repeat hit refreshes the open alert's evidence instead, so admins see one row per incident.
    Returns True when a new alert was created.
    """
    db = get_db()
    now = _now()
    user = await db.users.find_one({"_id": subject_user_id}, {"full_name": 1, "role": 1})
    existing = await db.security_audit_logs.find_one_and_update(
        {
            "kind": "ALERT",
            "rule": rule,
            "subject_user_id": subject_user_id,
            "status": "OPEN",
            "created_at": {"$gte": now - RADAR_WINDOW},
        },
        {"$set": {"message": message, "evidence": evidence, "updated_at": now}, "$inc": {"hits": 1}},
    )
    if existing is not None:
        return False
    await db.security_audit_logs.insert_one(
        {
            "kind": "ALERT",
            "severity": severity,
            "rule": rule,
            "subject_user_id": subject_user_id,
            "subject": {"id": subject_user_id, "full_name": (user or {}).get("full_name", "Unknown"), "role": (user or {}).get("role")},
            "message": message,
            "evidence": evidence,
            "hits": 1,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
        }
    )
    logger.warning("Radar alert %s for user %s: %s", rule, subject_user_id, message)
    return True


async def check_qr_spam(owner_id: ObjectId) -> bool:
    """Rule 1: an owner issued 3+ QR codes in 48 hours that nobody has confirmed."""
    since = _now() - RADAR_WINDOW
    events = await get_db().qr_handshake_logs.find(
        {"owner_id": owner_id, "event": {"$in": ["ISSUED", "CONFIRMED"]}, "at": {"$gte": since}},
        {"event": 1, "nonce_fp": 1, "booking_id": 1},
    ).to_list(None)
    confirmed = {e["nonce_fp"] for e in events if e["event"] == "CONFIRMED"}
    unconfirmed = [e for e in events if e["event"] == "ISSUED" and e["nonce_fp"] not in confirmed]
    if len(unconfirmed) < QR_SPAM_THRESHOLD:
        return False
    bookings = sorted({str(e["booking_id"]) for e in unconfirmed})
    return await raise_alert(
        "QR_SPAM",
        owner_id,
        f"Issued {len(unconfirmed)} handshake QR codes in 48 hours with none confirmed "
        f"({len(bookings)} different request{'s' if len(bookings) != 1 else ''}).",
        unconfirmed_codes=len(unconfirmed),
        booking_ids=bookings,
    )


async def check_rapid_relist(listing: dict, owner_id: ObjectId) -> bool:
    """Rule 2: a listing went back on the market within 48 hours of a QR-confirmed handshake on it."""
    since = _now() - RADAR_WINDOW
    recent = await get_db().bookings.find(
        {"listing_id": listing["_id"], "status": "CONFIRMED", "confirmed_at": {"$gte": since}},
        {"_id": 1, "tenant": 1, "confirmed_at": 1},
    ).to_list(None)
    if not recent:
        return False
    return await raise_alert(
        "RAPID_RELIST",
        owner_id,
        f"Relisted “{listing['title']}” as available within 48 hours of {len(recent)} QR-confirmed "
        f"handshake{'s' if len(recent) != 1 else ''}.",
        listing_id=str(listing["_id"]),
        listing_title=listing["title"],
        booking_ids=[str(b["_id"]) for b in recent],
        tenants=[b["tenant"]["full_name"] for b in recent],
    )


async def sweep() -> int:
    """Re-check every owner who issued a QR code in the last 48 hours. Returns the number of new alerts."""
    since = _now() - RADAR_WINDOW
    owners = await get_db().qr_handshake_logs.distinct("owner_id", {"event": "ISSUED", "at": {"$gte": since}})
    created = 0
    for owner_id in owners:
        created += await check_qr_spam(owner_id)
    return created


async def run_radar_scheduler(interval_minutes: int) -> None:
    while True:
        try:
            created = await sweep()
            if created:
                logger.info("Scammer radar raised %d new alert(s)", created)
        except Exception:
            logger.exception("Scammer radar sweep failed")
        await asyncio.sleep(interval_minutes * 60)
