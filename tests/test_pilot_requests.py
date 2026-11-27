"""POST /api/pilot-requests — the landing page's paid-pilot form."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routers.pilot_requests as pr

ORG = str(uuid.uuid4())
GOOD = {
    "name": "  Sara   Ali ",
    "email": "sara@agency.example",
    "company": "Bright Agency",
    "team_size": "6-20",
    "task": "Weekly client reports take us six hours every Monday.",
    "lang": "ar",
}


@pytest.fixture
def env(monkeypatch):
    lead_svc = MagicMock()
    lead_svc.create = AsyncMock(return_value={"id": str(uuid.uuid4())})
    notif_svc = MagicMock()
    notif_svc.org_member_ids = AsyncMock(return_value=["u1", "u2"])
    notif_svc.create = AsyncMock(return_value={"id": "n"})
    ws = MagicMock()
    ws.broadcast = AsyncMock()

    import app.core.leads as leads_pkg
    import app.core.notifications.service as notif_mod
    import app.routers.ws as ws_mod
    monkeypatch.setattr(leads_pkg, "get_lead_service", lambda: lead_svc)
    monkeypatch.setattr(notif_mod, "get_notification_service", lambda: notif_svc)
    monkeypatch.setattr(ws_mod, "manager", ws)
    monkeypatch.setenv("PILOT_LEADS_ORG_ID", ORG)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    from app.core import rate_limit
    monkeypatch.setattr(rate_limit, "check_rate_limit", lambda *a, **k: True)

    app = FastAPI()
    app.include_router(pr.router)
    return TestClient(app), lead_svc, notif_svc


def test_request_becomes_lead_and_notifies_every_member(env):
    client, lead_svc, notif_svc = env
    r = client.post("/api/pilot-requests", json=GOOD)
    assert r.status_code == 202
    assert r.json() == {"status": "received"}

    kw = lead_svc.create.await_args.kwargs
    assert kw == {"org_id": ORG, "name": "Sara Ali", "email": "sara@agency.example",
                  "source": "landing_pilot"}
    assert notif_svc.create.await_count == 2
    n = notif_svc.create.await_args.kwargs
    assert n["organization_id"] == ORG
    assert n["title"] == "Pilot request: Bright Agency"
    assert "six hours every Monday" in n["message"]
    assert "team 6-20" in n["message"]


def test_free_text_is_kept_off_the_lead(env):
    client, lead_svc, _ = env
    client.post("/api/pilot-requests", json=GOOD)
    assert GOOD["task"] not in str(lead_svc.create.await_args)


def test_unconfigured_org_answers_503_and_stores_nothing(env, monkeypatch):
    client, lead_svc, _ = env
    monkeypatch.delenv("PILOT_LEADS_ORG_ID")
    r = client.post("/api/pilot-requests", json=GOOD)
    assert r.status_code == 503
    lead_svc.create.assert_not_awaited()


def test_invalid_org_id_answers_503(env, monkeypatch):
    client, lead_svc, _ = env
    monkeypatch.setenv("PILOT_LEADS_ORG_ID", "not-a-uuid")
    assert client.post("/api/pilot-requests", json=GOOD).status_code == 503
    lead_svc.create.assert_not_awaited()


def test_honeypot_is_accepted_silently_and_dropped(env):
    client, lead_svc, notif_svc = env
    r = client.post("/api/pilot-requests", json={**GOOD, "website": "http://spam"})
    assert r.status_code == 202
    lead_svc.create.assert_not_awaited()
    notif_svc.create.assert_not_awaited()


@pytest.mark.parametrize("patch", [
    {"email": "not-an-email"},
    {"name": "   "},
    {"task": "short"},
    {"task": "x" * 1001},
    {"team_size": "500"},
    {"lang": "fr"},
])
def test_invalid_input_is_rejected(env, patch):
    client, lead_svc, _ = env
    assert client.post("/api/pilot-requests", json={**GOOD, **patch}).status_code == 422
    lead_svc.create.assert_not_awaited()


def test_storage_failure_is_503_not_500(env):
    client, lead_svc, _ = env
    lead_svc.create.side_effect = RuntimeError("db down")
    assert client.post("/api/pilot-requests", json=GOOD).status_code == 503


def test_notification_failure_still_accepts(env):
    client, lead_svc, notif_svc = env
    notif_svc.org_member_ids.side_effect = RuntimeError("boom")
    assert client.post("/api/pilot-requests", json=GOOD).status_code == 202
    lead_svc.create.assert_awaited_once()


def test_rate_limited_at_five_per_hour(env, monkeypatch):
    client, _, _ = env
    seen = {}

    def fake(key, max_calls, window):
        seen.update(key=key, max_calls=max_calls, window=window)
        return False

    from app.core import rate_limit
    monkeypatch.setattr(rate_limit, "check_rate_limit", fake)
    assert client.post("/api/pilot-requests", json=GOOD).status_code == 429
    assert seen["key"].startswith("pilot_request:")
    assert (seen["max_calls"], seen["window"]) == (5, 3600)


def test_path_is_public():
    from app.core.config import PUBLIC_PREFIXES
    assert any("/api/pilot-requests".startswith(p) for p in PUBLIC_PREFIXES)
    # and nothing else under /api/pilot* was opened by accident
    assert not any("/api/pilot-requests/admin".startswith(p) and p != "/api/pilot-requests"
                   for p in PUBLIC_PREFIXES)


def test_router_is_registered_in_app_factory():
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "factory.py")) as f:
        src = f.read()
    assert "include_router(pilot_requests_router.router)" in src
