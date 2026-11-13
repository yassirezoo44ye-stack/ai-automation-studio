"""The dependency monitor reports missing optional settings once per change.

It used to log the same WARNING every 5 minutes for a permanent gap
(GitHub sign-in not configured), ~288 lines a day that buried real errors.
"""
import asyncio
import logging
from unittest.mock import MagicMock, patch

from app.services.dependency_monitor import DependencyMonitorService


def _tick(svc):
    with patch("app.core.observability.metrics.get_metrics") as m:
        m.return_value = MagicMock(gauge=MagicMock(return_value=MagicMock(set=MagicMock())))
        asyncio.run(svc.tick())


def _warnings(caplog):
    return [r for r in caplog.records if "missing optional env vars" in r.getMessage()]


def test_optional_gap_is_warned_once_then_again_only_when_it_changes(monkeypatch, caplog):
    for var in ("ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY", "GOOGLE_CLIENT_ID"):
        monkeypatch.setenv(var, "x")
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    svc = DependencyMonitorService()

    with caplog.at_level(logging.INFO, logger="app.services.dependency_monitor"):
        _tick(svc)
        _tick(svc)
        _tick(svc)
        assert len(_warnings(caplog)) == 1

        monkeypatch.delenv("GOOGLE_CLIENT_ID")
        _tick(svc)
        assert len(_warnings(caplog)) == 2

        monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
        monkeypatch.setenv("GITHUB_CLIENT_ID", "x")
        _tick(svc)
        assert any("now set" in r.getMessage() for r in caplog.records)
