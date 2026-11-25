"""Perf audit M1 (2026-11-17): the DB pool must survive bursts.

Before the fix, login held one pooled connection while write_audit()
acquired a second. With DB_POOL_MAX (default 10) logins arriving at the
same moment, every login held one connection and waited forever for
another: the whole pool deadlocked, every DB route hung until restart,
and /health still answered 200.

Real app, real auth, real PostgreSQL, synthetic users only.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

from tests_e2e.harness import PASSWORD, tenants

pytestmark = pytest.mark.asyncio(loop_scope="session")

POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def tenant(e2e_transport):
    async with tenants(e2e_transport, "load", ip_prefix="10.97.0") as t:
        yield t["load"]


async def test_simultaneous_logins_do_not_deadlock_the_pool(tenant):
    n = POOL_MAX + 5

    async def login(i: int):
        # One source IP per login: the per-IP auth rate limit is not under test.
        return await tenant.client.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": f"10.97.1.{i + 1}"},
            json={"email": tenant.email, "password": PASSWORD},
        )

    responses = await asyncio.wait_for(
        asyncio.gather(*(login(i) for i in range(n))), timeout=60,
    )
    assert [r.status_code for r in responses] == [200] * n
    tenant.client.cookies.clear()

    # The pool is usable afterwards: a DB-backed route answers promptly.
    r = await asyncio.wait_for(tenant.req("GET", "/api/automations"), timeout=15)
    assert r.status_code == 200, r.text


async def test_exhausted_pool_fails_fast_instead_of_hanging(e2e_transport):
    from app.core.db import PoolExhausted, get_pool

    pool = get_pool()
    held = [await pool.acquire() for _ in range(pool.get_max_size())]
    try:
        with pytest.raises(PoolExhausted):
            async with pool.acquire(timeout=0.5):
                pass
    finally:
        for conn in held:
            await pool.release(conn)

    async with pool.acquire() as conn:  # and recovers once released
        assert await conn.fetchval("SELECT 1") == 1
