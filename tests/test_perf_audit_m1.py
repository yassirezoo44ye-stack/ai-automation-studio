"""Unit guards for the perf audit M1 fixes (2026-11-17).

The deadlock itself is reproduced end to end in
tests_e2e/test_pool_under_load.py (real PostgreSQL)."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FailingAcquire:
    async def __aenter__(self):
        raise TimeoutError

    async def __aexit__(self, *exc):
        return False


class _OkAcquire:
    def __init__(self):
        self.conn = MagicMock()
        self.conn.fetchval = AsyncMock(return_value=1)

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


def _pool(ctx):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.fixture
def health(monkeypatch):
    import app.routers.health as h
    monkeypatch.setattr(h, "startup_complete", True)
    monkeypatch.setattr(h, "_db_stalled_since", None)
    return h


def test_liveness_ok_when_pool_hands_out_a_connection(health):
    with patch("app.core.db.get_pool", return_value=_pool(_OkAcquire())):
        body = asyncio.run(health.liveness())
    assert body["status"] == "alive"


def test_liveness_tolerates_a_short_stall(health):
    with patch("app.core.db.get_pool", return_value=_pool(_FailingAcquire())):
        body = asyncio.run(health.liveness())
    assert isinstance(body, dict) and body["status"] == "alive"


def test_liveness_fails_after_a_sustained_stall_and_recovers(health, monkeypatch):
    monkeypatch.setattr(health, "_db_stalled_since", time.monotonic() - health._DB_STALL_RESTART_S - 1)
    with patch("app.core.db.get_pool", return_value=_pool(_FailingAcquire())):
        resp = asyncio.run(health.liveness())
    assert resp.status_code == 503
    with patch("app.core.db.get_pool", return_value=_pool(_OkAcquire())):
        body = asyncio.run(health.liveness())
    assert body["status"] == "alive" and health._db_stalled_since is None


def test_liveness_skips_db_before_startup(monkeypatch):
    import app.routers.health as h
    monkeypatch.setattr(h, "startup_complete", False)
    with patch("app.core.db.get_pool", return_value=_pool(_FailingAcquire())) as gp:
        body = asyncio.run(h.liveness())
    assert body["status"] == "alive"
    gp.return_value.acquire.assert_not_called()


@pytest.mark.parametrize("env,expected", [
    ({}, False),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"}, True),
    ({"OBS_HTTP_TRACING_ENABLED": "true"}, True),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4317", "OBS_TRACING_ENABLED": "false"}, False),
])
def test_http_tracing_only_with_an_exporter(monkeypatch, env, expected):
    from app.core.observability.config import ObservabilityConfig
    for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OBS_HTTP_TRACING_ENABLED", "OBS_TRACING_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert ObservabilityConfig().http_tracing_enabled is expected


def test_write_audit_reuses_the_callers_connection():
    from app.core import db
    conn = MagicMock()
    conn.is_in_transaction = MagicMock(return_value=False)
    conn.execute = AsyncMock()
    with patch.object(db, "get_pool") as gp:
        asyncio.run(db.write_audit("a@example.com", "login", conn=conn))
    conn.execute.assert_awaited_once()
    gp.assert_not_called()


def test_login_verifies_password_off_the_event_loop():
    import app.routers.auth_users as au
    seen = {}

    def fake_verify(plain, hashed):
        try:
            asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        return True

    with patch.object(au, "verify_password", fake_verify):
        assert asyncio.run(au._verify_pw("x", "y")) is True
    assert seen["on_loop"] is False
