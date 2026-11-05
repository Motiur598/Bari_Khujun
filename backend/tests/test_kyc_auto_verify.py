"""Automated ID verification (Feature 1) and duplicate-account detection (Feature 20).

Photo mistakes come back in plain words with no penalty; a card whose number belongs to another account is revoked;
a card with another account's face or front is held for an admin. The response never says how any of it was
decided, and admins see the evidence in the Fraud Detection Center.
"""

import json

import pytest
from bson import ObjectId
from kyc_support import FakeCards, card_photo

from app.utils import id_card_verifier as verifier

pytestmark = pytest.mark.anyio

# Words that would give away how the check works.
SECRETS = ("phash", "dhash", "signature", "pixel", "similarity", "distance", "hamming", "cosine", "bbox", "threshold",
           "embedding", "laplacian", "user_id", "record_id", "score")


@pytest.fixture
async def cards(monkeypatch, db) -> FakeCards:
    # Every account's card is compared with every other's, so each test starts with none on file.
    await db.kyc_verifications.delete_many({})
    fake = FakeCards()
    monkeypatch.setattr(verifier, "read_card", fake)
    return fake


async def verify(client, account, front: bytes | None = None, back: bytes | None = None, doc_type: str = "NID", seed: int = 1):
    return await client.post(
        "/auth/kyc-auto-verify",
        data={"doc_type": doc_type},
        files={
            "front": ("front.jpg", front if front is not None else card_photo(seed), "image/jpeg"),
            "back": ("back.jpg", back if back is not None else card_photo(500 + seed), "image/jpeg"),
        },
        headers=account.auth,
    )


def assert_nothing_given_away(response) -> None:
    body = response.text.lower()
    assert not any(word in body for word in SECRETS), body
    assert set(response.json()) == {"verified", "kyc_status", "message", "mistakes"}


class TestPhotoMistakes:
    async def test_mistakes_come_back_in_plain_words_and_nothing_is_kept(self, client, make, db, cards, upload_root):
        owner = await make.account("OWNER")
        response = await verify(client, owner, front=card_photo(1, blur=8), back=card_photo(2, dark=True))

        assert response.status_code == 200
        body = response.json()
        assert (body["verified"], body["kyc_status"]) == (False, "NEEDS_RETRY")
        assert body["message"] == "Almost there! Please fix a quick issue with your photo and try again."
        assert [(m["side"], m["code"]) for m in body["mistakes"]] == [("front", "BLURRY"), ("back", "DARK")]
        assert body["mistakes"][0]["message"].startswith("The photo is too blurry.")
        assert_nothing_given_away(response)
        stored = await db.users.find_one({"_id": owner.oid})
        assert (stored["kyc_status"], stored["kyc_documents"], stored["trust_score"]) == ("NOT_SUBMITTED", [], 100)
        assert await db.kyc_verifications.count_documents({"user_id": owner.oid}) == 0
        assert not (upload_root / "kyc" / owner.id).exists()

    async def test_a_profile_name_typo_and_a_missing_portrait_are_mistakes_too(self, client, make, cards):
        owner = await make.account("OWNER", name="Abdur Rahim")
        cards.show("KARIM HOSSAIN", "1990123456")
        assert [m["code"] for m in (await verify(client, owner)).json()["mistakes"]] == ["NAME_MISMATCH"]
        cards.show("MD. ABDUR RAHIM", "1990123456", face_seed=None)
        assert [m["code"] for m in (await verify(client, owner)).json()["mistakes"]] == ["NO_PHOTO"]
        cards.show("MD. ABDUR RAHIM", "1990123456")
        assert (await verify(client, owner)).json()["kyc_status"] == "VERIFIED"

    async def test_files_that_are_not_photos_are_turned_away(self, client, make, db, cards, upload_root):
        owner = await make.account("OWNER")
        response = await verify(client, owner, front=b"<?php echo 'probe'; ?>" * 20, back=b"%PDF-1.4 not a photo")

        body = response.json()
        assert (response.status_code, body["kyc_status"]) == (200, "NEEDS_RETRY")
        assert {(m["side"], m["code"]) for m in body["mistakes"]} == {("front", "NOT_AN_IMAGE"), ("back", "NOT_AN_IMAGE")}
        assert cards.calls == 0
        assert (await db.users.find_one({"_id": owner.oid}))["kyc_documents"] == []
        assert not (upload_root / "kyc" / owner.id).exists()


class TestNameCheck:
    def test_titles_dont_make_different_people_look_alike(self):
        assert verifier.name_similarity("MD MOTIUR RAHMAN MIM", "Md. Siumuzzaman Khan") < verifier.NAME_MIN_SIMILARITY
        assert verifier.name_similarity("MST. NUSRAT JAHAN", "Mosammat Farhana Akter") < verifier.NAME_MIN_SIMILARITY

    def test_the_same_person_still_matches(self):
        assert verifier.name_similarity("MD. ABDUR RAHIM", "Abdur Rahim") == 100
        assert verifier.name_similarity("MD MOTIUR RAHMAN MIM", "Motiur Rahman") == 100
        assert verifier.name_similarity("MOHAMMAD ALI", "Md Ali") == 100


class TestVerifying:
    async def test_a_readable_card_verifies_and_keeps_both_sides(self, client, make, db, cards, upload_root):
        owner = await make.account("OWNER")
        response = await verify(client, owner)

        assert response.status_code == 200, response.text
        assert response.json() == {"verified": True, "kyc_status": "VERIFIED", "message": "Your ID has been verified successfully!", "mistakes": []}
        me = (await client.get("/auth/me", headers=owner.auth)).json()
        assert (me["kyc_status"], me["is_verified"], me["kyc_documents"][0]["doc_number"], me["kyc_documents"][0]["has_back"]) == ("VERIFIED", True, cards.number, True)
        assert "storage_path" not in json.dumps(me) and "verification" not in json.dumps(me)
        stored = sorted(path.name for path in (upload_root / "kyc" / owner.id).iterdir())
        assert len(stored) == 2 and all(len(name) == 32 + len(".jpg") for name in stored)
        record = await db.kyc_verifications.find_one({"user_id": owner.oid})
        assert record["outcome"] == "VERIFIED" and len(record["front"]["pixel_signature_256"]) == 256

        assert (await verify(client, owner)).status_code == 409  # already verified

    async def test_the_holder_and_admins_can_open_the_card_but_nobody_else(self, client, make, cards):
        owner, stranger, admin = await make.account("OWNER"), await make.account("BACHELOR_TENANT"), await make.account("ADMIN")
        assert (await verify(client, owner)).status_code == 200
        front, back = f"/auth/kyc/{owner.id}/documents/NID", f"/auth/kyc/{owner.id}/documents/NID?side=back"

        stolen = await client.get(front, headers=stranger.auth)
        assert stolen.status_code == 403 and not stolen.content.startswith(b"\xff\xd8")
        for path in (front, back):
            assert (await client.get(path, headers=owner.auth)).status_code == 200
            assert (await client.get(path, headers=admin.auth)).status_code == 200
        assert (await client.get(front)).status_code == 401


class TestDuplicates:
    async def test_the_same_id_number_on_another_account_is_revoked(self, client, make, db, cards):
        first, second = await make.account("OWNER", name="Abdur Rahim"), await make.account("BACHELOR_TENANT", name="Abdur Rahim")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=1)
        assert (await verify(client, first, seed=1)).json()["kyc_status"] == "VERIFIED"
        cards.show("ABDUR RAHIM", "1990123456", face_seed=2)

        response = await verify(client, second, seed=2)

        assert response.status_code == 403
        assert response.json() == {
            "verified": False,
            "kyc_status": "REVOKED",
            "message": "Verification revoked: This ID document is already associated with another account or violates our single-account verification policy.",
            "mistakes": [],
        }
        assert_nothing_given_away(response)
        stored = await db.users.find_one({"_id": second.oid})
        assert (stored["kyc_status"], stored["trust_score"]) == ("REVOKED", 70)
        alert = await db.security_audit_logs.find_one({"rule": "KYC_DUPLICATE_ID", "subject_user_id": second.oid})
        (match,) = alert["evidence"]["matches"]
        assert (match["user_id"], match["reasons"][0], match["id_similarity"]) == (first.id, "Same ID number", 100.0)
        # Trying again changes nothing.
        assert (await verify(client, second, seed=3)).status_code == 403

    async def test_the_same_number_is_revoked_whatever_the_name(self, client, make, cards):
        first, second = await make.account("OWNER", name="Abdur Rahim"), await make.account("FAMILY_TENANT", name="Karim Hossain")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=1)
        await verify(client, first, seed=1)
        cards.show("KARIM HOSSAIN", "1990123456", face_seed=2)
        assert (await verify(client, second, seed=2)).status_code == 403

    async def test_people_who_share_a_name_both_verify(self, client, make, cards):
        """Same name, and even a number one digit apart: different people, as long as number and face differ."""
        first, second = await make.account("OWNER", name="Md. Abdur Rahim"), await make.account("BUYER", name="Abdur Rahim")
        cards.show("MD. ABDUR RAHIM", "1990123456", face_seed=1)
        assert (await verify(client, first, seed=1)).json()["kyc_status"] == "VERIFIED"
        cards.show("ABDUR RAHIM", "1990123458", face_seed=2)
        assert (await verify(client, second, seed=2)).json()["kyc_status"] == "VERIFIED"

    async def test_the_same_face_is_held_for_an_admin_without_a_penalty(self, client, make, db, cards):
        first, second = await make.account("OWNER", name="Abdur Rahim"), await make.account("BACHELOR_TENANT", name="Karim Hossain")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=7)
        await verify(client, first, seed=1)
        cards.show("KARIM HOSSAIN", "5554443332", face_seed=7)

        response = await verify(client, second, seed=2)

        assert (response.status_code, response.json()["kyc_status"], response.json()["verified"]) == (202, "PENDING", False)
        assert_nothing_given_away(response)
        stored = await db.users.find_one({"_id": second.oid})
        assert (stored["kyc_status"], stored["trust_score"]) == ("PENDING", 100)
        alert = await db.security_audit_logs.find_one({"rule": "KYC_POSSIBLE_DUPLICATE", "subject_user_id": second.oid})
        assert alert["evidence"]["matches"][0]["reasons"] == ["Same face as the portrait on this card"]
        assert alert["evidence"]["matches"][0]["face_similarity"] == 1.0

    async def test_the_same_card_photo_with_a_misread_number_is_held_too(self, client, make, db, cards):
        first, second = await make.account("OWNER", name="Abdur Rahim"), await make.account("OWNER", name="Abdur Rahim")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=1)
        await verify(client, first, seed=4)
        cards.show("ABDUR RAHIM", "1990123458", face_seed=2)
        assert (await verify(client, second, seed=4)).json()["kyc_status"] == "PENDING"
        alert = await db.security_audit_logs.find_one({"rule": "KYC_POSSIBLE_DUPLICATE", "subject_user_id": second.oid})
        assert alert["evidence"]["matches"][0]["reasons"] == ["Front of the card looks the same", "Near-identical ID number"]

    async def test_different_people_with_the_same_kind_of_card_both_verify(self, client, make, cards):
        first, second = await make.account("OWNER", name="Abdur Rahim"), await make.account("OWNER", name="Karim Hossain")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=1)
        assert (await verify(client, first, seed=1)).json()["kyc_status"] == "VERIFIED"
        cards.show("KARIM HOSSAIN", "5554443332", face_seed=2)
        assert (await verify(client, second, seed=2)).json()["kyc_status"] == "VERIFIED"


