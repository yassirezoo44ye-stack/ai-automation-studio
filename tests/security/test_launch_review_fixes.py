"""Regression tests for the pre-launch security review (2026-11-18).

Each test pins one fix:
  * password-reset links: hashed at rest, 30-minute TTL, atomic single use
  * failed logins: logged without the email, counted for alerting
  * HTTP -> HTTPS redirect behind the TLS-terminating proxy
  * OpenAPI/docs not served outside development
  * orchestrator 500s do not echo internal exception text
  * dashboard activity feed renders user text with textContent, not innerHTML
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import pathlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pool_for(conn):
    @asynccontextmanager
    async def _acquire():
        yield conn

    @asynccontextmanager
    async def _tx():
        yield None

    conn.transaction = MagicMock(side_effect=lambda: _tx())
    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=lambda: _acquire())
    return pool


# ── Password reset links ────────────────────────────────────────────────────

def test_forgot_password_stores_only_a_hash_with_30_minute_expiry():
    from app.routers import auth_users as au

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "u1"})
    conn.execute = AsyncMock()
    sent = {}

    async def _send(to, token):
        sent["token"] = token

    with patch.object(au, "get_pool", return_value=_pool_for(conn)), \
            patch.object(au, "send_password_reset_email", new=_send):
        before = datetime.datetime.now(datetime.timezone.utc)
        asyncio.run(au.forgot_password(au.ForgotPasswordRequest(email="a@example.com"), None))

    insert = [c for c in conn.execute.await_args_list
              if "INSERT INTO password_reset_tokens" in c.args[0]][0]
    stored_token, _uid, expires_at = insert.args[1], insert.args[2], insert.args[3]
    raw = sent["token"]
    assert stored_token != raw, "raw reset token must never be stored"
    assert stored_token == hashlib.sha256(raw.encode()).hexdigest()
    ttl = expires_at - before
    assert datetime.timedelta(minutes=29) < ttl <= datetime.timedelta(minutes=31)


def _run_reset(consumed_row):
    from app.routers import auth_users as au

    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        consumed_row,
        {"user_id": "11111111-1111-1111-1111-111111111111", "email": "a@example.com"},
    ])
    with patch.object(au, "get_pool", return_value=_pool_for(conn)), \
            patch.object(au, "hash_password", return_value="h"), \
            patch.object(au, "revoke_user_tokens", new=AsyncMock()), \
            patch.object(au, "write_audit", new=AsyncMock()), \
            patch.object(au.asyncio, "create_task", MagicMock()):
        result = asyncio.run(au.reset_password(
            au.ResetPasswordRequest(token="raw-token", password="NewPass123"), None))
    return conn, result


def test_reset_password_consumes_token_atomically_by_hash():
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
    conn, result = _run_reset({"user_id": "u1", "expires_at": future})
    first = conn.fetchrow.await_args_list[0]
    assert first.args[0].startswith("DELETE FROM password_reset_tokens")
    assert "RETURNING" in first.args[0]
    assert first.args[1] == hashlib.sha256(b"raw-token").hexdigest()
    sqls = [c.args[0] for c in conn.execute.await_args_list]
    assert any("DELETE FROM user_sessions" in q for q in sqls)
    assert "successfully" in result["message"]


def test_reset_password_rejects_reused_or_unknown_token():
    with pytest.raises(HTTPException) as e:
        _run_reset(None)
    assert e.value.status_code == 400


def test_reset_password_rejects_expired_token():
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
    with pytest.raises(HTTPException) as e:
        _run_reset({"user_id": "u1", "expires_at": past})
    assert e.value.status_code == 400


# ── Failed-login monitoring ─────────────────────────────────────────────────

def test_failed_login_event_is_logged_without_email_and_counted(caplog):
    from app.core.observability.metrics import get_metrics
    from app.routers import auth_users as au

    counter = get_metrics().counter("auth_login_failures_total")
    before = counter.value if hasattr(counter, "value") else None
    with caplog.at_level(logging.WARNING, logger=au.log.name):
        au._record_failed_login_event("Victim@Example.com", "1.2.3.4", "invalid_credentials")
    text = caplog.text
    assert "auth.login_failed" in text
    assert "victim@example.com" not in text.lower()
    if before is not None:
        assert counter.value == before + 1


def test_failed_login_alert_rule_is_seeded():
    from app.services.alerting import _DEFAULT_RULES
    assert any(r[2] == "auth_login_failures_total" for r in _DEFAULT_RULES)


# ── HTTPS + docs ────────────────────────────────────────────────────────────

def _mini_app():
    from fastapi import FastAPI
    from app.factory import HTTPSRedirectBehindProxyMiddleware

    app = FastAPI()

    @app.get("/x")
    async def _x():
        return {"ok": True}

    app.add_middleware(HTTPSRedirectBehindProxyMiddleware)
    return app


def test_plain_http_behind_proxy_is_redirected_in_production(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("ENVIRONMENT", "production")
    c = TestClient(_mini_app())
    r = c.get("/x?a=1", headers={"X-Forwarded-Proto": "http", "Host": "api.example.com"},
              follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"] == "https://api.example.com/x?a=1"
    ok = c.get("/x", headers={"X-Forwarded-Proto": "https"})
    assert ok.status_code == 200
    assert c.get("/x").status_code == 200  # health checks without the header


def test_no_https_redirect_in_development(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("ENVIRONMENT", "development")
    r = TestClient(_mini_app()).get("/x", headers={"X-Forwarded-Proto": "http"},
                                    follow_redirects=False)
    assert r.status_code == 200


def test_openapi_and_docs_hidden_outside_development(monkeypatch):
    from app.factory import create_app
    monkeypatch.setenv("ENVIRONMENT", "production")
    app = create_app()
    assert app.openapi_url is None and app.docs_url is None and app.redoc_url is None
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert create_app().openapi_url == "/openapi.json"


# ── Error detail leakage ────────────────────────────────────────────────────

def test_orchestrator_500_does_not_echo_exception_text():
    src = (ROOT / "app/routers/orchestrator.py").read_text()
    assert 'status_code=500, detail=str(exc)' not in src


# ── Stored XSS in the static dashboard ──────────────────────────────────────

@pytest.mark.parametrize("path", ["public/dashboard.html", "dashboard.html"])
def test_dashboard_activity_feed_does_not_use_innerhtml_for_user_text(path):
    src = (ROOT / path).read_text()
    assert "prompt_preview" in src
    assert "el.innerHTML" not in src
    assert "strong.textContent" in src
