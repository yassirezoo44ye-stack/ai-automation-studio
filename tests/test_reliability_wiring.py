"""
Runtime Health Manager wiring — current_health() accessor + circuit-breaker
application to the real (non-PlatformProviderRegistry) AI traffic path.

Matches tests/test_plugins.py's source-inspection style for the router
wiring checks (cheap regression guard against a future edit silently
dropping ai_circuit_precheck()/ai_circuit_report() from a call site) and
plain unittest.mock for the accessor/helper unit tests — no live DB/Redis
needed for anything in this file.
"""
from __future__ import annotations

import inspect
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from app.core.observability import health as health_mod


# ── current_health() accessor ───────────────────────────────────────────────

class TestCurrentHealthAccessor(unittest.TestCase):
    def setUp(self):
        # Isolate from whatever a real HealthMonitorService tick may have
        # set earlier in the test run.
        self._orig = health_mod._current_status
        health_mod._current_status = health_mod.HealthStatus.UNKNOWN

    def tearDown(self):
        health_mod._current_status = self._orig

    def test_defaults_to_unknown(self):
        self.assertEqual(health_mod.current_health(), health_mod.HealthStatus.UNKNOWN)

    def test_flips_after_set(self):
        health_mod._set_current_health(health_mod.HealthStatus.DEGRADED)
        self.assertEqual(health_mod.current_health(), health_mod.HealthStatus.DEGRADED)
        health_mod._set_current_health(health_mod.HealthStatus.HEALTHY)
        self.assertEqual(health_mod.current_health(), health_mod.HealthStatus.HEALTHY)


class TestHealthMonitorTickSetsCurrentHealth(unittest.IsolatedAsyncioTestCase):
    async def test_tick_calls_set_current_health(self):
        from app.services.health_monitor import HealthMonitorService

        fake_report = {"status": "degraded", "probes": []}
        with unittest.mock.patch(
            "app.core.observability.health.get_health_registry"
        ) as mock_reg, unittest.mock.patch(
            "app.core.observability.health._set_current_health"
        ) as mock_set, unittest.mock.patch(
            "app.core.observability.metrics.get_metrics"
        ) as mock_metrics:
            mock_reg.return_value.check_all = unittest.mock.AsyncMock(return_value=fake_report)
            mock_metrics.return_value.gauge.return_value.set = unittest.mock.MagicMock()

            svc = HealthMonitorService()
            await svc.tick()

            mock_set.assert_called_once_with(health_mod.HealthStatus.DEGRADED)


# ── ai_circuit_precheck() / ai_circuit_report() ─────────────────────────────

class TestAiCircuitHelpers(unittest.TestCase):
    def test_precheck_raises_503_when_circuit_open(self):
        from app.core import helpers

        with unittest.mock.patch("app.ai.circuit_breaker.circuit_breaker") as mock_cb:
            mock_cb.allow.return_value = False
            with self.assertRaises(HTTPException) as ctx:
                helpers.ai_circuit_precheck("anthropic")
            self.assertEqual(ctx.exception.status_code, 503)
            mock_cb.allow.assert_called_once_with("anthropic")

    def test_precheck_noop_when_circuit_closed(self):
        from app.core import helpers

        with unittest.mock.patch("app.ai.circuit_breaker.circuit_breaker") as mock_cb:
            mock_cb.allow.return_value = True
            helpers.ai_circuit_precheck("anthropic")  # must not raise

    def test_report_success_calls_record_success(self):
        from app.core import helpers

        with unittest.mock.patch("app.ai.circuit_breaker.circuit_breaker") as mock_cb:
            helpers.ai_circuit_report(True, "anthropic")
            mock_cb.record_success.assert_called_once_with("anthropic")
            mock_cb.record_failure.assert_not_called()

    def test_report_failure_calls_record_failure(self):
        from app.core import helpers

        with unittest.mock.patch("app.ai.circuit_breaker.circuit_breaker") as mock_cb:
            helpers.ai_circuit_report(False, "anthropic")
            mock_cb.record_failure.assert_called_once_with("anthropic")
            mock_cb.record_success.assert_not_called()

    def test_shares_target_id_with_platform_registry_path(self):
        """The whole point of this wiring is that GET /api/ai/providers
        (which reads app.ai.circuit_breaker.circuit_breaker.snapshot(),
        keyed by app.core.ai.registry.registry.py's provider ids) reflects
        real traffic too — so the default target_id here must match the
        'anthropic' key the registry path already uses."""
        from app.core import helpers
        import inspect as _inspect

        sig = _inspect.signature(helpers.ai_circuit_precheck)
        self.assertEqual(sig.parameters["target_id"].default, "anthropic")
        sig = _inspect.signature(helpers.ai_circuit_report)
        self.assertEqual(sig.parameters["target_id"].default, "anthropic")


# ── Source-inspection: every router call site actually wires it in ─────────

