"""Concurrency correctness: two requests racing to use the same refresh token
must not both succeed — exactly one winner, matching the duplicate-protection
requirement the scheduler/publishing pipeline will lean on in later phases.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, get_db
from app.main import app
from tests.conftest import unique_email

settings = get_settings()

pytestmark = pytest.mark.asyncio


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


async def test_concurrent_refresh_with_the_same_token_only_one_wins(client) -> None:
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email(), "password": "Sup3rSecret1", "full_name": "Racer"},
    )
    assert reg.status_code == 201
    raw_refresh = reg.cookies[settings.refresh_cookie_name]
    csrf = reg.json()["csrf_token"]

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)

    async def _attempt() -> int:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post(
                "/api/v1/auth/refresh",
                headers={"X-CSRF-Token": csrf},
                cookies={settings.refresh_cookie_name: raw_refresh, settings.csrf_cookie_name: csrf},
            )
            return r.status_code

    try:
        results = await asyncio.gather(*[_attempt() for _ in range(8)])
    finally:
        app.dependency_overrides.clear()

    assert results.count(200) == 1, f"expected exactly one winner, got {results}"
    assert results.count(401) == 7
