"""Direct handler regression tests for external lead capture privacy.

Dependencies are mocked; these do not exercise HTTP authentication or the database.
No real customer data is used.
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
    with patch("app.routers.leads.get_lead_service", return_value=svc) as get_service:
        try:
            asyncio.run(capture_lead(CaptureLeadRequest(name="Test Lead", message="Private customer details"), request=None, key=key, _rl=None))
        except HTTPException as exc:
            assert exc.status_code == 422
            assert "not supported" in exc.detail
        else:
            raise AssertionError("Message capture must fail closed")
    get_service.assert_not_called()
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


def test_capture_uses_credential_org_not_request_data():
    from app.routers.leads import capture_lead, CaptureLeadRequest
    import asyncio

    org_id = "00000000-0000-4000-8000-000000000002"
    key = ApiKeyRecord(key_id="test", key_hash="test", name="test", scopes=["write"], organization_id=org_id)
    svc = AsyncMock()
    svc.create.return_value = {"id": "00000000-0000-4000-8000-000000000003"}
    svc.qualify.return_value = {"id": "00000000-0000-4000-8000-000000000003", "status": "new", "ai_tier": None}
    with patch("app.routers.leads.get_lead_service", return_value=svc), patch(
        "app.routers.leads._enqueue_lead_followup", new_callable=AsyncMock, return_value="no_definition"
    ) as enqueue:
        result = asyncio.run(capture_lead(CaptureLeadRequest(name="Test Lead", source="web"), request=None, key=key, _rl=None))
    svc.create.assert_awaited_once_with(org_id=org_id, name="Test Lead", email=None, phone=None, source="web")
    svc.qualify.assert_awaited_once_with(lead_id=result["id"], org_id=org_id)
    enqueue.assert_awaited_once_with(org_id=org_id, lead_id=result["id"], triggered_by="lead_capture", user_id=None)
    assert "organization_id" not in result


def test_capture_keeps_two_api_key_organizations_separate():
    """Handler-level regression: org scope comes from each credential."""
    import asyncio
    from app.routers.leads import capture_lead, CaptureLeadRequest

    org_a = "00000000-0000-4000-8000-000000000011"
    org_b = "00000000-0000-4000-8000-000000000022"
    svc = AsyncMock()
    svc.create.side_effect = [
        {"id": "00000000-0000-4000-8000-000000000031"},
        {"id": "00000000-0000-4000-8000-000000000032"},
    ]
    svc.qualify.side_effect = [
        {"id": "00000000-0000-4000-8000-000000000031", "status": "new"},
        {"id": "00000000-0000-4000-8000-000000000032", "status": "new"},
    ]
    with patch("app.routers.leads.get_lead_service", return_value=svc), patch(
        "app.routers.leads._enqueue_lead_followup", new_callable=AsyncMock, return_value="no_definition"
    ) as enqueue:
        for org in (org_a, org_b):
            key = ApiKeyRecord(key_id="test", key_hash="test", name="test", scopes=["write"], organization_id=org)
            asyncio.run(capture_lead(CaptureLeadRequest(name="Example"), request=None, key=key, _rl=None))

    assert [call.kwargs["org_id"] for call in svc.create.await_args_list] == [org_a, org_b]
    assert [call.kwargs["org_id"] for call in svc.qualify.await_args_list] == [org_a, org_b]
    assert [call.kwargs["org_id"] for call in enqueue.await_args_list] == [org_a, org_b]