class TestCircuitBreakerWiredIntoRealTraffic(unittest.TestCase):
    """Regression guard: app/core/helpers.py's circuit-breaker helpers exist,
    but they only matter if every LLM call site in the live-traffic routers
    actually calls them. A future edit that adds/refactors a call site
    without wiring this in would silently reopen the original gap (real
    traffic is guarded only by the low-traffic PlatformProviderRegistry
    path). This asserts presence in source, not runtime behavior — cheap
    and matches tests/test_plugins.py's own source-inspection convention."""

    def _source(self, module_name: str) -> str:
        import importlib
        mod = importlib.import_module(module_name)
        return inspect.getsource(mod)

    def test_agents_router_wired(self):
        src = self._source("app.routers.agents")
        self.assertIn("ai_circuit_precheck", src)
        self.assertIn("ai_circuit_report", src)

    def test_design_router_wired(self):
        src = self._source("app.routers.design")
        self.assertIn("ai_circuit_precheck", src)
        self.assertIn("ai_circuit_report", src)

    def test_social_router_wired(self):
        src = self._source("app.routers.social")
        self.assertIn("ai_circuit_precheck", src)
        self.assertIn("ai_circuit_report", src)

    def test_youtube_router_wired(self):
        src = self._source("app.routers.youtube")
        self.assertIn("ai_circuit_precheck", src)
        self.assertIn("ai_circuit_report", src)

    def test_tasks_router_wired(self):
        src = self._source("app.routers.tasks")
        self.assertIn("ai_circuit_precheck", src)
        self.assertIn("ai_circuit_report", src)


class TestChatBuildRoutersRouteThroughInferenceEngine(unittest.TestCase):
    """chat.py/build.py were migrated off manual ai_circuit_precheck()/
    ai_circuit_report() onto InferenceEngine (app/core/ai/inference/
    engine.py), which already applies the same circuit_breaker singleton
    (same target_id="anthropic") internally via platform_registry — see
    tests/test_reliability_wiring.py's git history for the commit that
    made this change. Keeping the manual helpers around after this
    migration would double-count every success/failure against the same
    breaker bucket, so their ABSENCE here is the regression guard (the
    inverse of TestCircuitBreakerWiredIntoRealTraffic above, which still
    asserts PRESENCE for the routers that haven't been migrated yet)."""

    def _source(self, module_name: str) -> str:
        import importlib
        mod = importlib.import_module(module_name)
        return inspect.getsource(mod)

    def test_chat_router_no_longer_self_wires_circuit_breaker(self):
        src = self._source("app.routers.chat")
        self.assertNotIn("ai_circuit_precheck", src)
        self.assertNotIn("ai_circuit_report", src)
        self.assertIn("InferenceEngine", src)
        self.assertIn("auto_tools=False", src)

    def test_build_router_no_longer_self_wires_circuit_breaker(self):
        src = self._source("app.routers.build")
        self.assertNotIn("ai_circuit_precheck", src)
        self.assertNotIn("ai_circuit_report", src)
        self.assertIn("InferenceEngine", src)
        self.assertIn("auto_tools=False", src)


class TestBulkheadWiredIntoRemainingRouters(unittest.TestCase):
    """The 5 routers that previously had no bulkhead at all
    (agents/design/social/youtube/tasks) must now acquire one around
    their AI call — same regression-guard rationale as above."""

    def _source(self, module_name: str) -> str:
        import importlib
        mod = importlib.import_module(module_name)
        return inspect.getsource(mod)

    def test_agents_router_has_bulkhead(self):
        self.assertIn("get_bulkhead", self._source("app.routers.agents"))

    def test_design_router_has_bulkhead(self):
        self.assertIn("get_bulkhead", self._source("app.routers.design"))

    def test_social_router_has_bulkhead(self):
        self.assertIn("get_bulkhead", self._source("app.routers.social"))

    def test_youtube_router_has_bulkhead(self):
        self.assertIn("get_bulkhead", self._source("app.routers.youtube"))

    def test_tasks_router_has_bulkhead(self):
        self.assertIn("get_bulkhead", self._source("app.routers.tasks"))


# ── Circuit-open, end-to-end through an actual router endpoint ─────────────
#
# chat.py/build.py no longer have their own ai_circuit_precheck() short
# circuit — the "every provider's circuit is open" condition is now
# detected deep inside InferenceEngine -> AIGateway -> PlatformProviderRegistry
# (app/core/ai/registry/registry.py's complete_with_events(), which raises a
# bare RuntimeError in that case). run_agent/build_program's new
# `except RuntimeError as e: raise HTTPException(503, str(e))` clause is
# what re-establishes the "circuit open -> clean 503" contract these tests
# originally proved for the removed manual precheck. Mocking
# InferenceEngine.complete() directly (rather than reconstructing the full
# registry/circuit-breaker/retry chain) keeps this a router-level test, not
# a re-test of the registry's own internals, and avoids exercising
# with_retry()'s real backoff sleep. The raw SDK client constructor is
# additionally patched as a belt-and-suspenders proof nothing deeper ever
# touches the network.

