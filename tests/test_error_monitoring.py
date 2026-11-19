"""Error monitoring stays off without SENTRY_DSN and never breaks requests."""
import sys
import types

from app.core import error_monitoring as em


def test_disabled_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert em.init_error_monitoring() is False
    assert em.is_enabled() is False
    em.capture_exception(RuntimeError("ignored"))  # no-op, must not raise


def test_enabled_with_dsn_and_no_pii(monkeypatch):
    calls: dict = {}
    captured: list = []
    fake = types.SimpleNamespace(
        init=lambda **kw: calls.update(kw),
        capture_exception=lambda exc: captured.append(exc),
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setenv("SENTRY_DSN", "https://key@example.ingest.sentry.io/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "5")  # clamped to 1.0

    assert em.init_error_monitoring() is True
    assert calls["send_default_pii"] is False
    assert calls["max_request_body_size"] == "never"
    assert calls["traces_sample_rate"] == 1.0

    err = ValueError("boom")
    em.capture_exception(err)
    assert captured == [err]

    monkeypatch.delenv("SENTRY_DSN")
    em.init_error_monitoring()


def test_capture_never_raises(monkeypatch):
    def broken(_exc):
        raise RuntimeError("sentry down")

    monkeypatch.setitem(sys.modules, "sentry_sdk", types.SimpleNamespace(init=lambda **kw: None, capture_exception=broken))
    monkeypatch.setenv("SENTRY_DSN", "https://key@example.ingest.sentry.io/1")
    em.init_error_monitoring()
    em.capture_exception(ValueError("x"))  # must swallow
    monkeypatch.delenv("SENTRY_DSN")
    em.init_error_monitoring()
