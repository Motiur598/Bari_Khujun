"""Automated ID verification (Feature 1) and its duplicate-account checks (Feature 20).

The card is checked for photo mistakes and read in app/utils/id_card_verifier.py. Readable cards are then compared
with every other account's card in `db.kyc_verifications` (one record per readable attempt: the extracted name and
number, and fingerprints of each side and of the holder's portrait). These records and the comparison scores are
server-side only; users get the plain outcome, and admins see the evidence in the Fraud Detection Center.

Every account's ID number and portrait must be its own. Names are not: different people share names, so a name never
counts towards a match (it's kept only as context for admins).

- Same ID number as another account: revoked at once (30 trust points off), whatever the names.
- The same face, or a near-identical front of the card, on another account: held for an admin (status PENDING),
  because every card of a kind shares one printed design and only a person can be sure.
"""

import asyncio
from datetime import datetime, timezone
from enum import StrEnum

import imagehash
import numpy as np
from bson import ObjectId
from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from rapidfuzz import fuzz
from rapidfuzz import utils as fuzz_utils

from app.core.config import settings
from app.core.database import get_db
from app.schemas.user import KycAutoVerifyResult, KycDocType, KycMistakeOut, KycStatus
from app.services.governance import raise_alert
from app.services.trust import penalize
from app.utils import id_card_verifier as verifier
from app.utils.file_security import read_id_photo, store_bytes

REVOKE_PENALTY_POINTS = 30
# A number this alike backs up a picture match (a digit misread from the same card); on its own it proves nothing,
# since numbers issued close together can differ by a digit.
ID_FUZZY_MIN = 85
CARD_HASH_MAX = 10
CARD_HASH_WITH_COSINE_MAX = 16
CARD_COSINE_MIN = 0.96
# OpenCV's published same-person threshold for SFace cosine similarity.
FACE_SIMILARITY_MIN = 0.363
FACE_HASH_MAX = 8

DUPLICATE_RULE = "KYC_DUPLICATE_ID"
LOOKALIKE_RULE = "KYC_POSSIBLE_DUPLICATE"
KYC_RULES = (DUPLICATE_RULE, LOOKALIKE_RULE)

MESSAGES = {
    "NEEDS_RETRY": "Almost there! Please fix a quick issue with your photo and try again.",
    "VERIFIED": "Your ID has been verified successfully!",
    "PENDING": "Thanks! We need a closer look at your ID. You'll be notified once it's checked.",
    "REVOKED": (
        "Verification revoked: This ID document is already associated with another account or violates our "
        "single-account verification policy."
    ),
}

# Reading a card is heavy (OCR on CPU), and a check plus its record must not interleave with another account's.
_one_at_a_time = asyncio.Lock()


class Outcome(StrEnum):
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"  # held for an admin
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"  # an admin turned it down


def result(kyc_status: str, mistakes: list[KycMistakeOut] = ()) -> KycAutoVerifyResult:
    return KycAutoVerifyResult(verified=kyc_status == "VERIFIED", kyc_status=kyc_status, message=MESSAGES[kyc_status], mistakes=list(mistakes))


def _hamming(a: str, b: str) -> int:
    return int(imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b))


def _cosine(a: list[float], b: list[float]) -> float:
    return float(np.dot(np.asarray(a), np.asarray(b)))


def compare(record: dict, other: dict) -> tuple[list[str], list[str], dict]:
    """Why `record` should be revoked or flagged against another account's `other`, and the scores behind it. Only
    the ID number and the pictures decide; the name similarity is recorded for the admin and nothing else."""
    revoke, flag = [], []
    scores: dict = {}
    mine, theirs = record["extracted_id_number"], other["extracted_id_number"]
    scores["id_similarity"] = round(fuzz.ratio(mine, theirs), 1)
    scores["name_similarity"] = round(fuzz.token_sort_ratio(record["extracted_name"], other["extracted_name"], processor=fuzz_utils.default_process), 1)
    if mine == theirs:
        revoke.append("Same ID number")

    # The front only: card backs (address, barcode) all look alike.
    distance = _hamming(record["front"]["phash"], other["front"]["phash"])
    cosine = _cosine(record["front"]["pixel_signature_256"], other["front"]["pixel_signature_256"])
    scores["front_phash_distance"], scores["front_pixel_cosine"] = distance, round(cosine, 4)
    if distance <= CARD_HASH_MAX or (cosine >= CARD_COSINE_MIN and distance <= CARD_HASH_WITH_COSINE_MAX):
        flag.append("Front of the card looks the same")

    if record.get("face") and other.get("face"):
        face_similarity = _cosine(record["face"]["embedding"], other["face"]["embedding"])
        face_distance = _hamming(record["face"]["phash"], other["face"]["phash"])
        scores["face_similarity"], scores["face_phash_distance"] = round(face_similarity, 4), face_distance
        if face_similarity >= FACE_SIMILARITY_MIN or face_distance <= FACE_HASH_MAX:
            flag.append("Same face as the portrait on this card")
    if flag and mine != theirs and scores["id_similarity"] >= ID_FUZZY_MIN:
        flag.append("Near-identical ID number")
    return revoke, flag, scores


