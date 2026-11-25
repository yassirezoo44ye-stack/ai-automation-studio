"""Direct handler regression tests for external lead capture privacy.

Dependencies are mocked; these do not exercise HTTP authentication or the database.
No real customer data is used.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response
from starlette.requests import Request

from app.core.api_keys import ApiKeyRecord
from tests.test_idempotency import FakeIdempotencyPool


def _request(headers: dict | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/api/leads/capture",
                    "headers": raw})


@pytest.fixture(autouse=True)
def _idempotency_pool():
    """capture_lead claims each submission in idempotency_keys; give it an
    in-memory pool so these handler tests stay database-free."""
    pool = FakeIdempotencyPool()
    with patch("app.core.db.get_pool", return_value=pool):
        yield pool


def _capture(body, key, headers=None, response=None):
    from app.routers.leads import capture_lead
    import asyncio
    return asyncio.run(capture_lead(body, request=_request(headers),
                                    response=response or Response(), key=key, _rl=None))


def test_capture_rejects_message_before_persisting():
    # This test is deliberately isolated from the real API-key and rate-limit
    # dependencies; it verifies the handler's privacy behavior, not auth.
    from app.routers.leads import CaptureLeadRequest
    from fastapi import HTTPException

    key = ApiKeyRecord(key_id="test", key_hash="test", name="test", scopes=["write"], organization_id="00000000-0000-4000-8000-000000000001")
    svc = AsyncMock()
    with patch("app.routers.leads.get_lead_service", return_value=svc) as get_service:
        try:
            _capture(CaptureLeadRequest(name="Test Lead", message="Private customer details"), key)
        except HTTPException as exc:
            assert exc.status_code == 422
            assert "not supported" in exc.detail
        else:
            raise AssertionError("Message capture must fail closed")
    get_service.assert_not_called()
    svc.create.assert_not_awaited()
    svc.qualify.assert_not_awaited()


def test_capture_rejects_unscoped_key():
    from app.routers.leads import CaptureLeadRequest
    from fastapi import HTTPException

    key = ApiKeyRecord(key_id="test", key_hash="test", name="test", scopes=["write"], organization_id=None)
    try:
        _capture(CaptureLeadRequest(name="Test Lead"), key)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Unscoped API keys must not capture leads")


def test_capture_uses_credential_org_not_request_data():
    from app.routers.leads import CaptureLeadRequest

    org_id = "00000000-0000-4000-8000-000000000002"
    key = ApiKeyRecord(key_id="test", key_hash="test", name="test", scopes=["write"], organization_id=org_id)
    svc = AsyncMock()
    svc.create.return_value = {"id": "00000000-0000-4000-8000-000000000003"}
    svc.qualify.return_value = {"id": "00000000-0000-4000-8000-000000000003", "status": "new", "ai_tier": None}
    with patch("app.routers.leads.get_lead_service", return_value=svc), patch(
        "app.routers.leads._enqueue_lead_followup", new_callable=AsyncMock, return_value="no_definition"
    ) as enqueue:
        result = _capture(CaptureLeadRequest(name="Test Lead", source="web"), key)
    svc.create.assert_awaited_once_with(org_id=org_id, name="Test Lead", email=None, phone=None, source="web")
    svc.qualify.assert_awaited_once_with(lead_id=result["id"], org_id=org_id)
    enqueue.assert_awaited_once_with(org_id=org_id, lead_id=result["id"], triggered_by="lead_capture", user_id=None)
    assert "organization_id" not in result


def test_capture_keeps_two_api_key_organizations_separate():
    """Handler-level regression: org scope comes from each credential."""
    from app.routers.leads import CaptureLeadRequest

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
            _capture(CaptureLeadRequest(name="Example"), key)

    assert [call.kwargs["org_id"] for call in svc.create.await_args_list] == [org_a, org_b]
    assert [call.kwargs["org_id"] for call in svc.qualify.await_args_list] == [org_a, org_b]
    assert [call.kwargs["org_id"] for call in enqueue.await_args_list] == [org_a, org_b]


def _svc(*ids):
    svc = AsyncMock()
    svc.create.side_effect = [{"id": i} for i in ids]
    svc.qualify.side_effect = [{"id": i, "status": "new", "ai_tier": None} for i in ids]
    return svc


def test_capture_resend_without_key_replays_first_lead():
    from app.routers.leads import CaptureLeadRequest
    org = "00000000-0000-4000-8000-000000000041"
    key = ApiKeyRecord(key_id="t", key_hash="t", name="t", scopes=["write"], organization_id=org)
    svc = _svc("lead-1", "lead-2")
    with patch("app.routers.leads.get_lead_service", return_value=svc), patch(
        "app.routers.leads._enqueue_lead_followup", new_callable=AsyncMock, return_value="enqueued"
    ) as enqueue:
        first = _capture(CaptureLeadRequest(name="Ana  Example", email="Ana@Example.com",
                                            phone="+971 50 000 0000"), key)
        resp = Response()
        # Same person, different casing/spacing/phone formatting.
        again = _capture(CaptureLeadRequest(name="ana example", email="ana@example.com ",
                                            phone="+971-50-000-0000"), key, response=resp)
    assert again == first
    assert resp.headers["Idempotent-Replayed"] == "true"
    assert svc.create.await_count == 1
    assert enqueue.await_count == 1


def test_capture_idempotency_key_reused_with_other_body_is_422():
    from fastapi import HTTPException
    from app.routers.leads import CaptureLeadRequest
    org = "00000000-0000-4000-8000-000000000042"
    key = ApiKeyRecord(key_id="t", key_hash="t", name="t", scopes=["write"], organization_id=org)
    svc = _svc("lead-1", "lead-2")
    with patch("app.routers.leads.get_lead_service", return_value=svc), patch(
        "app.routers.leads._enqueue_lead_followup", new_callable=AsyncMock, return_value="enqueued"
    ):
        _capture(CaptureLeadRequest(name="First"), key, headers={"Idempotency-Key": "abc-1"})
        with pytest.raises(HTTPException) as exc:
            _capture(CaptureLeadRequest(name="Second"), key, headers={"Idempotency-Key": "abc-1"})
    assert exc.value.status_code == 422
    assert svc.create.await_count == 1


def test_capture_in_flight_duplicate_is_409(_idempotency_pool):
    from fastapi import HTTPException
    from app.routers.leads import CaptureLeadRequest
    org = "00000000-0000-4000-8000-000000000043"
    key = ApiKeyRecord(key_id="t", key_hash="t", name="t", scopes=["write"], organization_id=org)
    svc = _svc("lead-1")
    # Another worker holds the claim right now.
    _idempotency_pool.rows[("lead_capture", f"{org}:k:" + __import__("hashlib").sha256(b"k-9").hexdigest())] = {
        "status": "pending", "result": None, "error": None, "age_s": 0}
    with patch("app.routers.leads.get_lead_service", return_value=svc):
        with pytest.raises(HTTPException) as exc:
            _capture(CaptureLeadRequest(name="X"), key, headers={"Idempotency-Key": "k-9"})
    assert exc.value.status_code == 409
    svc.create.assert_not_awaited()


@pytest.mark.parametrize("bad", ["", "x" * 256, "has space", "ünicode"])
def test_capture_rejects_malformed_idempotency_key(bad):
    from fastapi import HTTPException
    from app.routers.leads import CaptureLeadRequest
    key = ApiKeyRecord(key_id="t", key_hash="t", name="t", scopes=["write"],
                       organization_id="00000000-0000-4000-8000-000000000044")
    with pytest.raises(HTTPException) as exc:
        _capture(CaptureLeadRequest(name="X"), key, headers={"Idempotency-Key": bad})
    assert exc.value.status_code == 400
