"""Unit guards for bugs the M9 end-to-end journeys found (tests_e2e/test_journeys.py).

Each test fails on the code before its fix.
"""
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


# ── Journey 6: automation definitions ─────────────────────────────────────────

def test_definition_rejects_steps_the_scheduler_would_skip():
    from app.core.workflow.automation_api import DefinitionCreate, DefinitionUpdate

    for bad in (
        {"steps": [{"id": "a", "kind": "emial"}]},
        {"steps": [{"id": "a"}, {"id": "a"}]},
        {"steps": [{"id": "a", "depends_on": ["missing"]}]},
        {"steps": [{"id": "a", "depends_on": ["a"]}]},
        {"steps": [{"kind": "noop"}]},
        {"steps": "not a list"},
    ):
        with pytest.raises(ValidationError):
            DefinitionCreate(name="x", definition=bad)
        with pytest.raises(ValidationError):
            DefinitionUpdate(definition=bad)
    with pytest.raises(ValidationError):
        DefinitionCreate(name="   ", definition={})


def test_definition_accepts_the_shapes_the_app_creates():
    from app.core.workflow.automation_api import DefinitionCreate, DefinitionUpdate

    # LeadsPage follow-up, production's existing email step, missing kind = noop.
    DefinitionCreate(name="Lead follow-up", definition={"lead_followup": "true", "steps": [
        {"id": "draft", "kind": "noop"},
        {"id": "send", "kind": "email", "args": {"subject": "Hi"}, "requires_approval": True, "depends_on": ["draft"]},
    ]})
    DefinitionCreate(name="no steps", definition={})
    DefinitionCreate(name="plain", definition={"steps": [{"id": "a"}, {"id": "b", "kind": "ai", "depends_on": ["a"]}]})
    assert DefinitionUpdate(is_active=True).definition is None


# ── Journey 10: Stripe ────────────────────────────────────────────────────────

async def test_subscription_webhook_handles_stripe_objects(monkeypatch):
    """stripe-python 8+ objects are not dicts; the handler used .get() on them."""
    import app.core.config as cfg
    from app.routers import subscriptions

    secret = "whsec_unit"
    monkeypatch.setattr(cfg, "STRIPE_WEBHOOK_SECRET", secret)
    body = json.dumps({"id": "evt_unit", "object": "event", "type": "customer.subscription.updated",
                       "data": {"object": {"id": "sub_1", "object": "subscription", "status": "active",
                                           "current_period_end": 1_900_000_000,
                                           "metadata": {"organization_id": "o", "plan_id": "starter"}}}})
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()

    seen = {}

    class _Svc:
        async def record(self, **kw):
            return True

        async def mark_processed(self, event_id):
            seen["processed"] = event_id

        async def mark_failed(self, event_id, err):
            seen["failed"] = err

    async def dispatch(event):
        seen["period_end"] = event["data"]["object"].get("current_period_end")
        seen["plan"] = event["data"]["object"].get("metadata", {}).get("plan_id")

    import app.billing as billing
    monkeypatch.setattr(billing, "get_webhook_event_service", lambda: _Svc())
    monkeypatch.setattr(subscriptions, "_dispatch_webhook_event", dispatch)

    class _Req:
        headers = {"stripe-signature": f"t={ts},v1={sig}"}

        async def body(self):
            return body.encode()

    assert await subscriptions.stripe_webhook(_Req()) == {"received": True}
    assert seen == {"period_end": 1_900_000_000, "plan": "starter", "processed": "evt_unit"}


async def test_checkout_without_stripe_is_503_not_500(monkeypatch):
    import stripe

    from app.routers import subscriptions

    monkeypatch.setattr(stripe, "api_key", None)
    with pytest.raises(HTTPException) as exc:
        await subscriptions.create_checkout(subscriptions.CheckoutRequest(email="a@example.com"))
    assert exc.value.status_code == 503


# ── Journey 7: devices ────────────────────────────────────────────────────────

def test_device_not_found_is_404():
    from app.routers.devices import _bad_request

    assert _bad_request(ValueError("Session not found")).status_code == 404
    assert _bad_request(ValueError("Device not found or already revoked")).status_code == 404
    assert _bad_request(ValueError("Session cannot be started from status 'stopped'")).status_code == 400


# ── Journey 8: content ────────────────────────────────────────────────────────

def test_creations_accept_the_login_access_token(monkeypatch):
    from app.core import jwt_utils
    from app.routers import discover

    monkeypatch.setattr(jwt_utils, "decode_access_token", lambda t: {"sub": "u1", "email": "a@example.com"})

    class _Req:
        headers = {"Authorization": "Bearer header.payload.sig"}

    discover._require_auth(_Req())  # used to raise 401

    class _Anon:
        headers = {}

    with pytest.raises(HTTPException) as exc:
        discover._require_auth(_Anon())
    assert exc.value.status_code == 401
