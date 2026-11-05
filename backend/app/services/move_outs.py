"""Ends leases whose move-out date has arrived and puts the seat or flat back on the market."""

import asyncio
import logging
from datetime import date, datetime, timezone

from app.core.database import get_db
from app.schemas.booking import BookingStatus
from app.schemas.marketplace import DHAKA_TZ
from app.schemas.rental import ListingCategory, RentalStatus
from app.services.listings import change_room_seats

logger = logging.getLogger(__name__)


async def process_due_move_outs(as_of: date | None = None) -> int:
    """End every active lease with a move-out date on or before `as_of` (default: today in Dhaka)."""
    as_of = as_of or datetime.now(timezone.utc).astimezone(DHAKA_TZ).date()
    db = get_db()
    ended = 0
    due = db.bookings.find(
        {"status": BookingStatus.CONFIRMED.value, "move_out.move_out_date": {"$lte": as_of.isoformat()}}
    )
    async for booking in due:
        now = datetime.now(timezone.utc)
        # Guarding on CONFIRMED makes this safe to run twice (or from two workers at once).
        result = await db.bookings.update_one(
            {"_id": booking["_id"], "status": BookingStatus.CONFIRMED.value},
            {"$set": {"status": BookingStatus.ENDED.value, "ended_at": now, "updated_at": now}},
        )
        if result.modified_count == 0:
            continue
        ended += 1
        listing = await db.listings.find_one({"_id": booking["listing_id"]}, {"category": 1})
        if listing is None:
            continue
        if (unit := booking.get("unit")) is not None:
            # A sublet's seat or room: give its seats back, never more than the room has.
            reopen = change_room_seats(unit["room_id"], unit["seats"], now)
        else:
            fields: dict = {"rental_status": RentalStatus.AVAILABLE.value, "updated_at": now}
            if listing["category"] == ListingCategory.BACHELOR_SEAT:
                # Give the seat back, never exceeding the flat's total.
                fields["seats.available_seats"] = {
                    "$min": [{"$add": ["$seats.available_seats", 1]}, "$seats.total_seats"]
                }
            reopen = [{"$set": fields}]
        await db.listings.update_one(
            {"_id": booking["listing_id"]},
            [
                *reopen,
                {
                    "$set": {
                        "upcoming_vacancies": {
                            "$filter": {
                                "input": {"$ifNull": ["$upcoming_vacancies", []]},
                                "cond": {"$ne": ["$$this.booking_id", booking["_id"]]},
                            }
                        }
                    }
                },
            ],
        )
    return ended


async def run_move_out_scheduler(interval_minutes: int) -> None:
    while True:
        try:
            ended = await process_due_move_outs()
            if ended:
                logger.info("Ended %d lease(s) at their move-out date", ended)
        except Exception:
            logger.exception("Move-out check failed")
        await asyncio.sleep(interval_minutes * 60)
