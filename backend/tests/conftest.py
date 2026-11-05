"""Shared fixtures for the API test suite.

The FastAPI app runs in-process (httpx's ASGI transport) against a throwaway MongoDB database and a temporary
uploads folder, so the suite never touches development data or backend/uploads.
"""

import atexit
import os
import secrets
import shutil
import tempfile
from pathlib import Path

# Settings are read once, when the app is imported, so the test configuration has to be in place first.
_UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="barikhujun-test-uploads-"))
atexit.register(shutil.rmtree, _UPLOAD_DIR, ignore_errors=True)  # runs even if collection fails
os.environ["MONGO_URI"] = os.environ.get("TEST_MONGO_URI", "mongodb://localhost:27017/barikhujun_test")
os.environ["JWT_AUTH_SECRET"] = secrets.token_urlsafe(48)
os.environ["QR_HANDSHAKE_SECRET"] = secrets.token_urlsafe(48)
os.environ["UPLOAD_DIR"] = str(_UPLOAD_DIR)
# The suite signs in far more often than the 5-per-minute login limit allows.
os.environ["RATE_LIMIT_ENABLED"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
from support import Factory  # noqa: E402

from app.core import database  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def db():
    await database.connect_to_mongo()  # also creates the indexes the app relies on (unique, partial, geo)
    test_db = database.get_db()
    if not test_db.name.endswith("_test"):
        pytest.exit(f"Refusing to run against database {test_db.name!r}: TEST_MONGO_URI must name a *_test database")
    for name in await test_db.list_collection_names():
        await test_db[name].delete_many({})
    yield test_db
    await test_db.client.drop_database(test_db.name)
    await database.close_mongo_connection()


@pytest.fixture(scope="session")
async def client(db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver/api") as http:
        yield http


@pytest.fixture
def make(client, db) -> Factory:
    return Factory(client, db)


@pytest.fixture
def upload_root() -> Path:
    return settings.upload_dir
