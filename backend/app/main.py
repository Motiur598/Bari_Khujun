import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo
from app.core.limiter import limiter, rate_limit_exceeded
from app.core.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.core.sanitizers import NoSqlInjectionGuard
from app.core.security import AccountSuspended
from app.routers import admin_governance, auth, chat_and_notifications, locations, marketplace, operations, qr_handshake, rentals
from app.services.governance import run_radar_scheduler
from app.services.listings import backfill_admin_areas, backfill_sublets
from app.services.move_outs import run_move_out_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await connect_to_mongo()
    await backfill_admin_areas()
    await backfill_sublets()
    jobs = [
        asyncio.create_task(run_move_out_scheduler(settings.move_out_check_minutes)),
        asyncio.create_task(run_radar_scheduler(settings.radar_check_minutes)),
    ]
    yield
    for job in jobs:
        job.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await job
    await close_mongo_connection()


app = FastAPI(
    title="Bari Khujun API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded)


@app.exception_handler(AccountSuspended)
async def account_suspended(_request: Request, exc: AccountSuspended) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status_code)


# Middleware runs outermost-last-added: security headers wrap everything (errors included), then CORS, then the
# body-size ceiling, then the NoSQL operator guard right in front of the routes.
app.add_middleware(NoSqlInjectionGuard)
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=settings.max_request_body_bytes,
    # One video per request, plus form overhead.
    overrides=[(r"/api/(rentals|marketplace/sale-listings)/[0-9a-f]{24}/video", settings.video_max_bytes + 1024 * 1024)],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,  # explicit list from .env; "*" is refused at startup
    allow_credentials=False,  # auth is a bearer header, never a cookie
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(rentals.router)
app.include_router(locations.router)
app.include_router(marketplace.router)
app.include_router(qr_handshake.router)
app.include_router(operations.router)
app.include_router(admin_governance.router)
app.include_router(admin_governance.disputes_router)
app.include_router(chat_and_notifications.router)


@app.get("/api/health", tags=["health"])
async def health():
    return {"status": "ok"}
