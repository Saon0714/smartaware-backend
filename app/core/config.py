"""Application settings.

Every value here comes from the environment. Nothing that varies between
environments — and nothing secret — may be hardcoded elsewhere in the app.

Values that SmartAWARE staff must be able to change at runtime (chat retention
window, invite expiry, escalation threshold, notification recipients) do NOT
live here: they live in the `settings` DB table and are read through
`app.core.settings_service`. This class is for deploy-time configuration only.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Application ---
    ENVIRONMENT: Literal["local", "test", "staging", "production"] = "local"
    DEBUG: bool = False
    PROJECT_NAME: str = "SmartAWARE API"
    API_V1_PREFIX: str = "/api/v1"

    # --- Database ---
    DATABASE_URL: str = "postgresql+psycopg://smartaware:smartaware@localhost:5432/smartaware"
    # Echo every statement. Off even in local dev: it buries script output.
    SQL_ECHO: bool = False

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --- CORS ---
    # Explicit allowlist. The frontend is a separate origin, so this is a real
    # security boundary — a wildcard is never acceptable here, and credentialed
    # requests (our auth cookie) would be rejected by browsers anyway.
    # NoDecode stops pydantic-settings JSON-decoding this before the
    # validator runs, so a plain comma-separated env var works.
    CORS_ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # --- Auth (see BUILD_PLAN Q1) ---
    # Short-lived access token held in memory by the SPA; long-lived refresh
    # token in an httpOnly cookie so XSS cannot exfiltrate a durable session.
    JWT_SECRET_KEY: str = "dev-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 14

    REFRESH_COOKIE_NAME: str = "smartaware_refresh"
    # Unset locally (host-only cookie). In production set to ".smartaware.com"
    # so app.* and api.* are same-site and SameSite=Lax holds.
    COOKIE_DOMAIN: str | None = None
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # --- Frontend ---
    # Used to build links in outbound email (invites, notifications).
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # --- OpenAI ---
    OPENAI_API_KEY: str = ""
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_DIMENSIONS: int = 1536

    # --- AWS ---
    AWS_REGION: str = "eu-west-2"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "smartaware-documents-local"
    S3_PRESIGNED_URL_TTL_SECONDS: int = 900
    SES_SENDER_EMAIL: str = "no-reply@smartaware.example"
    # Local dev writes uploads to disk and emails to stdout instead of AWS.
    USE_LOCAL_STORAGE: bool = True
    USE_CONSOLE_EMAIL: bool = True

    # --- Wise (Section 12) ---
    # A single Open Payment Link obtained manually from the Wise Business
    # dashboard. We only ever append query params to it. There is deliberately
    # no Wise API credential here: creating payment links via the Wise API is
    # unsupported and must not be built.
    # Empty by default. A plausible-looking placeholder would put a live Pay
    # Now button in front of clients pointing at a page that does not exist.
    WISE_PAYMENT_LINK_BASE_URL: str = ""

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
