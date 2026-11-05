"""Attack simulations against the Bari Khujun API's security guardrails.

Each class plays one attack end to end through the HTTP API and checks two things: the response the attacker gets,
and that nothing changed in the database. Run from backend/ with `python -m pytest`.
"""

import asyncio

import pytest
from bson import ObjectId
from kyc_support import FakeCards, card_photo
from support import PASSWORD

from app.utils import id_card_verifier

pytestmark = pytest.mark.anyio


# ================================================================ Attack 1: privilege escalation / mass assignment


class TestMassAssignment:
    ESCALATION = {"role": "ADMIN", "trust_score": 999}

    async def test_register_cannot_set_admin_role_or_trust_score(self, client, db):
        email = "mallory.register@example.com"
        response = await client.post(
            "/auth/register",
            json={"full_name": "Mallory", "email": email, "phone": "+8801711111111", "password": PASSWORD, **self.ESCALATION},
        )
        assert response.status_code == 422
        assert "access_token" not in response.json()
        assert await db.users.find_one({"email": email}) is None

    @pytest.mark.parametrize(
        "extra",
        [{"trust_score": 999}, {"kyc_status": "VERIFIED"}, {"is_banned": False, "token_version": 0}, {"_id": "0" * 24}],
        ids=["trust_score", "kyc_status", "ban_fields", "_id"],
    )
    async def test_register_rejects_any_server_owned_field(self, client, db, extra):
        email = f"mallory.{next(iter(extra)).strip('_')}@example.com"
        response = await client.post(
            "/auth/register",
            json={"full_name": "Mallory", "email": email, "phone": "+8801711111111", "password": PASSWORD, "role": "BUYER", **extra},
        )
        assert response.status_code == 422
        assert await db.users.find_one({"email": email}) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"role": "ADMIN", "trust_score": 999},
            {"full_name": "Mallory Admin", "role": "ADMIN"},
            {"phone": "+8801722222222", "trust_score": 999},
            {"kyc_status": "VERIFIED"},
            {"is_banned": False, "token_version": 99},
        ],
        ids=["role+trust_score", "name+role", "phone+trust_score", "kyc_status", "ban_fields"],
    )
    async def test_profile_update_cannot_escalate(self, client, db, make, payload):
        tenant = await make.account("BACHELOR_TENANT")
        response = await client.patch("/auth/me", json=payload, headers=tenant.auth)
        assert response.status_code == 422
        stored = await db.users.find_one({"_id": tenant.oid})
        assert (stored["role"], stored["trust_score"], stored["kyc_status"]) == ("BACHELOR_TENANT", 100, "NOT_SUBMITTED")
        assert (stored["full_name"], stored["phone"], stored["token_version"]) == (tenant.full_name, "+8801700000000", 0)

    async def test_profile_update_still_allows_name_and_phone(self, client, make):
        tenant = await make.account("FAMILY_TENANT")
        response = await client.patch("/auth/me", json={"full_name": "Nadia Rahman", "phone": "+8801733333333"}, headers=tenant.auth)
        assert response.status_code == 200
        body = response.json()
        assert (body["full_name"], body["phone"], body["role"]) == ("Nadia Rahman", "+8801733333333", "FAMILY_TENANT")


# ================================================================ Attack 2: NoSQL operator injection


