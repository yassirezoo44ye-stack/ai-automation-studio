"""
Regression test for the AUDIT FIX to app/core/auth.py::extract_auth_credentials:
a `sub_token` cookie is no longer accepted as a credential — nothing in this
codebase ever sets that cookie (the token is only ever handed to clients in a
JSON response body, stored/sent via the X-Sub-Token header), so the cookie
fallback was a dead, unreachable-via-legitimate-flows path that stayed
trusted for auth (a real risk if this domain ever shares a parent domain with
a less-trusted subdomain that can plant cookies for it).

DB-free — ASGITransport does not run the app's lifespan, matching this
suite's established convention (see tests/security/test_authentication.py).
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from httpx import AsyncClient, ASGITransport

from app.core.auth import extract_auth_credentials, make_token


def _app():
    from app.factory import create_app
    return create_app()


class TestExtractAuthCredentialsIgnoresCookie(unittest.TestCase):
    def test_sub_token_cookie_alone_yields_no_credential(self):
        from starlette.requests import Request

        scope = {
            "type": "http", "method": "GET", "path": "/api/projects",
            "headers": [(b"cookie", b"sub_token=" + make_token("a@b.com", False, 0).encode())],
        }
        req = Request(scope)
        sub_token, bearer = extract_auth_credentials(req)
        self.assertEqual(sub_token, "")
        self.assertEqual(bearer, "")

    def test_x_sub_token_header_still_works(self):
        from starlette.requests import Request

        tok = make_token("a@b.com", False, 0)
        scope = {
            "type": "http", "method": "GET", "path": "/api/projects",
            "headers": [(b"x-sub-token", tok.encode())],
        }
        req = Request(scope)
        sub_token, bearer = extract_auth_credentials(req)
        self.assertEqual(sub_token, tok)


class TestSubTokenCookieRejectedByRealMiddleware(unittest.IsolatedAsyncioTestCase):
    """End-to-end proof through the real api_auth_middleware, not just the
    extraction helper in isolation."""

    async def test_valid_sub_token_sent_only_as_a_cookie_is_rejected(self):
        tok = make_token("a@b.com", False, 0)
        transport = ASGITransport(app=_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/projects", cookies={"sub_token": tok})
        self.assertEqual(res.status_code, 401)

    async def test_same_valid_sub_token_sent_as_the_header_is_not_rejected_by_the_middleware(self):
        """Sanity check that the fix didn't also break the legitimate
        X-Sub-Token header path (mirrors test_auth_token_lifecycle_fixes.py's
        equivalent check)."""
        tok = make_token("a@b.com", False, 0)
        transport = ASGITransport(app=_app())
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get("/api/projects", headers={"X-Sub-Token": tok})
        except AttributeError as exc:
            self.assertIn("acquire", str(exc))  # expected no-DB failure downstream, not an auth 401
            return
        self.assertNotEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
