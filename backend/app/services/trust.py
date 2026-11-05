"""Trust score bookkeeping shared by reviews (Feature 19) and arbitration rulings (Feature 20)."""

from bson import ObjectId

from app.core.database import get_db
from app.schemas.operations import trust_score_from

FAULT_PENALTY_POINTS = 15


async def recalculate_trust(user_id: ObjectId) -> int:
    """Score from reviews, minus any penalties from lost disputes, floored at 0."""
    db = get_db()
    ratings = [r["rating"] async for r in db.reviews.find({"reviewee_id": user_id}, {"rating": 1})]
    user = await db.users.find_one({"_id": user_id}, {"trust_penalty": 1})
    penalty = (user or {}).get("trust_penalty", 0)
    score = max(0, trust_score_from(ratings) - penalty)
    await db.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "trust_score": score,
                "review_count": len(ratings),
                "rating_average": round(sum(ratings) / len(ratings), 2) if ratings else None,
            }
        },
    )
    return score


async def penalize(user_id: ObjectId, points: int = FAULT_PENALTY_POINTS) -> int:
    # Penalties are stored separately so a later review recalculation can't wash them out.
    await get_db().users.update_one({"_id": user_id}, {"$inc": {"trust_penalty": points}})
    return await recalculate_trust(user_id)
