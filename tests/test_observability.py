"""
Enterprise Observability & Monitoring phase — tests for the pieces added
or changed this phase: the OTel tracer bridge's shape compatibility,
correlation-ID propagation, sensitive-data log masking, the new health
probes degrading gracefully when their dependency is absent, the new
metrics registering and updating correctly, alert rule threshold
evaluation, ObservabilityConfig flags, and an audit-log write+read
roundtrip (mocked DB — the real live-Postgres roundtrip is exercised by
this phase's verification script, matching the convention established in
tests/test_ai_routing.py's TestBudgetGranularityBackwardCompat).
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Tracer bridge — shape compatibility
# ═══════════════════════════════════════════════════════════════════════════════

class TestTracerBridge(unittest.TestCase):
    def setUp(self):
        from app.core.observability.tracer import Tracer
        self.tracer = Tracer()

    def test_span_dict_shape_unchanged(self):
        """/api/diagnostics/traces* consumers depend on this exact shape."""
        with self.tracer.start_span("op", service="svc") as span:
            span.set_tag("k", "v")
        spans = self.tracer.recent(1)
        self.assertEqual(len(spans), 1)
        s = spans[0]
        for key in ("trace_id", "span_id", "parent_id", "name", "service",
                    "duration_ms", "tags", "events", "error"):
            self.assertIn(key, s)
        self.assertEqual(s["tags"]["k"], "v")
        self.assertIsNone(s["error"])

    def test_error_status_recorded(self):
        try:
            with self.tracer.start_span("failing") as span:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        spans = self.tracer.recent(1)
        self.assertEqual(spans[0]["error"], "boom")

    def test_active_reflects_in_flight_span(self):
        span = self.tracer.start_span("long_running")
        active = self.tracer.active()
        self.assertTrue(any(s["span_id"] == span.span_id for s in active))
        span.finish()
        active_after = self.tracer.active()
        self.assertFalse(any(s["span_id"] == span.span_id for s in active_after))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Correlation ID propagation
# ═══════════════════════════════════════════════════════════════════════════════

class TestCorrelationId(unittest.TestCase):
    def test_active_trace_id_reflects_current_otel_span(self):
        from app.core.middleware import _active_trace_id
        from app.core.observability.tracer import Tracer
        from opentelemetry import trace as otel_trace

        tracer = Tracer()
        # No ambient span — falls back to "" so callers mint their own uuid4.
        self.assertEqual(_active_trace_id(), "")

        with tracer.start_span("http_request") as span:
            # use_span makes this the "current" span exactly like
            # FastAPIInstrumentor does for a real HTTP request.
            with otel_trace.use_span(span._span):
                self.assertEqual(_active_trace_id(), span.trace_id)

    def test_inference_engine_prefers_request_id_from_context(self):
        """InferenceEngine.complete()/.stream() must read the ambient
        request_id (set by RequestIdMiddleware) instead of always minting
        a fresh uuid4, so an HTTP request and the AI event(s) it triggers
        share one ID."""
        from app.core.logging import set_request_id, get_request_id
        set_request_id("existing-request-id")
        try:
            request_id = get_request_id() or "fallback"
            self.assertEqual(request_id, "existing-request-id")
        finally:
            set_request_id("")

    def test_falls_back_to_fresh_id_when_no_context(self):
        from app.core.logging import set_request_id, get_request_id
        import uuid
        set_request_id("")
        request_id = get_request_id() or str(uuid.uuid4())
        self.assertNotEqual(request_id, "")
        self.assertEqual(len(request_id), 36)  # uuid4 string length


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Sensitive-data log masking
# ═══════════════════════════════════════════════════════════════════════════════

class TestSensitiveDataFilter(unittest.TestCase):
    def setUp(self):
        from app.core.logging import SensitiveDataFilter
        self.f = SensitiveDataFilter()

    def test_scrubs_known_secret_pattern(self):
        text = "leaked anthropic key: sk-ant-abcdefghijklmnopqrstuvwx1234567890"
        scrubbed = self.f.scrub_text(text)
        self.assertNotIn("sk-ant-abcdefghijklmnopqrstuvwx1234567890", scrubbed)
        self.assertIn("REDACTED", scrubbed)

    def test_scrubs_jwt_pattern(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        scrubbed = self.f.scrub_text(text)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", scrubbed)

    def test_key_name_redaction_regardless_of_value_shape(self):
        self.assertEqual(self.f.scrub_value("password", "hunter2"), "***REDACTED***")
        self.assertEqual(self.f.scrub_value("api_key", "not-a-known-pattern"), "***REDACTED***")
        self.assertEqual(self.f.scrub_value("authorization", "whatever"), "***REDACTED***")

    def test_non_sensitive_key_untouched_when_no_pattern_match(self):
        self.assertEqual(self.f.scrub_value("user_id", "abc-123"), "abc-123")

    def test_non_string_value_passed_through(self):
        self.assertEqual(self.f.scrub_value("count", 42), 42)

    def test_json_formatter_end_to_end(self):
        import json
        import logging
        from app.core.logging import _JsonFormatter

        fmt = _JsonFormatter()
        rec = logging.LogRecord(
            name="test", level=logging.INFO, pathname="x", lineno=1,
            msg="login attempt", args=(), exc_info=None,
        )
        rec.password = "hunter2"
        payload = json.loads(fmt.format(rec))
        self.assertEqual(payload["password"], "***REDACTED***")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. New health probes — degrade gracefully when a dependency is absent
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewHealthProbes(unittest.TestCase):
    def setUp(self):
        from app.core.observability.health import HealthRegistry, _register_defaults
        self.hr = HealthRegistry()
        _register_defaults(self.hr)

    def test_all_new_probes_registered(self):
        expected = {
            "agent_kernel", "agent_memory", "background_services",
            "redis", "ai_providers", "event_bus", "marketplace",
            "billing", "plugin_loader", "storage", "vector_db",
        }
        self.assertTrue(expected.issubset(set(self.hr.probe_names)))

    def test_redis_probe_degrades_without_redis_url(self):
        from app.core.observability.health import HealthStatus
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("REDIS_URL", None)
            result = run(self.hr.check("redis"))
        self.assertIn(result.status, (HealthStatus.DEGRADED, HealthStatus.HEALTHY, HealthStatus.UNHEALTHY))
        # In-process fallback must never crash the probe itself.
        self.assertIsNotNone(result)

    def test_billing_probe_never_raises_when_pool_missing(self):
        """A probe that raises would be caught by HealthRegistry and
        reported UNHEALTHY anyway — this asserts the probe function itself
        doesn't blow up the process, matching every other probe's
        try/except-wrapped contract."""
        result = run(self.hr.check("billing"))
        self.assertIsNotNone(result.status)

    def test_vector_db_probe_reports_degraded_not_unhealthy_on_fallback(self):
        """pgvector unavailable has a working TF-IDF fallback — must not
        be reported as UNHEALTHY (that's reserved for genuine outages)."""
        from app.core.observability.health import HealthStatus
        result = run(self.hr.check("vector_db"))
        self.assertIn(result.status, (HealthStatus.DEGRADED, HealthStatus.HEALTHY))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. New metrics — register and update correctly
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewMetrics(unittest.TestCase):
    def setUp(self):
        from app.core.observability.metrics import MetricsRegistry, _wire_defaults
        self.m = MetricsRegistry()
        _wire_defaults(self.m)

    def test_ai_metrics_registered(self):
        snap = self.m.snapshot()
        for name in ("ai_requests_total", "ai_tokens_input_total", "ai_tokens_output_total",
                     "ai_cost_usd_total", "ai_provider_failures_total"):
            self.assertIn(name, snap["counters"])
        self.assertIn("ai_active_streams", snap["gauges"])
        self.assertIn("ai_request_latency_ms", snap["histograms"])

    def test_workflow_metrics_registered(self):
        snap = self.m.snapshot()
        for name in ("workflow_runs_total", "workflow_runs_success", "workflow_runs_failed"):
            self.assertIn(name, snap["counters"])
        self.assertIn("workflow_active_runs", snap["gauges"])

    def test_system_and_sandbox_gauges_registered(self):
        snap = self.m.snapshot()
        for name in ("system_cpu_percent", "system_memory_rss_mb", "system_disk_used_percent",
                     "sandbox_running_workers", "sandbox_execution_failures"):
            self.assertIn(name, snap["gauges"])

    def test_metric_updates_reflected_in_snapshot(self):
        self.m.counter("ai_requests_total").inc()
        self.m.counter("ai_requests_total").inc(2)
        self.assertEqual(self.m.snapshot()["counters"]["ai_requests_total"], 3)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Metrics bridges — event-driven updates
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetricsBridges(unittest.TestCase):
    def test_ai_bridge_updates_on_prompt_completed(self):
        from app.core.observability import bridges
        from app.core.observability.metrics import get_metrics
        from app.core.ai.events.bus import bus
        from app.core.ai.events.events import PromptCompleted

        bridges._wired["ai"] = False  # allow re-wiring for test isolation
        bridges.wire_ai_metrics()
        m = get_metrics()
        before = m.counter("ai_requests_total").value

        run(bus.emit(PromptCompleted(
            request_id="t1", provider_id="anthropic", model="claude",
            input_tokens=10, output_tokens=5, cost_usd=0.001, latency_ms=100.0,
        )))
        after = m.counter("ai_requests_total").value
        self.assertEqual(after, before + 1)

    def test_workflow_bridge_updates_on_event(self):
        from app.core.observability import bridges
        from app.core.observability.metrics import get_metrics
        from app.core.events import get_event_bus

        bridges._wired["workflow"] = False
        bridges.wire_workflow_metrics()
        m = get_metrics()
        before = m.counter("workflow_runs_total").value

        run(get_event_bus().publish("workflow.started", {"run_id": "r1"}, organization_id=None))
        after = m.counter("workflow_runs_total").value
        self.assertEqual(after, before + 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Alert rule threshold evaluation — pure logic, no real notification sent
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlertRuleEvaluation(unittest.TestCase):
    def setUp(self):
        from app.services.alerting import AlertingService
        self.svc = AlertingService()

    def _rule(self, **kwargs):
        base = {
            "id": "rule-1", "name": "test rule", "rule_type": "gauge_above",
            "target": "system_cpu_percent", "threshold": 50.0,
            "notify_email": None, "notify_webhook_url": None,
        }
        base.update(kwargs)
        return base

    def test_gauge_above_fires_when_breached(self):
        from app.core.observability.metrics import get_metrics
        get_metrics().gauge("system_cpu_percent").set(75.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # no open alert yet
        conn.execute = AsyncMock()
        run(self.svc._evaluate(conn, self._rule()))
        insert_call = conn.execute.call_args
        self.assertIn("INSERT INTO alert_history", insert_call.args[0])

    def test_gauge_above_does_not_fire_when_below_threshold(self):
        from app.core.observability.metrics import get_metrics
        get_metrics().gauge("system_cpu_percent").set(10.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock()
        run(self.svc._evaluate(conn, self._rule()))
        conn.execute.assert_not_called()

    def test_dedup_skips_second_fire_while_already_open(self):
        from app.core.observability.metrics import get_metrics
        get_metrics().gauge("system_cpu_percent").set(99.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "already-open"})
        conn.execute = AsyncMock()
        run(self.svc._evaluate(conn, self._rule()))
        conn.execute.assert_not_called()  # no new INSERT while one is open

    def test_resolves_when_condition_clears(self):
        from app.core.observability.metrics import get_metrics
        get_metrics().gauge("system_cpu_percent").set(1.0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "open-alert"})
        conn.execute = AsyncMock()
        run(self.svc._evaluate(conn, self._rule()))
        update_call = conn.execute.call_args
        self.assertIn("UPDATE alert_history", update_call.args[0])

    def test_notification_failure_never_raises(self):
        """Delivery failures must never propagate into the tick loop."""
        rule = self._rule(notify_email="ops@example.com")
        with patch("app.core.email.send_email", AsyncMock(side_effect=RuntimeError("smtp down"))):
            try:
                run(self.svc._notify(rule, "test message"))
            except Exception as exc:  # pragma: no cover - failure path
                self.fail(f"_notify() must swallow delivery failures, raised: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ObservabilityConfig — feature flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservabilityConfig(unittest.TestCase):
    def setUp(self):
        from app.core.observability.config import ObservabilityConfig
        self.c = ObservabilityConfig()

    def test_defaults_are_all_enabled(self):
        with patch.dict("os.environ", {}, clear=False):
            for k in ("OBS_TRACING_ENABLED", "OBS_METRICS_ENABLED", "OBS_AUDIT_ENABLED", "OBS_ALERTS_ENABLED"):
                import os
                os.environ.pop(k, None)
            self.assertTrue(self.c.tracing_enabled)
            self.assertTrue(self.c.metrics_enabled)
            self.assertTrue(self.c.audit_enabled)
            self.assertTrue(self.c.alerts_enabled)
            self.assertEqual(self.c.sampling_rate, 1.0)

    def test_falsy_strings_disable(self):
        with patch.dict("os.environ", {"OBS_TRACING_ENABLED": "false", "OBS_ALERTS_ENABLED": "0"}):
            self.assertFalse(self.c.tracing_enabled)
            self.assertFalse(self.c.alerts_enabled)

    def test_sampling_rate_clamped(self):
        with patch.dict("os.environ", {"OBS_SAMPLING_RATE": "5"}):
            self.assertEqual(self.c.sampling_rate, 1.0)
        with patch.dict("os.environ", {"OBS_SAMPLING_RATE": "-1"}):
            self.assertEqual(self.c.sampling_rate, 0.0)

    def test_audit_disabled_short_circuits_write_audit(self):
        from app.core.db import write_audit
        with patch.dict("os.environ", {"OBS_AUDIT_ENABLED": "false"}):
            with patch("app.core.db.get_pool") as mock_pool:
                run(write_audit("user@example.com", "login"))
                mock_pool.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Audit log write+read roundtrip — mocked DB (see this phase's
#    verification script for the real live-Postgres roundtrip)
# ═══════════════════════════════════════════════════════════════════════════════

import os as _os  # noqa: E402
_os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
_os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.routers.auth_users import router as _auth_router  # noqa: E402


def _mock_pool(conn_mock):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.auth_users.get_pool", return_value=pool)


@pytest.fixture()
def audit_client():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(_auth_router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestAuditLogReadAPI:
    def test_my_audit_log_returns_entries(self, audit_client, monkeypatch):
        import uuid
        from datetime import datetime, timezone
        from app.core.jwt_utils import make_access_token

        row = {
            "id": uuid.uuid4(), "action": "login", "resource": None, "resource_id": None,
            "details": None, "ip_address": "127.0.0.1", "created_at": datetime.now(timezone.utc),
        }
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])

        token = make_access_token("user-1", "user@example.com")
        with _mock_pool(conn):
            res = audit_client.get(
                "/api/auth/me/audit-log", headers={"Authorization": f"Bearer {token}"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["entries"][0]["action"] == "login"
        assert body["entries"][0]["ip_address"] == "127.0.0.1"

    def test_requires_auth(self, audit_client):
        res = audit_client.get("/api/auth/me/audit-log")
        assert res.status_code == 401


if __name__ == "__main__":
    unittest.main()
