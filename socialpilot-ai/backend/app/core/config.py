"""Application settings, loaded from environment variables (.env in dev).

No secret ever has a real-looking default here — production must set every
`Field(...)` (required) value explicitly, and the app refuses to boot in
`ENVIRONMENT=production` with an insecure/default secret (see `Settings.validate_for_production`).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "SocialPilot AI"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/socialpilot"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 5
    database_echo: bool = False
    # NullPool: opens a fresh physical connection per checkout instead of pooling.
    # Tests set this to true — pytest-asyncio's event-loop lifecycle otherwise leaves
    # pooled asyncpg connections bound to a loop that's gone by the next test/task,
    # surfacing as "Future attached to a different loop". Not for production use.
    database_use_null_pool: bool = False

    # --- Redis / Queue ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth / JWT ---
    jwt_secret_key: str = Field(default="dev-insecure-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # --- Cookies ---
    cookie_domain: str | None = None
    cookie_secure: bool = True
    refresh_cookie_name: str = "sp_refresh_token"
    csrf_cookie_name: str = "sp_csrf_token"

    # --- CORS ---
    # `NoDecode` + the `mode="before"` validator below: pydantic-settings would
    # otherwise require CORS_ALLOWED_ORIGINS to be JSON (`'["a","b"]'`) since the
    # field type is a list. We want plain comma-separated values to work too
    # (`CORS_ALLOWED_ORIGINS=http://a,http://b`), which is the friendlier and far
    # more common shape for this env var across hosting providers.
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # --- Rate limiting ---
    rate_limit_storage_url: str | None = None  # falls back to redis_url, then in-memory
    auth_rate_limit: str = "10/minute"
    ai_generation_rate_limit: str = "20/minute"

    # --- AI provider abstraction (Phase 2+) ---
    ai_provider: str = "anthropic"
    ai_api_key: str | None = None
    ai_model: str = "claude-sonnet-4-5"

    # --- Object storage (Phase 5+) ---
    storage_provider: Literal["s3", "local"] = "local"
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_production(self) -> None:
        """Fail fast on boot rather than run insecurely in prod."""
        if not self.is_production:
            return
        if self.jwt_secret_key == "dev-insecure-secret-change-me" or len(self.jwt_secret_key) < 32:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a strong random value (>=32 chars) in production."
            )
        if not self.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production.")
        if self.ai_provider == "mock":
            raise RuntimeError(
                "AI_PROVIDER=mock (deterministic canned responses, no real AI call) is for local "
                "development/CI/E2E only — set a real provider (e.g. AI_PROVIDER=anthropic) in production."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
