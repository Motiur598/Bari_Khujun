from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.database import serialize_doc
from app.core.sanitizers import RequestModel, SafeText


class Role(StrEnum):
    OWNER = "OWNER"
    BACHELOR_TENANT = "BACHELOR_TENANT"
    FAMILY_TENANT = "FAMILY_TENANT"
    BUYER = "BUYER"
    ADMIN = "ADMIN"


# ADMIN accounts are created with `python -m app.scripts.create_admin`, never via public signup.
SELF_REGISTER_ROLES = (Role.OWNER, Role.BACHELOR_TENANT, Role.FAMILY_TENANT, Role.BUYER)


class KycStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"  # an admin is checking it (an older manual upload, or a card that looks like another account's)
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"  # the ID belongs to another account; only an admin can restore it


class KycDocType(StrEnum):
    NID = "NID"
    STUDENT_ID = "STUDENT_ID"
    JOB_ID = "JOB_ID"


PHONE_PATTERN = r"^\+?[0-9][0-9 -]{5,19}$"


class RegisterRequest(RequestModel):
    full_name: SafeText = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(pattern=PHONE_PATTERN)
    # bcrypt only uses the first 72 bytes of a password.
    password: str = Field(min_length=8, max_length=72)
    role: Role

    @field_validator("role")
    @classmethod
    def role_must_be_self_registrable(cls, role: Role) -> Role:
        if role not in SELF_REGISTER_ROLES:
            raise ValueError("This role cannot be self-registered")
        return role


class ProfileUpdate(RequestModel):
    """The only profile fields a user may change. Role, trust score, KYC and ban state stay server-owned:
    sending any of them is a 422 (extra="forbid")."""

    full_name: SafeText | None = Field(default=None, min_length=2, max_length=100)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)


class LoginRequest(RequestModel):
    email: EmailStr
    password: str = Field(max_length=256)


class KycDocumentOut(BaseModel):
    doc_type: KycDocType
    doc_number: str
    original_filename: str
    content_type: str
    size_bytes: int
    # Cards checked automatically keep a photo of each side; ?side=back downloads the back.
    has_back: bool = False
    uploaded_at: datetime


class UserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    phone: str
    role: Role
    kyc_status: KycStatus
    is_verified: bool = False
    kyc_documents: list[KycDocumentOut] = []
    kyc_review_note: str | None = None
    trust_score: int
    review_count: int = 0
    rating_average: float | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class KycReviewRequest(RequestModel):
    status: Literal[KycStatus.VERIFIED, KycStatus.REJECTED]
    note: SafeText | None = Field(default=None, max_length=500)


def user_to_out(doc: dict) -> UserOut:
    # Unknown keys (password_hash, storage_path) are dropped by the model.
    data = serialize_doc(doc)
    data["is_verified"] = data.get("kyc_status") == KycStatus.VERIFIED
    for document in data.get("kyc_documents", []):
        document["has_back"] = bool(document.get("back"))
    return UserOut.model_validate(data)


class KycMistakeOut(BaseModel):
    side: Literal["front", "back"]
    code: str
    message: str


class KycAutoVerifyResult(BaseModel):
    """What the user is told after an automated ID check. Deliberately nothing about how the check works: no scores,
    hashes, thresholds or matched accounts."""

    verified: bool
    kyc_status: Literal["VERIFIED", "NEEDS_RETRY", "PENDING", "REVOKED"]
    message: str
    mistakes: list[KycMistakeOut] = []
