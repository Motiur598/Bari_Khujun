import logging
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import GEOSPHERE
from pymongo.errors import OperationFailure

from app.core.config import settings
from app.core.sanitizers import parse_object_id  # noqa: F401  (re-exported for the routers)

logger = logging.getLogger(__name__)
INDEX_NOT_FOUND = 27  # MongoDB error code

_client: AsyncIOMotorClient | None = None


async def migrate_listing_locations(db: AsyncIOMotorDatabase) -> int:
    """Fold listings saved before the location upgrade (an `address` beside a bare GeoJSON `location`) into the
    `location: {city, area_name, formatted_address, geo}` shape. Returns how many moved; 0 once all have."""
    result = await db.listings.update_many(
        {"address": {"$exists": True}},
        [
            # $mergeObjects swaps `location` wholesale; a plain $set would merge into the old point's fields.
            {
                "$replaceWith": {
                    "$mergeObjects": [
                        "$$ROOT",
                        {
                            "location": {
                                "city": "$address.city",
                                "area_name": "$address.area",
                                "formatted_address": "$address.line",
                                "geo": "$location",
                            }
                        },
                    ]
                }
            },
            {"$unset": "address"},
        ],
    )
    if result.modified_count:
        logger.info("Moved %d listing(s) to the new location shape", result.modified_count)
    return result.modified_count


async def connect_to_mongo() -> None:
    global _client
    _client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    # Fail fast at startup if MongoDB is unreachable.
    await _client.admin.command("ping")
    db = get_db()
    await db.users.create_index("email", unique=True)
    # Listings used to keep a bare GeoJSON point at `location`; it now lives at `location.geo`. The old index would
    # reject the new shape (`location` is no longer a GeoJSON point), so it goes before older listings are moved.
    try:
        await db.listings.drop_index("location_2dsphere")
    except OperationFailure as error:
        if error.code != INDEX_NOT_FOUND:  # already gone, possibly dropped by another worker starting at the same time
            raise
    await migrate_listing_locations(db)
    await db.listings.create_index([("location.geo", GEOSPHERE)])
    # Area search is a case-insensitive whole-word regex; MongoDB can answer it by scanning this index's keys.
    await db.listings.create_index("location.area_name")
    await db.listings.create_index([("category", 1), ("effective_rent", 1)])
    await db.listings.create_index("lister_id")
    # Partial unique indexes enforce "one open item" and "no double-booked slot" rules atomically.
    await db.offers.create_index(
        [("listing_id", 1), ("buyer_id", 1)], unique=True, partialFilterExpression={"is_open": True},
        name="one_open_offer_per_buyer",
    )
    await db.offers.create_index("seller_id")
    await db.visit_slots.create_index(
        [("host_id", 1), ("starts_at", 1)], unique=True, partialFilterExpression={"status": "BOOKED"},
        name="host_slot_unique",
    )
    await db.visit_slots.create_index(
        [("visitor_id", 1), ("starts_at", 1)], unique=True, partialFilterExpression={"status": "BOOKED"},
        name="visitor_slot_unique",
    )
    await db.bookings.create_index(
        [("listing_id", 1), ("tenant_id", 1)], unique=True, partialFilterExpression={"is_open": True},
        name="one_open_booking_per_tenant",
    )
    await db.bookings.create_index("owner_id")
    await db.bookings.create_index("tenant_id")
    await db.invoices.create_index([("booking_id", 1), ("period", 1)], unique=True, name="one_invoice_per_month")
    await db.invoices.create_index("owner_id")
    await db.invoices.create_index("tenant_id")
    await db.maintenance_tickets.create_index("booking_id")
    await db.maintenance_tickets.create_index([("owner_id", 1), ("status", 1)])
    await db.reviews.create_index([("booking_id", 1), ("reviewer_id", 1)], unique=True, name="one_review_per_lease_side")
    await db.reviews.create_index("reviewee_id")
    await db.disputes.create_index(
        "subject_key", unique=True, partialFilterExpression={"is_open": True}, name="one_open_dispute_per_deal"
    )
    await db.disputes.create_index([("claimant_id", 1), ("respondent_id", 1)])
    await db.qr_handshake_logs.create_index([("owner_id", 1), ("at", -1)])
    await db.qr_handshake_logs.create_index("booking_id")
    await db.security_audit_logs.create_index([("kind", 1), ("status", 1), ("created_at", -1)])
    await db.security_audit_logs.create_index("subject_user_id")
    # Chat: a thread's history, a user's unread inbox, the threads list (either side of a message), and cards by record.
    await db.chat_messages.create_index([("thread_id", 1), ("_id", -1)])
    await db.chat_messages.create_index([("receiver_id", 1), ("is_read", 1)])
    await db.chat_messages.create_index([("sender_id", 1), ("_id", -1)])
    await db.chat_messages.create_index("action_payload.reference_id", sparse=True)
    await db.notifications.create_index([("recipient_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("recipient_id", 1), ("is_read", 1)])
    # New messages in a thread update one unread notification instead of stacking up a new one each.
    await db.notifications.create_index(
        [("recipient_id", 1), ("metadata.thread_id", 1)], unique=True,
        partialFilterExpression={"type": "NEW_MESSAGE", "is_read": False}, name="one_unread_message_alert_per_thread",
    )
    await db.rent_offers.create_index(
        [("listing_id", 1), ("tenant_id", 1)], unique=True, partialFilterExpression={"is_open": True},
        name="one_open_rent_offer_per_tenant",
    )
    await db.rent_offers.create_index("owner_id")


async def close_mongo_connection() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_db() -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("MongoDB client is not initialised")
    return _client.get_default_database()


async def find_for_party(
    collection: AsyncIOMotorCollection,
    query: dict,
    user_id: ObjectId,
    label: str,
    party_fields: tuple[str, ...] = ("owner_id", "tenant_id"),
) -> dict:
    """Load a record the user is a party to. `query` must contain `_id`.

    Ownership is part of the query filter itself. Only on a miss does a second lookup (by id, party fields only)
    decide the error: the record belongs to someone else (403), or there's no such record for this user (404).
    """
    doc = await collection.find_one({**query, "$or": [{field: user_id} for field in party_fields]})
    if doc is not None:
        return doc
    other = await collection.find_one({"_id": query["_id"]}, {field: 1 for field in party_fields})
    if other is not None and all(other.get(field) != user_id for field in party_fields):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"You don't have access to this {label}")
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label[0].upper()}{label[1:]} not found")


def serialize_doc(value: Any) -> Any:
    """Make a Mongo document API-safe: `_id` becomes `id` and every ObjectId becomes a str."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, list):
        return [serialize_doc(item) for item in value]
    if isinstance(value, dict):
        return {("id" if key == "_id" else key): serialize_doc(item) for key, item in value.items()}
    return value