class TestNoSqlInjection:
    @pytest.mark.parametrize(
        "email",
        [{"$gt": ""}, {"$ne": None}, {"$regex": ".*"}, {"$where": "return true"}],
        ids=["$gt", "$ne", "$regex", "$where"],
    )
    async def test_login_with_operator_as_email_is_rejected(self, client, make, email):
        await make.account("OWNER")  # there is someone to match, if the operator ever reached the query
        response = await client.post("/auth/login", json={"email": email, "password": "123"})
        assert response.status_code in (400, 422)
        assert "access_token" not in response.json()

    async def test_login_with_operator_as_password_is_rejected(self, client, make):
        owner = await make.account("OWNER")
        response = await client.post("/auth/login", json={"email": owner.email, "password": {"$ne": ""}})
        assert response.status_code in (400, 422)
        assert "access_token" not in response.json()

    async def test_operator_smuggled_in_query_string_is_rejected(self, client):
        response = await client.get("/rentals", params={"category[$ne]": "FAMILY_FLAT"})
        assert response.status_code == 400

    async def test_operator_nested_in_body_is_rejected(self, client, make, db):
        tenant = await make.account("BACHELOR_TENANT")
        response = await client.post(
            "/qr-handshake/bookings",
            json={"listing_id": {"$gt": ""}, "move_in_date": "2030-01-01", "deposit_amount": 1, "payment_method": "BKASH", "payment_reference": "TRX1"},
            headers=tenant.auth,
        )
        assert response.status_code == 400
        assert await db.bookings.count_documents({"tenant_id": tenant.oid}) == 0

    async def test_malformed_object_id_is_a_400(self, client, make):
        tenant = await make.account("BACHELOR_TENANT")
        response = await client.get("/qr-handshake/bookings/not-an-object-id", headers=tenant.auth)
        assert (response.status_code, response.json()["detail"]) == (400, "Invalid ID format")


# ================================================================ Attack 3: QR replay and cross-tenant hijacking


class TestQrReplayAndHijack:
    async def test_code_issued_to_tenant_a_cannot_be_used_by_tenant_b(self, make, db):
        owner, tenant_a, tenant_b = await make.account("OWNER"), await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner)
        booking_id, token = await make.approved_booking(owner, tenant_a, listing_id)

        hijack = await make.scan(tenant_b, token)

        assert hijack.status_code == 403
        booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
        assert booking["status"] == "APPROVED" and booking["qr"]["used_at"] is None
        listing = await db.listings.find_one({"_id": ObjectId(listing_id)})
        assert listing["seats"]["available_seats"] == 1
        # The attempt lands on the admin's QR audit trail...
        assert await db.qr_handshake_logs.count_documents({"booking_id": booking["_id"], "event": "SCAN_REJECTED"}) == 1
        # ...and the rightful tenant can still use the code.
        assert (await make.scan(tenant_a, token)).status_code == 200

    async def test_confirmed_code_cannot_be_replayed(self, make, db):
        owner, tenant_a, tenant_b = await make.account("OWNER"), await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner, total_seats=3, available_seats=2)
        booking_id, token = await make.approved_booking(owner, tenant_a, listing_id)
        assert (await make.scan(tenant_a, token)).status_code == 200

        replay = await make.scan(tenant_a, token)
        hijack_after_use = await make.scan(tenant_b, token)

        assert replay.status_code == 400
        assert hijack_after_use.status_code == 403
        booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
        assert booking["status"] == "CONFIRMED" and booking["qr"]["nonce"] is None
        listing = await db.listings.find_one({"_id": ObjectId(listing_id)})
        assert listing["seats"]["available_seats"] == 1  # one seat taken, not two
        assert await db.qr_handshake_logs.count_documents({"booking_id": booking["_id"], "event": "CONFIRMED"}) == 1

    async def test_superseded_code_is_refused(self, client, make):
        owner, tenant = await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner)
        booking_id, first_token = await make.approved_booking(owner, tenant, listing_id)
        await client.post(f"/qr-handshake/generate/{booking_id}", headers=owner.auth)  # the owner regenerates the code

        assert (await make.scan(tenant, first_token)).status_code == 400

    async def test_login_token_is_not_a_handshake_code(self, make):
        tenant = await make.account("BACHELOR_TENANT")
        assert (await make.scan(tenant, tenant.token)).status_code == 400


# ================================================================ Attack 4: concurrent double-scan race


