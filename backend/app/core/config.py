from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Required, with no defaults on purpose: secrets and the database URL only ever come from .env / the environment.
    mongo_uri: str
    jwt_auth_secret: str = Field(validation_alias=AliasChoices("JWT_AUTH_SECRET", "JWT_SECRET"))
    # A separate key for handshake QR tokens (and lease signatures), so a login token can never verify as a
    # QR code and a leaked QR code reveals nothing about login tokens.
    qr_handshake_secret: str = Field(validation_alias=AliasChoices("QR_HANDSHAKE_SECRET", "QR_SECRET_KEY"))

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Explicit frontend origins only; "*" is rejected below.
    allowed_origins: list[str] = Field(
        default=["http://localhost:5173"], validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ORIGINS")
    )

    upload_dir: Path = BACKEND_DIR / "uploads"
    upload_max_bytes: int = 5 * 1024 * 1024
    # Whole-request ceiling, checked before FastAPI parses a body (10 photos x 5 MB plus form overhead).
    max_request_body_bytes: int = 55 * 1024 * 1024
    # A listing's walkthrough video. Only the video upload endpoints accept a body this large.
    video_max_bytes: int = 100 * 1024 * 1024
    # Face detection/recognition and OCR models for automated ID verification, downloaded on first use.
    vision_model_dir: Path = BACKEND_DIR / "models"

    rate_limit_enabled: bool = True
    # memory:// is per process; point this at redis://... when running several workers.
    rate_limit_storage_uri: str = "memory://"

    enable_api_docs: bool = True
    # Only turn on when the API is served over HTTPS.
    enable_hsts: bool = False

    # Frontend origin, used for links printed on lease PDFs (e.g. the verification QR stamp).
    app_base_url: str = "http://localhost:5173"
    qr_token_ttl_hours: int = 24

    # How often the server checks for tenants whose move-out date has arrived and reopens their seat or flat.
    move_out_check_minutes: int = 15
    # How often the scammer radar re-checks recent QR activity (it also runs after every QR issue).
    radar_check_minutes: int = 15

    @model_validator(mode="after")
    def secure_configuration(self) -> "Settings":
        for name in ("jwt_auth_secret", "qr_handshake_secret"):
            if len(getattr(self, name)) < MIN_SECRET_LENGTH:
                raise ValueError(f"{name.upper()} must be at least {MIN_SECRET_LENGTH} characters of random data")
        if self.jwt_auth_secret == self.qr_handshake_secret:
            raise ValueError("JWT_AUTH_SECRET and QR_HANDSHAKE_SECRET must be different")
        if any(origin.strip() == "*" for origin in self.allowed_origins):
            raise ValueError("ALLOWED_ORIGINS must list explicit origins, not *")
        return self


settings = Settings()
