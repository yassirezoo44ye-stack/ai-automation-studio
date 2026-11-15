"""Regression tests for the external lead capture privacy guard.

These tests use FastAPI dependency overrides to exercise the real HTTP route
without database, outbound email or AI providers. No customer data is used.
"""
from unittest.mock import AsyncMock, patch

from app.core.api_keys import ApiKeyRecord


def test_capture_rejects_message_before_persisting():
    # This test is deliberately isolated from the real API-key and rate-limit
    # dependencies; it verifies the handler's privacy behavior, not auth.
    from app.routers.leads import capture_lead, CaptureLeadRequest
    import asyncio
    from fastapi import HTTPException

    key = ApiKeyRecord(key_id="test", key_hash="test", name="test", scopes=["write"], organization_id="00000000-0000-4000-8000-000000000001")
    svc = AsyncMock()
    with patch("app.routers.leads.get_lead_service", return_value=svc):
        try:
            asyncio.run(capture_lead(CaptureLeadRequest(name="Test Lead", message="Private customer details"), request=None, key=key, _rl=None))
        except HTTPException as exc:
            assert exc.status_code == 422
            assert "not supported" in exc.detail
        else:
            raise AssertionError("Message capture must fail closed")
    svc.create.assert_not_awaited()
    svc.qualify.assert_not_awaited()


def test_capture_rejects_unscoped_key():
    from app.routers.leads import capture_lead, CaptureLeadRequest
    import asyncio
    from fastapi import HTTPException

    key = ApiKeyRecord(key_id="test", key_hash="test", name="test", scopes=["write"], organization_id=None)
    try:
        asyncio.run(capture_lead(CaptureLeadRequest(name="Test Lead"), request=None, key=key, _rl=None))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Unscoped API keys must not capture leads")
