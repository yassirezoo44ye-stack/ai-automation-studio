"""
Auth token lifecycle audit — regression tests for the fixes:

1. app/factory.py's api_auth_middleware now distinguishes an expired JWT
   ({"error": "token_expired"}) from invalid/missing credentials (generic
   {"detail": "Subscription required"}) — previously every failure reason
   collapsed into the identical response, giving a client no way to decide
   "silently refresh and retry" vs "force a full re-login."
2. app/routers/subscriptions.py's GET /api/subscription/status no longer
   auto-enrolls an arbitrary, unverified email into a trial and hands back
   a valid token for it (unauthenticated account impersonation) — it is
   now a read-only status check with no side effects and no token.
3. POST /api/subscription/verify no longer re-signs/extends a token with
   no password re-check — it only reports validity now.

DB-free throughout — ASGITransport does not run the app's lifespan, so
get_pool() is never touched unless the code path under test actually
needs the DB (mocked where it does), matching this suite's established
convention (see tests/security/test_authentication.py).
"""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

import jwt as pyjwt
from httpx import AsyncClient, ASGITransport

from app.core.auth import make_token
from app.core.config import SESSION_SECRET


def _app():
    from app.factory import create_app
    return create_app()


def _expired_jwt() -> str:
    now = time.time()
    return pyjwt.encode(
        {"sub": "u1", "email": "a@b.com", "type": "access", "iat": now - 1000, "exp": now - 1},
        SESSION_SECRET, algorithm="HS256",
    )


class TestApiAuthMiddlewareDistinguishesExpiredFromInvalid(unittest.IsolatedAsyncioTestCase):
    async def _post(self, headers: dict) -> "object":
        transport = ASGITransport(app=_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/projects", headers=headers)

    async def test_expired_jwt_returns_distinct_token_expired_error(self):
        res = await self._post({"Authorization": f"Bearer {_expired_jwt()}"})
        self.assertEqual(res.status_code, 401)
        body = res.json()
        self.assertEqual(body.get("error"), "token_expired")

    async def test_malformed_jwt_returns_generic_error_not_token_expired(self):
        res = await self._post({"Authorization": "Bearer not.a.valid.jwt"})
        self.assertEqual(res.status_code, 401)
        body = res.json()
        self.assertNotEqual(body.get("error"), "token_expired")
        self.assertEqual(body.get("detail"), "Subscription required")

    async def test_missing_credentials_returns_generic_error_not_token_expired(self):
        res = await self._post({})
        self.assertEqual(res.status_code, 401)
        body = res.json()
        self.assertNotEqual(body.get("error"), "token_expired")
        self.assertEqual(body.get("detail"), "Subscription required")

    async def test_valid_sub_token_is_not_rejected_by_the_middleware(self):
        """A valid sub_token must pass the middleware regardless of this
        change — proves the fix didn't touch the non-JWT branch. The
        downstream route has no live DB in this test, so a clean pass
        surfaces either as a non-401 response OR as a raised exception from
        the DB-less route handler itself (get_pool() is None) — Starlette's
        BaseHTTPMiddleware re-raises exceptions from call_next rather than
        converting them, so this is expected here, not a test bug. Either
        outcome proves the middleware did NOT short-circuit with its own
        401 — only a middleware-level rejection returns that specific
        response cleanly, since it happens before call_next is ever
        invoked."""
        tok = make_token("a@b.com", False, 0)
        try:
            res = await self._post({"X-Sub-Token": tok})
        except AttributeError as exc:
            self.assertIn("acquire", str(exc))  # the expected no-DB failure, not an auth 401
            return
        self.assertNotEqual(res.status_code, 401)


class TestSubscriptionStatusNoLongerMintsTokens(unittest.IsolatedAsyncioTestCase):
    """Regression test for the closed unauthenticated-impersonation bug:
    an arbitrary, never-seen-before email must never come back with a
    usable token or an auto-created trial."""

    def _fake_pool_no_existing_records(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # no subscription, no trial row
        conn.execute = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool, conn

    async def test_unknown_email_gets_no_token_and_no_trial_insert(self):
        from app.routers import subscriptions as subs_mod

        pool, conn = self._fake_pool_no_existing_records()
        with patch.object(subs_mod, "get_pool", return_value=pool), \
             patch("app.core.rate_limit.check_rate_limit", return_value=True):
            transport = ASGITransport(app=self._minimal_app(subs_mod))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get(
                    "/api/subscription/status", params={"email": "never-seen@example.com"},
                )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertNotIn("token", body)
        self.assertNotIn("trial", body)
        self.assertFalse(body["active"])
        # The old code did an "INSERT INTO trials" the moment no trial row
        # existed — assert that never happens now.
        for call in conn.execute.call_args_list:
            sql = call.args[0] if call.args else ""
            self.assertNotIn("INSERT INTO trials", sql)

    async def test_active_paid_subscription_reports_active_with_no_token(self):
        from app.routers import subscriptions as subs_mod
        from datetime import datetime, timedelta

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "status": "active", "current_period_end": datetime.utcnow() + timedelta(days=10),
        })
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(subs_mod, "get_pool", return_value=pool), \
             patch("app.core.rate_limit.check_rate_limit", return_value=True):
            transport = ASGITransport(app=self._minimal_app(subs_mod))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get(
                    "/api/subscription/status", params={"email": "paying@example.com"},
                )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body, {"active": True})  # no token key at all, on any branch

    def _minimal_app(self, subs_mod):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(subs_mod.router)
        return app


class TestVerifySessionNoLongerExtendsTokens(unittest.IsolatedAsyncioTestCase):
    async def test_valid_token_reports_validity_without_reissuing_a_token(self):
        from app.routers import subscriptions as subs_mod
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(subs_mod.router)
        tok = make_token("a@b.com", True, 5)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/subscription/verify", json={"token": tok})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["valid"])
        self.assertNotIn("token", body)

    async def test_invalid_token_reports_invalid(self):
        from app.routers import subscriptions as subs_mod
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(subs_mod.router)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/subscription/verify", json={"token": "garbage"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"valid": False})


if __name__ == "__main__":
    unittest.main()
