"""Business Creator API tests without external provider calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.routers import business_creator as api


def test_plan_returns_real_not_executed_status():
    result = api._plan(api.PlanRequest(capability="app", description="Create an inventory tracker"))
    assert result["status"] == "planned_not_executed"


def test_invalid_capability_returns_422():
    with pytest.raises(HTTPException) as exc:
        api._plan(api.PlanRequest(capability="invalid", description="Create an inventory tracker"))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_unverified_adapter_refuses_execution(monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(api, "get_pipeline", lambda: SimpleNamespace(start=start))
    with pytest.raises(HTTPException) as exc:
        await api.execute(
            api.PlanRequest(capability="voiceover", description="Produce an audio narration"),
            SimpleNamespace(org_id="org-1", user_id="user-1"),
        )
    assert exc.value.status_code == 409
    start.assert_not_awaited()


@pytest.mark.asyncio
async def test_app_submission_uses_authenticated_tenant(monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(api, "get_pipeline", lambda: SimpleNamespace(start=start))
    result = await api.execute(
        api.PlanRequest(capability="app", description="Create an inventory tracker"),
        SimpleNamespace(org_id="org-1", user_id="user-1"),
    )
    assert result["status"] == "submitted"
    assert result["published"] is False
    start.assert_awaited_once()
    assert start.await_args.kwargs["org_id"] == "org-1"
    assert start.await_args.kwargs["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_store_submission_explicitly_requests_storefront(monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(api, "get_pipeline", lambda: SimpleNamespace(start=start))
    result = await api.execute(
        api.PlanRequest(capability="store", description="Sell handmade products to customers"),
        SimpleNamespace(org_id="org-1", user_id="user-1"),
    )
    assert result["status"] == "submitted"
    assert "online store" in start.await_args.kwargs["idea_text"]
    assert "product catalog" in start.await_args.kwargs["idea_text"]
    assert start.await_args.kwargs["org_id"] == "org-1"