async def _matches(record: dict, user_id: ObjectId) -> list[dict]:
    """Other accounts' cards this one conflicts with. Cards already revoked don't count: if a thief's copy was
    revoked, the real owner verifying later must not be revoked in turn."""
    db = get_db()
    found = []
    others = db.kyc_verifications.find({"user_id": {"$ne": user_id}, "outcome": {"$in": [Outcome.VERIFIED.value, Outcome.FLAGGED.value]}}, {"files": 0})
    async for other in others:
        revoke, flag, scores = compare(record, other)
        if revoke or flag:
            found.append({"user_id": other["user_id"], "record_id": other["_id"], "revoke": revoke, "flag": flag, "scores": scores})
    return found


async def _evidence(record_id: ObjectId, matches: list[dict]) -> dict:
    names = {u["_id"]: u["full_name"] async for u in get_db().users.find({"_id": {"$in": [m["user_id"] for m in matches]}}, {"full_name": 1})}
    return {
        "record_id": str(record_id),
        "matches": [
            {
                "user_id": str(m["user_id"]),
                "full_name": names.get(m["user_id"], "Unknown"),
                "record_id": str(m["record_id"]),
                "reasons": m["revoke"] + m["flag"],
                **m["scores"],
            }
            for m in matches
        ],
    }


async def auto_verify(user: dict, doc_type: KycDocType, front: UploadFile, back: UploadFile) -> KycAutoVerifyResult:
    front_bytes, front_type = await read_id_photo(front)
    back_bytes, back_type = await read_id_photo(back)
    unopenable = [KycMistakeOut(side=side, code="NOT_AN_IMAGE", message=verifier.MISTAKES["NOT_AN_IMAGE"])
                  for side, kind in (("front", front_type), ("back", back_type)) if kind is None]
    if unopenable:
        return result("NEEDS_RETRY", unopenable)

    async with _one_at_a_time:
        reading = await run_in_threadpool(verifier.read_card, front_bytes, back_bytes, doc_type.value, user["full_name"])
        if reading.mistakes:
            # Nothing is kept from a photo that needs retaking, and there's no penalty for trying again.
            return result("NEEDS_RETRY", [KycMistakeOut(side=m.side, code=m.code, message=m.message) for m in reading.mistakes])

        db = get_db()
        now = datetime.now(timezone.utc)
        folder = settings.upload_dir / "kyc" / str(user["_id"])
        files = {
            "front": await store_bytes(front_bytes, front_type, folder, front.filename),
            "back": await store_bytes(back_bytes, back_type, folder, back.filename),
        }
        record = {
            "_id": ObjectId(),
            "user_id": user["_id"],
            "doc_type": doc_type.value,
            "extracted_name": reading.extracted_name,
            "extracted_id_number": verifier.normalize_id(reading.extracted_id_number),
            "name_similarity": reading.name_similarity,
            "front": reading.front,
            "back": reading.back,
            "face": reading.face,
            "files": files,
            "created_at": now,
        }
        matches = await _matches(record, user["_id"])
        revoking = [m for m in matches if m["revoke"]]
        outcome = Outcome.REVOKED if revoking else Outcome.FLAGGED if matches else Outcome.VERIFIED
        await db.kyc_verifications.insert_one({**record, "outcome": outcome.value, "matches": [
            {"user_id": m["user_id"], "record_id": m["record_id"], "reasons": m["revoke"] + m["flag"]} for m in matches
        ]})

    # The card itself is kept like any ID upload, so admins can look at it.
    document = {
        "doc_type": doc_type.value,
        "doc_number": reading.extracted_id_number,
        **files["front"],
        "back": files["back"],
        "verification_id": record["_id"],
        "uploaded_at": now,
    }
    documents = [d for d in user.get("kyc_documents", []) if d["doc_type"] != doc_type.value] + [document]
    status = {Outcome.VERIFIED: KycStatus.VERIFIED, Outcome.FLAGGED: KycStatus.PENDING, Outcome.REVOKED: KycStatus.REVOKED}[outcome]
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"kyc_documents": documents, "kyc_status": status.value, "kyc_review_note": None, "updated_at": now}},
    )

    if outcome == Outcome.REVOKED:
        await penalize(user["_id"], REVOKE_PENALTY_POINTS)
        evidence = await _evidence(record["_id"], matches)
        other = evidence["matches"][0]
        await raise_alert(
            DUPLICATE_RULE, user["_id"],
            f"Verification revoked automatically: the ID card matches {other['full_name']}'s ({', '.join(revoking[0]['revoke']).lower()}).",
            "HIGH", **evidence,
        )
        return result("REVOKED")
    if outcome == Outcome.FLAGGED:
        evidence = await _evidence(record["_id"], matches)
        other = evidence["matches"][0]
        await raise_alert(
            LOOKALIKE_RULE, user["_id"],
            f"ID card held for review: it looks like {other['full_name']}'s ({', '.join(matches[0]['flag']).lower()}).",
            "HIGH", **evidence,
        )
        return result("PENDING")
    return result("VERIFIED")


async def set_latest_outcome(user_id: ObjectId, outcome: Outcome) -> None:
    """Keep the user's newest card record in step with an admin's decision, so later comparisons use it (or don't)."""
    latest = await get_db().kyc_verifications.find_one({"user_id": user_id}, {"_id": 1}, sort=[("created_at", -1)])
    if latest:
        await get_db().kyc_verifications.update_one({"_id": latest["_id"]}, {"$set": {"outcome": outcome.value}})
