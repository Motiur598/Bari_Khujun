from datetime import datetime, timedelta, timezone

import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import AUTH_AUDIENCE
from app.schemas.user import Role

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

ISSUER = "barikhujun"
# A real hash of a random password, so a login for an unknown email costs the same bcrypt time as a wrong
# password and response timing doesn't reveal which emails are registered.
_DUMMY_HASH = pwd_context.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        pwd_context.verify(password, _DUMMY_HASH)
        return False
    return pwd_context.verify(password, password_hash)


def create_access_token(user: dict) -> str:
    """Login token. `tv` is the user's token version: bumping it (ban, sign out everywhere) revokes old tokens."""
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "aud": AUTH_AUDIENCE,
        "sub": str(user["_id"]),
        "role": user["role"],
        "tv": user.get("token_version", 0),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_auth_secret, algorithm=settings.jwt_algorithm)


class AccountSuspended(HTTPException):
    """403 for a banned account. The response also carries `"code": "ACCOUNT_BANNED"` (see main.py), so the app can
    tell a ban apart from an ordinary permission error and end the session."""

    code = "ACCOUNT_BANNED"

    def __init__(self, detail: str = "This account has been suspended. Contact Bari Khujun support."):
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    return await user_from_token(credentials.credentials)


async def user_from_token(token: str) -> dict:
    """The account a login token belongs to, with every check a request gets: signature, expiry, ban, revocation.
    Shared by the bearer-header dependency and the realtime WebSocket, which carries the token in its URL."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_auth_secret,
            algorithms=[settings.jwt_algorithm],
            audience=AUTH_AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token")

    user_id = payload["sub"]
    if not ObjectId.is_valid(user_id):
        raise _unauthorized("Invalid token")
    user = await get_db().users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise _unauthorized("User no longer exists")
    # Checked on every request, so a ban cuts a scammer off at once even though their token hasn't expired.
    if user.get("is_banned"):
        raise AccountSuspended()
    if payload.get("tv", 0) != user.get("token_version", 0):
        raise _unauthorized("This session was signed out. Sign in again.")
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict | None:
    """The signed-in user for endpoints that also work anonymously; a bad token is still a 401."""
    if credentials is None:
        return None
    return await get_current_user(credentials)


def require_roles(*roles: Role):
    """Dependency factory: allow the request only if the current user has one of `roles`."""

    async def guard(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return guard