class TestAdminDecisions:
    async def test_the_real_owner_is_restored_and_the_thief_revoked(self, client, make, db, cards):
        """A thief verified with someone's card first; the real owner was revoked, appealed, and an admin fixes it."""
        thief, owner, admin = await make.account("OWNER", name="Abdur Rahim"), await make.account("OWNER", name="Abdur Rahim"), await make.account("ADMIN")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=1)
        await verify(client, thief, seed=1)
        assert (await verify(client, owner, seed=2)).status_code == 403
        alert = await db.security_audit_logs.find_one({"rule": "KYC_DUPLICATE_ID", "subject_user_id": owner.oid})
        thief_record = alert["evidence"]["matches"][0]["record_id"]
        assert (await client.get(f"/admin/governance/kyc-verifications/{thief_record}/images/front", headers=admin.auth)).status_code == 200
        assert (await client.get(f"/admin/governance/kyc-verifications/{thief_record}/images/front", headers=owner.auth)).status_code == 403

        note = {"note": "Owner sent a video holding the card"}
        restored = await client.post(f"/admin/governance/users/{owner.id}/kyc/restore", json=note, headers=admin.auth)
        revoked = await client.post(f"/admin/governance/users/{thief.id}/kyc/revoke", json={"note": "Used someone else's NID"}, headers=admin.auth)

        assert (restored.status_code, restored.json()["kyc_status"], restored.json()["trust_score"]) == (200, "VERIFIED", 100)
        assert (revoked.status_code, revoked.json()["kyc_status"], revoked.json()["trust_score"]) == (200, "REVOKED", 70)
        assert (await db.security_audit_logs.find_one({"_id": alert["_id"]}))["status"] == "RESOLVED"
        assert await db.security_audit_logs.count_documents({"kind": "ACTION", "rule": {"$in": ["KYC_RESTORED", "KYC_REVOKED"]}}) >= 2
        assert (await client.post(f"/admin/governance/users/{owner.id}/kyc/restore", json=note, headers=admin.auth)).status_code == 409

        # The thief's card no longer counts; the owner's does.
        newcomer = await make.account("OWNER", name="Abdur Rahim")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=3)
        assert (await verify(client, newcomer, seed=3)).status_code == 403
        latest = await db.security_audit_logs.find_one({"rule": "KYC_DUPLICATE_ID", "subject_user_id": newcomer.oid})
        assert [m["user_id"] for m in latest["evidence"]["matches"]] == [owner.id]

    async def test_a_card_held_for_review_can_be_approved(self, client, make, db, cards):
        first, second, admin = await make.account("OWNER", name="Abdur Rahim"), await make.account("OWNER", name="Karim Hossain"), await make.account("ADMIN")
        cards.show("ABDUR RAHIM", "1990123456", face_seed=9)
        await verify(client, first, seed=1)
        cards.show("KARIM HOSSAIN", "5554443332", face_seed=9)
        await verify(client, second, seed=2)

        approved = await client.post(f"/admin/governance/users/{second.id}/kyc/approve", json={"note": "Twins, checked by phone"}, headers=admin.auth)

        assert (approved.status_code, approved.json()["kyc_status"]) == (200, "VERIFIED")
        assert (await db.kyc_verifications.find_one({"user_id": second.oid}))["outcome"] == "VERIFIED"
        assert (await client.post(f"/admin/governance/users/{second.id}/kyc/approve", json={"note": "again"}, headers=second.auth)).status_code == 403