class TestConcurrentScans:
    async def test_five_tenants_racing_for_the_last_seat_confirm_one_lease(self, make, db):
        owner = await make.account("OWNER")
        listing_id = await make.seat_listing(owner, total_seats=3, available_seats=1)
        tenants = [await make.account("BACHELOR_TENANT", name=f"Racer {i}") for i in range(5)]
        codes = [(await make.approved_booking(owner, tenant, listing_id))[1] for tenant in tenants]

        responses = await asyncio.gather(*(make.scan(tenant, code) for tenant, code in zip(tenants, codes)))

        assert sorted(response.status_code for response in responses) == [200, 409, 409, 409, 409]
        listing = await db.listings.find_one({"_id": ObjectId(listing_id)})
        assert (listing["seats"]["available_seats"], listing["rental_status"]) == (0, "RENTED")
        bookings = await db.bookings.find({"listing_id": ObjectId(listing_id)}).to_list(None)
        assert sorted(b["status"] for b in bookings) == ["CANCELLED"] * 4 + ["CONFIRMED"]
        assert sum(1 for b in bookings if b.get("lease")) == 1
        assert all(b["escrow_status"] == "REFUNDED" for b in bookings if b["status"] == "CANCELLED")

    async def test_one_code_scanned_five_times_at_once_confirms_once(self, make, db):
        owner, tenant = await make.account("OWNER"), await make.account("BACHELOR_TENANT")
        listing_id = await make.seat_listing(owner, total_seats=3, available_seats=1)
        booking_id, code = await make.approved_booking(owner, tenant, listing_id)

        responses = await asyncio.gather(*(make.scan(tenant, code) for _ in range(5)))

        assert sorted(response.status_code for response in responses) == [200, 400, 400, 400, 400]
        listing = await db.listings.find_one({"_id": ObjectId(listing_id)})
        assert listing["seats"]["available_seats"] == 0  # decremented exactly once, never below zero
        booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
        assert booking["status"] == "CONFIRMED" and booking["escrow_status"] == "RELEASED"
        assert sum(1 for entry in booking["escrow_ledger"] if entry["status"] == "RELEASED") == 1
        assert await db.qr_handshake_logs.count_documents({"booking_id": booking["_id"], "event": "CONFIRMED"}) == 1


# ================================================================ Attack 5: IDOR on leases, invoices and KYC files


class TestIdor:
    async def test_tenant_b_cannot_download_tenant_a_lease_pdf(self, client, make):
        owner, tenant_a, tenant_b = await make.account("OWNER"), await make.account("BACHELOR_TENANT"), await make.account("FAMILY_TENANT")
        booking_id = await make.confirmed_lease(owner, tenant_a)
        path = f"/qr-handshake/bookings/{booking_id}/lease.pdf"

        stolen = await client.get(path, headers=tenant_b.auth)
        own = await client.get(path, headers=tenant_a.auth)

        assert stolen.status_code == 403
        assert not stolen.content.startswith(b"%PDF")
        assert own.status_code == 200 and own.content.startswith(b"%PDF")
        assert (await client.get(f"/operations/leases/{booking_id}", headers=tenant_b.auth)).status_code == 403

    async def test_tenant_b_cannot_read_or_pay_tenant_a_invoice(self, client, make, db):
        owner, tenant_a, tenant_b = await make.account("OWNER"), await make.account("BACHELOR_TENANT"), await make.account("BACHELOR_TENANT")
        booking_id = await make.confirmed_lease(owner, tenant_a)
        booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
        response = await client.post(
            "/operations/invoices/generate",
            json={"listing_id": str(booking["listing_id"]), "period": f"{make.move_in_date():%Y-%m}", "electricity": 1500},
            headers=owner.auth,
        )
        assert response.status_code == 201, response.text
        invoice_id = response.json()["created"][0]["id"]

        listed = await client.get("/operations/invoices", params={"booking_id": booking_id}, headers=tenant_b.auth)
        paid = await client.post(f"/operations/invoices/{invoice_id}/pay", json={"method": "BKASH", "reference": "BK5XQ12"}, headers=tenant_b.auth)
        receipt = await client.get(f"/operations/invoices/{invoice_id}/receipt.pdf", headers=tenant_b.auth)

        assert (listed.status_code, paid.status_code, receipt.status_code) == (403, 403, 403)
        invoice = await db.invoices.find_one({"_id": ObjectId(invoice_id)})
        assert invoice["status"] == "UNPAID" and not invoice.get("payment")

    async def test_tenant_b_cannot_view_owner_c_kyc_document(self, client, make, monkeypatch):
        owner_c, tenant_b, admin = await make.account("OWNER"), await make.account("BACHELOR_TENANT"), await make.account("ADMIN")
        monkeypatch.setattr(id_card_verifier, "read_card", FakeCards())
        upload = await client.post(
            "/auth/kyc-auto-verify",
            data={"doc_type": "NID"},
            files={"front": ("nid_card.jpg", card_photo(7001), "image/jpeg"), "back": ("nid_back.jpg", card_photo(7002), "image/jpeg")},
            headers=owner_c.auth,
        )
        assert upload.json()["kyc_status"] == "VERIFIED", upload.text
        path = f"/auth/kyc/{owner_c.id}/documents/NID"

        stolen = await client.get(path, headers=tenant_b.auth)

        assert stolen.status_code == 403
        assert not stolen.content.startswith(b"\xff\xd8")
        assert (await client.get(path, headers=owner_c.auth)).status_code == 200
        assert (await client.get(path, headers=admin.auth)).status_code == 200
        assert (await client.get(path)).status_code == 401

    async def test_kyc_answer_does_not_reveal_whether_an_account_exists(self, client, make):
        tenant_b = await make.account("BACHELOR_TENANT")
        response = await client.get(f"/auth/kyc/{ObjectId()}/documents/NID", headers=tenant_b.auth)
        assert response.status_code == 403


