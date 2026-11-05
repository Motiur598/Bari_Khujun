from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.database import get_db, parse_object_id
from app.core.limiter import AUTH_LIMIT, KYC_VERIFY_LIMIT, limiter, user_or_ip
from app.core.security import (
    AccountSuspended,
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from app.schemas.user import (
    SELF_REGISTER_ROLES,
    KycAutoVerifyResult,
    KycDocType,
    KycReviewRequest,
    KycStatus,
    LoginRequest,
    ProfileUpdate,
    RegisterRequest,
    Role,
    TokenResponse,
    UserOut,
    user_to_out,
)
from app.services import kyc_verification
from app.utils.file_security import private_file_response

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(AUTH_LIMIT)
async def register(request: Request, payload: RegisterRequest):
    now = datetime.now(timezone.utc)
    # Every server-owned field is set here; the request model forbids anything beyond name, contact, password, role.
    user = {
        "full_name": payload.full_name,
        "email": payload.email.lower(),
        "phone": payload.phone,
        "password_hash": hash_password(payload.password),
        "role": payload.role.value,
        "kyc_status": KycStatus.NOT_SUBMITTED.value,
        "kyc_documents": [],
        "kyc_review_note": None,
        "trust_score": 100,
        "is_banned": False,
        "token_version": 0,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await get_db().users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
    return TokenResponse(access_token=create_access_token(user), user=user_to_out(user))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
async def login(request: Request, payload: LoginRequest):
    user = await get_db().users.find_one({"email": payload.email.lower()})
    # verify_password does a dummy bcrypt check for unknown emails, so timing doesn't reveal who's registered.
    if not verify_password(payload.password, user["password_hash"] if user else None):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user.get("is_banned"):
        raise AccountSuspended()
    return TokenResponse(access_token=create_access_token(user), user=user_to_out(user))


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_everywhere(user: dict = Depends(get_current_user)):
    """Revoke every token issued to this account so far (all devices)."""
    await get_db().users.update_one({"_id": user["_id"]}, {"$inc": {"token_version": 1}})


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return user_to_out(user)


@router.patch("/me", response_model=UserOut)
async def update_profile(payload: ProfileUpdate, user: dict = Depends(get_current_user)):
    changes = payload.model_dump(exclude_none=True)
    # Once ID documents are under review or verified, the name has to keep matching them.
    renaming = changes.get("full_name", user["full_name"]) != user["full_name"]
    if renaming and user["kyc_status"] in (KycStatus.PENDING, KycStatus.VERIFIED, KycStatus.REVOKED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Your name is locked to your ID documents. Contact support to correct it.")
    if not changes:
        return user_to_out(user)
    updated = await get_db().users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": {**changes, "updated_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    return user_to_out(updated)


@router.post(
    "/kyc-auto-verify",
    response_model=KycAutoVerifyResult,
    responses={202: {"model": KycAutoVerifyResult}, 403: {"model": KycAutoVerifyResult}},
)
@limiter.limit(KYC_VERIFY_LIMIT, key_func=user_or_ip)
async def auto_verify_kyc(
    request: Request,
    response: Response,
    doc_type: Annotated[KycDocType, Form()],
    front: Annotated[UploadFile, File(description="Photo of the front of the card (JPEG, PNG or WebP, up to 10 MB)")],
    back: Annotated[UploadFile, File(description="Photo of the back of the card")],
    user: dict = Depends(require_roles(*SELF_REGISTER_ROLES)),
):
    """Check an ID card automatically. 200 VERIFIED, or 200 NEEDS_RETRY with the photo mistakes to fix (no penalty);
    202 PENDING when an admin needs to look; 403 REVOKED when the card belongs to another account."""
    if user["kyc_status"] == KycStatus.REVOKED:
        return JSONResponse(kyc_verification.result("REVOKED").model_dump(), status_code=status.HTTP_403_FORBIDDEN)
    if user["kyc_status"] == KycStatus.VERIFIED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your ID is already verified")
    if user["kyc_status"] == KycStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your ID is already being checked")
    outcome = await kyc_verification.auto_verify(user, doc_type, front, back)
    if outcome.kyc_status == "REVOKED":
        return JSONResponse(outcome.model_dump(), status_code=status.HTTP_403_FORBIDDEN)
    if outcome.kyc_status == "PENDING":
        response.status_code = status.HTTP_202_ACCEPTED
    return outcome


@router.get("/kyc/{user_id}/documents/{doc_type}")
async def download_kyc_document(
    user_id: str,
    doc_type: KycDocType,
    side: Annotated[Literal["front", "back"], Query()] = "front",
    user: dict = Depends(get_current_user),
):
    """A KYC document, streamed only to the person it belongs to or an admin.

    Anyone else gets a 403 before any lookup, so the answer doesn't reveal whether the account or document exists.
    """
    owner_id = parse_object_id(user_id)
    if owner_id != user["_id"] and user["role"] != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't view another person's identity documents")
    owner = await get_db().users.find_one({"_id": owner_id}, {"kyc_documents": 1})
    document = next((d for d in (owner or {}).get("kyc_documents", []) if d["doc_type"] == doc_type.value), None)
    if side == "back":
        document = (document or {}).get("back")
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return private_file_response(document)


@router.get("/kyc/pending", response_model=list[UserOut])
async def list_pending_kyc(_admin: dict = Depends(require_roles(Role.ADMIN))):
    cursor = get_db().users.find({"kyc_status": KycStatus.PENDING.value}).sort("updated_at", 1)
    return [user_to_out(doc) for doc in await cursor.to_list(length=200)]


@router.patch("/kyc/{user_id}/review", response_model=UserOut)
async def review_kyc(
    user_id: str,
    payload: KycReviewRequest,
    _admin: dict = Depends(require_roles(Role.ADMIN)),
):
    updated = await get_db().users.find_one_and_update(
        {"_id": parse_object_id(user_id), "kyc_status": KycStatus.PENDING.value},
        {
            "$set": {
                "kyc_status": payload.status.value,
                "kyc_review_note": payload.note,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending KYC submission for this user")
    # A card held for review counts in later duplicate checks only once it's approved.
    approved = payload.status == KycStatus.VERIFIED
    await kyc_verification.set_latest_outcome(updated["_id"], kyc_verification.Outcome.VERIFIED if approved else kyc_verification.Outcome.REJECTED)
    return user_to_out(updated)