class TestCircuitOpenEndToEndOnRouter(unittest.IsolatedAsyncioTestCase):
    async def test_chat_run_agent_503s_without_calling_the_sdk(self):
        from app.routers import chat as chat_mod

        fake_conn = MagicMock()
        fake_conn.__aenter__ = AsyncMock(return_value=MagicMock())
        fake_conn.__aexit__ = AsyncMock(return_value=False)
        fake_pool = MagicMock()
        fake_pool.acquire.return_value = fake_conn

        with unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=fake_pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value="u1"),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=RuntimeError(
                "No available AI providers — every provider's circuit is open.",
            )),
        ) as mock_complete, unittest.mock.patch(
            "app.ai.providers.anthropic.sdk.AsyncAnthropic",
        ) as mock_sdk:
            req = chat_mod.RunRequest(project_id="demo", prompt="hello")
            with self.assertRaises(HTTPException) as ctx:
                await chat_mod.run_agent(req, MagicMock())

        self.assertEqual(ctx.exception.status_code, 503)
        mock_complete.assert_awaited_once()
        mock_sdk.assert_not_called()

    async def test_build_program_503s_without_calling_the_sdk(self):
        from app.routers import build as build_mod

        fake_conn = MagicMock()
        fake_conn.__aenter__ = AsyncMock(return_value=MagicMock())
        fake_conn.__aexit__ = AsyncMock(return_value=False)
        fake_pool = MagicMock()
        fake_pool.acquire.return_value = fake_conn

        with unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=fake_pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value="u1"),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value="p1"),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=RuntimeError(
                "No available AI providers — every provider's circuit is open.",
            )),
        ) as mock_complete, unittest.mock.patch(
            "app.ai.providers.anthropic.sdk.AsyncAnthropic",
        ) as mock_sdk:
            req = build_mod.BuildRequest(project_id="demo", prompt="build me a thing")
            with self.assertRaises(HTTPException) as ctx:
                await build_mod.build_program(req, MagicMock())

        self.assertEqual(ctx.exception.status_code, 503)
        mock_complete.assert_awaited_once()
        mock_sdk.assert_not_called()


# ── Execution order: bulkhead is checked before the AI call is even made ───
#
# chat.py's run_agent acquires the bulkhead FIRST, then calls
# InferenceEngine.complete() (which is where a circuit-breaker consultation
# would happen, deep inside the registry) — never the reverse. A saturated
# bulkhead must short-circuit before the engine — and thus the circuit
# breaker — is even reached, so a capacity-shed response is never confused
# with a provider-health response, and a provider outage never gets to
# consume bulkhead capacity for requests that were going to be rejected
# anyway. Proven here against the real router function and the real
# Bulkhead singleton (not a mock) — if the bulkhead check didn't run first,
# InferenceEngine.complete() would have been invoked.

class TestBulkheadCheckedBeforeCircuitPrecheck(unittest.IsolatedAsyncioTestCase):
    async def test_saturated_bulkhead_wins_before_the_engine_is_ever_called(self):
        from app.routers import chat as chat_mod
        from app.core.reliability import BulkheadFull, get_bulkhead

        bulkhead = get_bulkhead("ai", 32)
        original_in_flight = bulkhead._in_flight
        bulkhead._in_flight = bulkhead.limit  # saturate it

        fake_conn = MagicMock()
        fake_conn.__aenter__ = AsyncMock(return_value=MagicMock())
        fake_conn.__aexit__ = AsyncMock(return_value=False)
        fake_pool = MagicMock()
        fake_pool.acquire.return_value = fake_conn

        try:
            with unittest.mock.patch.object(
                chat_mod, "check_org_quota", AsyncMock(return_value=None),
            ), unittest.mock.patch.object(
                chat_mod, "get_pool", return_value=fake_pool,
            ), unittest.mock.patch.object(
                chat_mod, "owner_user_id", AsyncMock(return_value="u1"),
            ), unittest.mock.patch(
                "app.core.ai.inference.engine.InferenceEngine.complete",
                AsyncMock(),
            ) as mock_complete, unittest.mock.patch(
                "app.ai.providers.anthropic.sdk.AsyncAnthropic",
            ) as mock_sdk:
                req = chat_mod.RunRequest(project_id="demo", prompt="hello")
                with self.assertRaises(BulkheadFull):
                    await chat_mod.run_agent(req, MagicMock())

            # The engine (and thus any circuit-breaker consultation inside
            # it) must never even have been reached — proof the bulkhead
            # rejected first, not just that both would have rejected
            # independently.
            mock_complete.assert_not_called()
            mock_sdk.assert_not_called()
        finally:
            bulkhead._in_flight = original_in_flight  # don't leak into other tests


if __name__ == "__main__":
    unittest.main()