# ================================================================ Attack 6: malicious file upload

# Inert stand-ins: they have the shape of a server-side script and a Windows executable (which is all the upload
# check looks at) but do nothing, so antivirus software doesn't quarantine this file.
PHP_SCRIPT = b"<?php echo 'barikhujun upload probe'; ?>\n"
WINDOWS_EXE = b"MZ" + bytes(58) + (64).to_bytes(4, "little") + b"PE\x00\x00" + bytes(256)
# A JPEG signature glued onto the script: passes a naive magic-byte check, but isn't a decodable image.
JPEG_POLYGLOT = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + PHP_SCRIPT * 20


class TestMaliciousUpload:
    @pytest.mark.parametrize(
        "content", [PHP_SCRIPT, WINDOWS_EXE, JPEG_POLYGLOT], ids=["php-as-jpg", "exe-as-jpg", "jpeg-header-polyglot"]
    )
    async def test_disguised_executable_is_rejected(self, client, make, db, upload_root, content):
        owner = await make.account("OWNER")
        response = await client.post(
            "/auth/kyc-auto-verify",
            data={"doc_type": "NID"},
            files={"front": ("nid_card.jpg", content, "image/jpeg"), "back": ("nid_back.jpg", content, "image/jpeg")},
            headers=owner.auth,
        )
        # Not an error page: the user is asked for a real photo, and nothing is kept.
        assert response.status_code == 200
        assert {m["code"] for m in response.json()["mistakes"]} == {"NOT_AN_IMAGE"}
        stored = await db.users.find_one({"_id": owner.oid})
        assert (stored["kyc_documents"], stored["kyc_status"]) == ([], "NOT_SUBMITTED")
        folder = upload_root / "kyc" / owner.id
        assert not folder.exists() or not any(folder.iterdir())

    async def test_real_jpeg_is_stored_under_a_random_name(self, client, make, db, upload_root, monkeypatch):
        owner = await make.account("OWNER")
        monkeypatch.setattr(id_card_verifier, "read_card", FakeCards())
        response = await client.post(
            "/auth/kyc-auto-verify",
            data={"doc_type": "NID"},
            files={"front": ("../../nid_card.php.jpg", card_photo(7003), "application/x-php"), "back": ("back.jpg", card_photo(7004), "image/jpeg")},
            headers=owner.auth,
        )
        assert response.status_code == 200, response.text
        document = (await db.users.find_one({"_id": owner.oid}))["kyc_documents"][0]
        assert document["content_type"] == "image/jpeg"  # taken from the bytes, not the client's header
        stored = [path.name for path in (upload_root / "kyc" / owner.id).iterdir()]
        assert len(stored) == 2 and all(name.endswith(".jpg") and len(name) == 32 + len(".jpg") for name in stored)
        me = await client.get("/auth/me", headers=owner.auth)
        assert "storage_path" not in me.text and str(upload_root) not in me.text
