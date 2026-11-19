"""
/api/auth/refresh has its own rate-limit bucket.

Regression: refresh shared the 10/min "auth" bucket with login/register, and
the SPA calls it on every page load and new tab, so about 10 reloads in a
minute put a signed-in user behind a full-screen 429 and also used up their
login budget.
"""
from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import rate_limit
from app.routers import auth_users


def _pool_without_sessions():
    """A pool whose refresh lookup finds nothing, so every call is a 401."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _tx():
        yield

    conn.transaction = _tx

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = _acquire
    return pool


class RefreshRateLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        rate_limit.rl_store.clear()
        rate_limit._key_windows.clear()
        app = FastAPI()
        app.include_router(auth_users.router)
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        self._patch = patch.object(auth_users, "get_pool", _pool_without_sessions)
        self._patch.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self._patch.stop()
        rate_limit.rl_store.clear()
        rate_limit._key_windows.clear()

    async def _refresh(self):
        return await self.client.post("/api/auth/refresh", json={"refresh_token": "x" * 64})

    async def test_twenty_page_loads_in_a_minute_are_not_rate_limited(self):
        for _ in range(20):
            r = await self._refresh()
            self.assertEqual(r.status_code, 401)

    async def test_refresh_does_not_consume_the_login_bucket(self):
        for _ in range(15):
            await self._refresh()
        self.assertFalse(any(k.startswith("auth:") for k in rate_limit.rl_store))
        self.assertTrue(any(k.startswith("auth_refresh:") for k in rate_limit.rl_store))

    async def test_refresh_still_has_a_ceiling(self):
        for _ in range(auth_users.REFRESH_RATE_LIMIT_MAX_CALLS):
            self.assertEqual((await self._refresh()).status_code, 401)
        r = await self._refresh()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)

    async def test_login_bucket_is_unchanged(self):
        dep = auth_users._auth_rl.dependency
        req = MagicMock()
        req.headers = {}
        req.client.host = "10.0.0.1"
        for _ in range(10):
            dep(req)
        with self.assertRaises(Exception) as ctx:
            dep(req)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 429)


if __name__ == "__main__":
    unittest.main()
