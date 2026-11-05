"""Rate limiting (slowapi). Limits are declared per route with the decorators below."""

import math

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings

AUTH_AUDIENCE = "barikhujun:auth"


def user_or_ip(request: Request) -> str:
    """Key by the signed-in user when the bearer token is valid, so limits follow the account, not the network.

    Only the signature is checked here (no database call); an invalid or missing token falls back to the IP.
    """
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            claims = jwt.decode(
                header[7:].strip(), settings.jwt_auth_secret, algorithms=[settings.jwt_algorithm], audience=AUTH_AUDIENCE
            )
            if claims.get("sub"):
                return f"user:{claims['sub']}"
        except jwt.PyJWTError:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.rate_limit_storage_uri,
    enabled=settings.rate_limit_enabled,
    headers_enabled=False,
)

# Credential stuffing and account farming: per client IP.
AUTH_LIMIT = "5/minute"
# Guessing or hammering handshake codes: per account.
QR_LIMIT = "10/minute"
# Listing videos are large: a handful an hour per account.
VIDEO_UPLOAD_LIMIT = "10/hour"
# Automated ID checks: retrying a better photo is expected, so a little more room than other identity uploads.
KYC_VERIFY_LIMIT = "12/hour"
# Identity and title-deed uploads: per account.
SENSITIVE_UPLOAD_LIMIT = "5/hour"
# Listing photos are uploaded one at a time from the editor: room for a few full listings an hour.
PHOTO_UPLOAD_LIMIT = "60/hour"
# Chat messages and in-chat proposals: brisk typing, not a spam run. Per account.
CHAT_LIMIT = "30/minute"


def rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = 60
    limit = getattr(exc, "limit", None)
    if limit is not None:
        retry_after = max(1, math.ceil(limit.limit.get_expiry()))
    return JSONResponse(
        {"detail": f"Too many attempts. Try again in {retry_after // 60 or 1} minute{'s' if retry_after >= 120 else ''}."},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )
