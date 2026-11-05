"""Create (or promote) an ADMIN account.

Usage (from /backend):
    python -m app.scripts.create_admin --email admin@barikhujun.com --name "Site Admin"
The password is read from the prompt, or from --password for non-interactive use.
"""

import argparse
import asyncio
import getpass
from datetime import datetime, timezone

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.core.security import hash_password
from app.schemas.user import KycStatus, Role


async def create_admin(email: str, full_name: str, password: str) -> None:
    await connect_to_mongo()
    try:
        now = datetime.now(timezone.utc)
        result = await get_db().users.update_one(
            {"email": email.lower()},
            {
                "$set": {
                    "full_name": full_name,
                    "password_hash": hash_password(password),
                    "role": Role.ADMIN.value,
                    "kyc_status": KycStatus.VERIFIED.value,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "is_banned": False,
                    "token_version": 0,
                    "phone": "+0000000000",
                    "kyc_documents": [],
                    "kyc_review_note": None,
                    "trust_score": 100,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        action = "Created" if result.upserted_id else "Updated"
        print(f"{action} ADMIN account {email.lower()}")
    finally:
        await close_mongo_connection()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Bari Khujun Admin")
    parser.add_argument("--password")
    args = parser.parse_args()
    # Same validation as the login endpoint, so the account can actually sign in.
    try:
        email = TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError as exc:
        parser.error(f"invalid email: {exc.errors()[0]['msg']}")
    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        parser.error("password must be at least 8 characters")
    asyncio.run(create_admin(email, args.name, password))


if __name__ == "__main__":
    main()
