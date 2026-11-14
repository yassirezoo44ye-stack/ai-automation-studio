"""Browser-origin handoff, cookie binding and precise middleware exceptions."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.core.cache import redis_adapter
from app.integrations.social.mock import MockSocialPublisherProvider
from app.integrations.social.oauth_handoff import is_public_social_oauth_request
from app.routers import social_publisher as social
from app.tenancy.context import OrgContext, org_context


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/api/social/accounts/tiktok/callback", True),
        ("POST", "/api/social/accounts/tiktok/authorize", True),
        ("GET", "/api/social/accounts/instagram/callback", True),
        ("POST", "/api/social/accounts/youtube/authorize", True),
        ("GET", "/api/social/accounts/tiktok/authorize", False),
        ("POST", "/api/social/accounts/tiktok/callback", False),
        ("GET", "/api/social/accounts/tiktok/connect", False),
        ("GET", "/api/social/accounts", False),
        ("POST", "/api/social/posts", False),
        ("GET", "/api/social/accounts/tiktok/callback/extra", False),
        ("GET", "/api/social/accounts/mock/callback", False),
    ],
)
def test_oauth_exception_is_exact(method, path, expected):
    assert is_public_social_oauth_request(method, path) is expected


@pytest_asyncio.fixture
async def flow(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://flow.example")
    cache = redis_adapter.RedisAdapter(
        redis_adapter.LocalCacheBackend(), namespace="oauth-test"
    )

    async def get_cache():
        return cache

    monkeypatch.setattr(redis_adapter, "get_redis", get_cache)
    provider = MockSocialPublisherProvider("tiktok", "TikTok")
    provider.get_auth_url = lambda redirect_uri, state: (
        f"https://provider.example/authorize?state={state}"
    )
    provider.exchange_code = AsyncMock(side_effect=provider.exchange_code)
    registry = MagicMock()
    registry.get_or_raise.return_value = provider
    monkeypatch.setattr(social, "get_social_registry", lambda: registry)
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "platform": "tiktok",
        "platform_user_id": "remote-user",
        "platform_username": "creator",
        "platform_name": "Creator",
        "scopes": [],
        "is_active": True,
        "metadata": {},
        "connected_at": datetime.now(UTC),
    }

    @asynccontextmanager
    async def acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = acquire
    monkeypatch.setattr(social, "get_pool", lambda: pool)
    app = FastAPI()
    app.include_router(social.router)
    app.dependency_overrides[org_context] = lambda: OrgContext(
        str(uuid.uuid4()), str(uuid.uuid4()), "owner@example.com", "owner"
    )

    # Exercise the same public-path decision as the application middleware.
    @app.middleware("http")
    async def middleware(request, call_next):
        if (
            not is_public_social_oauth_request(request.method, request.url.path)
            and request.headers.get("authorization") != "Bearer test-session"
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://api.example"
    ) as client:
        yield client, provider, cache, conn


async def ticket(client):
    res = await client.get(
        "/api/social/accounts/tiktok/connect",
        headers={"Authorization": "Bearer test-session"},
    )
    assert res.status_code == 200 and "set-cookie" not in res.headers
    assert res.headers["cache-control"] == "no-store"
    return res.json()


@pytest.mark.asyncio
async def test_authenticated_start_top_level_cookie_and_callback(flow):
    client, provider, _cache, _conn = flow
    assert (await client.get("/api/social/accounts/tiktok/connect")).status_code == 401
    data = await ticket(client)
    result = await client.post(
        data["auth_url"],
        data={"ticket": data["ticket"]},
        headers={"Origin": "https://flow.example"},
    )
    assert result.status_code == 303
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    state = parse_qs(urlsplit(result.headers["location"]).query)["state"][0]
    result = await client.get(
        "/api/social/accounts/tiktok/callback",
        params={"state": state, "code": "test-code"},
    )
    assert result.status_code == 200
    provider.exchange_code.assert_awaited_once()
    # Replay has neither usable ticket nor callback state.
    assert (
        await client.post(
            data["auth_url"],
            data={"ticket": data["ticket"]},
            headers={"Origin": "https://flow.example"},
        )
    ).status_code == 400
    assert (
        await client.get(
            "/api/social/accounts/tiktok/callback",
            params={"state": state, "code": "test-code"},
        )
    ).status_code == 400


@pytest.mark.asyncio
async def test_foreign_or_missing_origin_cannot_bind_victims_browser(flow):
    client, provider, _cache, _conn = flow
    data = await ticket(client)
    for headers in [{}, {"Origin": "https://attacker.example"}, {"Origin": "null"}]:
        res = await client.post(
            data["auth_url"], data={"ticket": data["ticket"]}, headers=headers
        )
        assert res.status_code == 403 and "set-cookie" not in res.headers
    result = await client.post(
        data["auth_url"],
        data={"ticket": data["ticket"]},
        headers={"Origin": "https://flow.example"},
    )
    state = parse_qs(urlsplit(result.headers["location"]).query)["state"][0]
    client.cookies.clear()
    assert (
        await client.get(
            "/api/social/accounts/tiktok/callback",
            params={"state": state, "code": "test-code"},
        )
    ).status_code == 400
    provider.exchange_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_ticket_and_wrong_platform_are_rejected(flow):
    client, provider, cache, _conn = flow
    data = await ticket(client)
    await cache.delete("social_oauth_handoff:" + data["ticket"])
    assert (
        await client.post(
            data["auth_url"],
            data={"ticket": data["ticket"]},
            headers={"Origin": "https://flow.example"},
        )
    ).status_code == 400
    data = await ticket(client)
    res = await client.post(
        "/api/social/accounts/instagram/authorize",
        data={"ticket": data["ticket"]},
        headers={"Origin": "https://flow.example"},
    )
    assert res.status_code == 400
    provider.exchange_code.assert_not_awaited()
