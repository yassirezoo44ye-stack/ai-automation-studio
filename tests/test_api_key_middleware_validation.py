"""
Regression tests: api_auth_middleware must VALIDATE API keys, not just
notice the header.

Background
----------
app/factory.py's api_auth_middleware used to let any request carrying an
`X-API-Key` or `Authorization: ApiKey ...` header through without checking
the key, deferring to a require_api_key() dependency that most routes never
declare. A junk header (`X-API-Key: x`) therefore bypassed authentication on
dozens of routes (diagnostics traces/metrics, agent memory, AI usage/cost,
kernel execute/rollback, service stop). The middleware now validates the key
itself, and platform-wide operator endpoints additionally require a platform
admin (ADMIN_EMAILS user, or an API key with the "admin" scope).
"""
from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient

import app.core.api_keys as api_keys_mod
from app.core.api_keys import ApiKeyRecord
from app.core.auth import make_token

VALID_KEY = "axon_validkey000000000000000000000000000000"
ADMIN_KEY = "axon_adminkey000000000000000000000000000000"
REVOKED_KEY = "axon_revokedkey0000000000000000000000000000"
EXPIRED_KEY = "axon_expiredkey0000000000000000000000000000"

ADMIN_ONLY_ROUTES = [
    "/api/diagnostics/services/__nope__/start",
    "/api/diagnostics/services/__nope__/stop",
    "/api/diagnostics/alerts/rules",
    "/api/diagnostics/alerts/rules/__nope__/toggle",
    "/api/diagnostics/codegen/__nope__/approve",
    "/api/diagnostics/codegen/__nope__/reject",
    "/api/kernel/execute",
    "/api/kernel/rollback/99999",
]


def _rec(key_id: str, scopes: list[str], *, active: bool = True, expires_at: float | None = None) -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id=key_id, key_hash=f"hash-{key_id}", name=key_id, scopes=scopes,
        owner_id="system", organization_id=None, active=active, expires_at=expires_at,
    )


_RECORDS = {
    VALID_KEY: _rec("valid", ["read", "write"]),
    ADMIN_KEY: _rec("admin", ["admin"]),
    REVOKED_KEY: _rec("revoked", ["read"], active=False),
    EXPIRED_KEY: _rec("expired", ["read"], expires_at=time.time() - 60),
}


@pytest.fixture(scope="module")
def app():
    from app.factory import create_app
    return create_app()


@pytest.fixture(autouse=True)
def fake_key_store(monkeypatch):
    async def _lookup(raw: str):
        return _RECORDS.get(raw)
    monkeypatch.setattr(api_keys_mod, "lookup_key", _lookup)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("headers", [
    {"X-API-Key": "junk"},
    {"Authorization": "ApiKey junk"},
    {"X-API-Key": "axon_unknown0000000000000000000000000000000"},
    {"X-API-Key": REVOKED_KEY},
    {"X-API-Key": EXPIRED_KEY},
])
async def test_invalid_api_key_rejected_by_middleware(client, headers):
    res = await client.get("/api/runtimes", headers=headers)
    assert res.status_code == 401


@pytest.mark.parametrize("headers", [
    {"X-API-Key": VALID_KEY},
    {"Authorization": f"ApiKey {VALID_KEY}"},
])
async def test_valid_api_key_passes_middleware(client, headers):
    res = await client.get("/api/runtimes", headers=headers)
    assert res.status_code == 200


async def test_key_store_failure_fails_closed(client, monkeypatch):
    async def _boom(raw: str):
        raise RuntimeError("db down")
    monkeypatch.setattr(api_keys_mod, "lookup_key", _boom)
    res = await client.get("/api/runtimes", headers={"X-API-Key": VALID_KEY})
    assert res.status_code == 503


async def test_junk_key_reaches_no_protected_get_route(app, client):
    """Sweep every parameter-free protected GET route: a junk key must be
    stopped by the middleware (401) before any handler runs."""
    from app.core.config import PUBLIC_PREFIXES
    from app.integrations.social.oauth_handoff import is_public_social_oauth_request
    from app.routers.study_library import is_public_study_request

    paths = sorted(
        p for p, ops in app.openapi()["paths"].items()
        if "get" in ops and p.startswith("/api/") and "{" not in p
        and not any(p.startswith(x) for x in PUBLIC_PREFIXES)
        and not is_public_social_oauth_request("GET", p)
        and not is_public_study_request("GET", p)
    )
    assert len(paths) > 50
    leaked = []
    for p in paths:
        res = await client.get(p, headers={"X-API-Key": "junk"})
        if res.status_code != 401:
            leaked.append((p, res.status_code))
    assert leaked == []


@pytest.mark.parametrize("path", ADMIN_ONLY_ROUTES)
async def test_admin_routes_reject_non_admin_api_key(client, path):
    res = await client.post(path, json={}, headers={"X-API-Key": VALID_KEY})
    assert res.status_code == 403


@pytest.mark.parametrize("path", ADMIN_ONLY_ROUTES)
async def test_admin_routes_reject_non_admin_session(client, path, monkeypatch):
    monkeypatch.setattr("app.core.config.ADMIN_EMAILS", frozenset({"boss@example.com"}))
    token = make_token("someone@example.com", trial=False, days_remaining=30)
    res = await client.post(path, json={}, headers={"X-Sub-Token": token})
    assert res.status_code == 403


async def test_admin_route_allows_admin_session(client, monkeypatch):
    monkeypatch.setattr("app.core.config.ADMIN_EMAILS", frozenset({"boss@example.com"}))
    token = make_token("Boss@example.com", trial=False, days_remaining=30)
    res = await client.post("/api/diagnostics/services/__nope__/stop", headers={"X-Sub-Token": token})
    assert res.status_code == 404  # reached the handler: unknown service


async def test_admin_route_allows_admin_scoped_key(client):
    res = await client.post("/api/diagnostics/services/__nope__/stop", headers={"X-API-Key": ADMIN_KEY})
    assert res.status_code == 404
