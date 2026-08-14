"""
Regression test: api_auth_middleware must NOT block API-key requests.

Background
----------
app/factory.py's api_auth_middleware guards every /api/* path that is not
in PUBLIC_PREFIXES. It used to check only X-Sub-Token / Authorization: Bearer
(JWT) and return 401 "Subscription required" for anything else — which meant
that ANY request using Authorization: ApiKey or X-API-Key was silently
rejected with 401 before the FastAPI route handler (and its
require_api_key() dependency) ever ran. The fix adds an elif branch that
recognises the ApiKey scheme and the X-API-Key header and lets those
requests pass through to require_api_key() for proper validation.

This file proves the fix and prevents regressions.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from httpx import AsyncClient, ASGITransport  # noqa: E402


def _app():
    from app.factory import create_app
    return create_app()


# ── Middleware passthrough tests ──────────────────────────────────────────────

class TestApiKeyMiddlewarePassthrough(unittest.IsolatedAsyncioTestCase):
    """End-to-end proof through the real api_auth_middleware (same pattern as
    tests/test_auth_credentials_cookie_fallback_removed.py)."""

    async def _assert_not_subscription_required(self, headers: dict) -> None:
        """Hit a middleware-protected endpoint with the given headers; verify
        the middleware did NOT return the "Subscription required" sentinel."""
        transport = ASGITransport(app=_app())
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get("/api/projects", headers=headers)
        except AttributeError as exc:
            # DB interaction failed downstream (expected in DB-free test env).
            # An exception from that depth proves the middleware let the
            # request through.
            self.assertIn("acquire", str(exc))
            return
        body = res.json() if "application/json" in res.headers.get("content-type", "") else {}
        self.assertNotEqual(
            body.get("detail"),
            "Subscription required",
            f"api_auth_middleware wrongly blocked API-key request with "
            f"'Subscription required' (headers={headers}, status={res.status_code}, body={body})",
        )

    async def test_authorization_apikey_scheme_passes_middleware(self):
        """Authorization: ApiKey axon_... must NOT be blocked by middleware."""
        await self._assert_not_subscription_required(
            {"Authorization": "ApiKey axon_testkey00000000000000000000000000000000"}
        )

    async def test_x_api_key_header_passes_middleware(self):
        """X-API-Key: axon_... must NOT be blocked by middleware."""
        await self._assert_not_subscription_required(
            {"X-API-Key": "axon_testkey00000000000000000000000000000000"}
        )

    async def test_no_credentials_still_blocked_by_middleware(self):
        """Sanity check: a request with no auth must still get 401 from
        middleware so the fix doesn't accidentally open the gates entirely."""
        transport = ASGITransport(app=_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/projects")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(
            res.json().get("detail"),
            "Subscription required",
            "Unauthenticated requests must still be rejected by middleware",
        )

    async def test_public_prefix_unaffected(self):
        """/api/auth/* is in PUBLIC_PREFIXES and must always pass through the
        middleware (no auth header required)."""
        transport = ASGITransport(app=_app())
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/api/auth/login",
                    json={"email": "x@example.com", "password": "pw"},
                )
        except AttributeError as exc:
            self.assertIn("acquire", str(exc))
            return
        # Must NOT be a middleware 401 — any other failure is fine.
        body = res.json() if "application/json" in res.headers.get("content-type", "") else {}
        self.assertNotEqual(body.get("detail"), "Subscription required")


if __name__ == "__main__":
    unittest.main()
