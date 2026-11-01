from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_resolve_org_uses_existing_membership_columns(monkeypatch):
    from app.routers import business_plans

    conn = AsyncMock()
    conn.fetchrow.return_value = {"organization_id": "org-1"}

    @asynccontextmanager
    async def acquire():
        yield conn

    class Pool:
        pass

    pool = Pool()
    pool.acquire = acquire
    monkeypatch.setattr(business_plans, "get_pool", lambda: pool)
    assert await business_plans._resolve_org("user-1") == "org-1"
    query, user = conn.fetchrow.call_args.args
    assert "ORDER BY created_at, organization_id" in query
    assert "deleted_at IS NULL" in query
    assert "joined_at" not in query
    assert user == "user-1"
    conn.fetchrow.return_value = None
    assert await business_plans._resolve_org("user-1") is None
