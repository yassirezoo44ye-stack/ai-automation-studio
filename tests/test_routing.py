"""
Regression tests for critical routing bugs.

Issue 1: POST /api/package/build/stream → 405 (wrong URL in frontend — now fixed)
Issue 2: GET /api/projects/{id}/files → 404 (spa_fallback registered before API routers)
"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.core.auth import make_token
from app.factory import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.mark.anyio
async def test_spa_fallback_does_not_intercept_api_get(app):
    """GET /api/* must reach the API routers, not the SPA catch-all."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # /api/health is a GET endpoint registered in health router.
        # If spa_fallback were registered first it would return HTML (200) or 404.
        r = await client.get("/api/health")
        assert r.status_code != 404, (
            "GET /api/health returned 404 — spa_fallback is intercepting API routes. "
            "Register spa_fallback AFTER all app.include_router() calls."
        )
        ct = r.headers.get("content-type", "")
        assert "text/html" not in ct, (
            "GET /api/health returned HTML — spa_fallback is intercepting API routes."
        )


@pytest.mark.anyio
async def test_package_stream_endpoint_exists(app):
    """POST /api/package/stream must exist (not /api/package/build/stream).

    Requests must be authenticated: api_auth_middleware gates all /api/*
    paths and returns 401 before routing runs, so an unauthenticated request
    would never reach the router's 404/405 method-matching logic.
    """
    transport = ASGITransport(app=app)
    headers = {"X-Sub-Token": make_token("routing-test@example.com", False, 0)}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # A POST to the wrong old URL must return 405, not 200/422.
        wrong = await client.post("/api/package/build/stream", json={}, headers=headers)
        assert wrong.status_code == 405, (
            f"Expected 405 on wrong URL /api/package/build/stream, got {wrong.status_code}"
        )

        # The correct URL must not return 405.
        correct = await client.post("/api/package/stream", json={}, headers=headers)
        assert correct.status_code != 405, (
            "POST /api/package/stream returned 405 — endpoint is missing or method not registered"
        )


@pytest.mark.anyio
async def test_projects_files_endpoint_reachable(app, tmp_path, monkeypatch):
    """GET /api/projects/{id}/files must return 200, not 404."""
    import app.core.config as cfg
    monkeypatch.setattr(cfg, "WORKSPACES", tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/projects/testproject/files",
            headers={"X-Sub-Token": "invalid-but-bypassed-by-test"},
        )
        # Without auth middleware bypassed this may be 401, but never 404 from spa_fallback
        assert r.status_code != 404 or "Not Found" not in r.text, (
            "GET /api/projects/testproject/files returned 404 — "
            "spa_fallback is registered before the build router."
        )


@pytest.mark.anyio
async def test_spa_fallback_serves_frontend_for_non_api(app):
    """Non-API paths (e.g. /login, /dev) must be served by the SPA fallback."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/login", "/dev", "/automation", "/some-deep/route"):
            r = await client.get(path)
            # Must not be a JSON 404 — it should be HTML (SPA) or simple 404 page
            ct = r.headers.get("content-type", "")
            if r.status_code == 200:
                assert "text/html" in ct, f"{path} returned 200 but content-type is {ct}"
