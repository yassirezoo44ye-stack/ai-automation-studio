"""Test configuration.

Sets test environment variables BEFORE any `app.*` module is imported (settings
are read once via `lru_cache`), points the app at a real local Postgres test
database (`socialpilot_test`), and provides an async HTTP client wired to the
ASGI app in-process (no real network socket) plus a raw AsyncSession for
assertions that need to look at the database directly.

Isolation strategy: truncate every app table before each test rather than
per-test transactions, because the app code itself commits (see
`app.core.db.get_db`) — a wrapping transaction would not see those commits
consistently across the multiple connections FastAPI's dependency system can
hand out during one request/response cycle.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/socialpilot_test"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-not-for-production-use-xxxxx")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("RATE_LIMIT_STORAGE_URL", "memory://")
os.environ.setdefault("AUTH_RATE_LIMIT", "1000/minute")
os.environ.setdefault("DATABASE_USE_NULL_POOL", "true")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, engine, get_db
from app.main import app

settings = get_settings()

_APP_TABLES = (
    "audit_logs",
    "refresh_tokens",
    "organization_members",
    "organizations",
    "users",
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    async def _override_get_db():
        async with AsyncSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def strong_password() -> str:
    return "Sup3rSecret1"
