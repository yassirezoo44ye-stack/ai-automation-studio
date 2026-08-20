"""
AI Routing, Model Orchestration & Cost Optimization — tests.

DB-backed paths (UsageService/QuotaExceeded against PostgreSQL) are
exercised via mocks here (matching test_enterprise.py's DB-free convention
so the suite stays green in CI without a database) plus a live-Postgres
verification script run manually during this phase's own verification pass
— not duplicated as slow pytest fixtures here.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── ProviderID widened from closed enum to plain string ────────────────────

class TestProviderIdWidened(unittest.TestCase):
    """CompletionRequest.provider/fallback_providers widened from a closed
    ProviderID enum to Optional[str]/list[str] (AI Routing consolidation) —
    every existing caller passing the 3 built-in string values must keep
    working identically, and a dynamically-registered plugin provider_id
    (not one of the 3 built-ins) must now be accepted."""

    def test_builtin_string_values_still_accepted(self):
        from app.ai.models import CompletionRequest, Message
        for value in ("anthropic", "openai", "gemini"):
            req = CompletionRequest(messages=[Message(role="user", content="hi")], provider=value)
            self.assertEqual(req.provider, value)

    def test_provider_id_enum_members_still_usable_as_strings(self):
        from app.ai.models import ProviderID
        self.assertEqual(ProviderID.anthropic, "anthropic")
        self.assertEqual(ProviderID.anthropic.value, "anthropic")
        self.assertTrue(isinstance(ProviderID.anthropic, str))

    def test_non_builtin_provider_id_now_accepted(self):
        from app.ai.models import CompletionRequest, Message
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            provider="my_custom_plugin_provider",
        )
        self.assertEqual(req.provider, "my_custom_plugin_provider")

    def test_fallback_providers_accepts_plain_strings(self):
        from app.ai.models import CompletionRequest, Message
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            fallback_providers=["openai", "my_plugin_provider"],
        )
        self.assertEqual(req.fallback_providers, ["openai", "my_plugin_provider"])


# ── platform_registry registration roundtrip (the real, live path) ─────────

class TestPlatformRegistryRegistration(unittest.TestCase):
    """PlatformProviderRegistry (app/core/ai/registry/registry.py) — the
    registry every real completion path uses. Distinct from the older
    app.ai.providers.registry.ProviderRegistry, whose own registration
    tests already exist in test_plugins.py and are left untouched."""

    def test_register_and_unregister_roundtrip(self):
        from app.core.ai.registry.registry import platform_registry

        class FakeProvider:
            provider_id = "test_roundtrip_provider"
            is_available = True
            def default_model(self): return "fake-model"
            def resolve_model(self, model): return model or "fake-model"

        platform_registry.register(FakeProvider())
        try:
            self.assertIn("test_roundtrip_provider", platform_registry.available())
        finally:
            platform_registry.unregister("test_roundtrip_provider")
        self.assertNotIn("test_roundtrip_provider", platform_registry.available())

    def test_registered_provider_appears_in_health_with_circuit_state(self):
        from app.core.ai.registry.registry import platform_registry

        class FakeProvider:
            provider_id = "test_health_provider"
            is_available = True
            def default_model(self): return "fake-model"
            def resolve_model(self, model): return model or "fake-model"

        platform_registry.register(FakeProvider())
        try:
            health = platform_registry.health()
            self.assertIn("test_health_provider", health)
            self.assertTrue(health["test_health_provider"]["available"])
            self.assertEqual(health["test_health_provider"]["circuit_state"], "closed")
        finally:
            platform_registry.unregister("test_health_provider")


# ── Quota-aware internal (non-HTTP) callers ─────────────────────────────────

class TestQuotaAwareInternalCallers(unittest.TestCase):
    """app/core/org_quota.py's check_org_quota_id — used by the agent
    kernel's internal LLM calls (llm_router.py, reflection.py, evolution.py,
    autonomy.py, plan_agent.py, analyze_agent.py, intent.py,
    deliberation.py) and EmbeddingsService, none of which have an HTTP
    Request to read a header from."""

    def test_no_org_id_always_allowed(self):
        from app.core.org_quota import check_org_quota_id
        self.assertTrue(run(check_org_quota_id(None)))
        self.assertTrue(run(check_org_quota_id("")))

    def test_quota_exceeded_blocks_the_call(self):
        from app.core.org_quota import check_org_quota_id
        from app.billing.usage import QuotaExceeded

        fake_svc = mock.AsyncMock()
        fake_svc.check_quota.side_effect = QuotaExceeded("tokens", 100, 100)
        with mock.patch("app.billing.get_usage_service", return_value=fake_svc):
            allowed = run(check_org_quota_id("org-1"))
        self.assertFalse(allowed)

    def test_quota_ok_allows_the_call(self):
        from app.core.org_quota import check_org_quota_id

        fake_svc = mock.AsyncMock()
        fake_svc.check_quota.return_value = None
        with mock.patch("app.billing.get_usage_service", return_value=fake_svc):
            allowed = run(check_org_quota_id("org-1"))
        self.assertTrue(allowed)

    def test_service_error_degrades_to_allowed_not_raised(self):
        """Internal callers (background reflection, kernel LLM router) have
        no HTTP response to fail — an infra error must degrade to
        'allowed' with a warning logged, never crash the caller."""
        from app.core.org_quota import check_org_quota_id

        fake_svc = mock.AsyncMock()
        fake_svc.check_quota.side_effect = RuntimeError("db unreachable")
        with mock.patch("app.billing.get_usage_service", return_value=fake_svc):
            allowed = run(check_org_quota_id("org-1"))
        self.assertTrue(allowed)


# ── Circuit breaker state transitions ───────────────────────────────────────

class TestCircuitBreaker(unittest.TestCase):
    def test_starts_closed(self):
        from app.ai.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        self.assertEqual(cb.state("p1"), CircuitState.CLOSED)
        self.assertTrue(cb.allow("p1"))

    def test_opens_after_threshold_consecutive_failures(self):
        from app.ai.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=3, cooldown_s=30)
        cb.record_failure("p1")
        cb.record_failure("p1")
        self.assertEqual(cb.state("p1"), CircuitState.CLOSED)
        cb.record_failure("p1")
        self.assertEqual(cb.state("p1"), CircuitState.OPEN)
        self.assertFalse(cb.allow("p1"))

    def test_success_resets_the_failure_count(self):
        from app.ai.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=3, cooldown_s=30)
        cb.record_failure("p1")
        cb.record_failure("p1")
        cb.record_success("p1")
        cb.record_failure("p1")
        cb.record_failure("p1")
        self.assertEqual(cb.state("p1"), CircuitState.CLOSED, "success should reset the streak")

    def test_half_open_after_cooldown_then_closes_on_success(self):
        from app.ai.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.05)
        cb.record_failure("p1")
        self.assertEqual(cb.state("p1"), CircuitState.OPEN)
        self.assertFalse(cb.allow("p1"))
        time.sleep(0.08)
        self.assertTrue(cb.allow("p1"), "cooldown elapsed — the probe call must be allowed")
        self.assertEqual(cb.state("p1"), CircuitState.HALF_OPEN)
        cb.record_success("p1")
        self.assertEqual(cb.state("p1"), CircuitState.CLOSED)

    def test_failed_probe_reopens_the_circuit(self):
        from app.ai.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.05)
        cb.record_failure("p1")
        time.sleep(0.08)
        self.assertTrue(cb.allow("p1"))
        cb.record_failure("p1")
        self.assertEqual(cb.state("p1"), CircuitState.OPEN)

    def test_circuits_are_independent_per_provider(self):
        from app.ai.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("p1")
        self.assertEqual(cb.state("p1"), CircuitState.OPEN)
        self.assertEqual(cb.state("p2"), CircuitState.CLOSED)


class TestFailoverChainSkipsOpenCircuit(unittest.TestCase):
    """Unit-level regression guard for the exact failover-chain behavior
    (app/core/ai/registry/registry.py's complete_with_events) — an
    open-circuit provider must be skipped entirely, never attempted."""

    def test_open_circuit_provider_never_attempted(self):
        from app.core.ai.registry.registry import platform_registry
        from app.ai.circuit_breaker import circuit_breaker
        from app.ai.models import CompletionRequest, Message, CompletionResponse, UsageStats

        class DeadProvider:
            provider_id = "test_dead_provider"
            is_available = True
            def __init__(self): self.calls = 0
            def default_model(self): return "dead-model"
            def resolve_model(self, model): return model or "dead-model"
            async def complete(self, request):
                self.calls += 1
                raise RuntimeError("must never be called while circuit is open")

        class OkProvider:
            provider_id = "test_ok_provider"
            is_available = True
            def default_model(self): return "ok-model"
            def resolve_model(self, model): return model or "ok-model"
            async def complete(self, request):
                return CompletionResponse(
                    content="ok",
                    usage=UsageStats(input_tokens=1, output_tokens=1, total_tokens=2,
                                     cost_usd=0.0, provider="test_ok_provider", model="ok-model"),
                )

        dead = DeadProvider()
        platform_registry.register(dead)
        platform_registry.register(OkProvider())
        try:
            for _ in range(5):
                circuit_breaker.record_failure("test_dead_provider")

            req = CompletionRequest(
                messages=[Message(role="user", content="hi")],
                provider="test_dead_provider", fallback_providers=["test_ok_provider"],
                max_tokens=10,
            )
            resp, used = run(platform_registry.complete_with_events(req))
            self.assertEqual(used, "test_ok_provider")
            self.assertEqual(dead.calls, 0)
        finally:
            platform_registry.unregister("test_dead_provider")
            platform_registry.unregister("test_ok_provider")


# ── ProviderID enum lookup regression (Python 3.11 str() bug) ─────────────
#
# Root cause (confirmed in production Python 3.11):
#   str(ProviderID.anthropic) == "ProviderID.anthropic"   ← wrong key
#   ProviderID.anthropic.value == "anthropic"              ← correct key
#
# The old default() used str(pid), so every ProviderID-typed entry in the
# iteration order was looked up with the wrong key and returned None — even
# when ANTHROPIC_API_KEY was set and AnthropicProvider.is_available = True.
# Fix: use pid.value instead of str(pid).

class TestProviderIdEnumLookupPy311Regression(unittest.TestCase):
    """Regression: default() must use pid.value, not str(pid), so it finds
    built-in providers on Python 3.11 where str(StrEnum-like members) returns
    the qualified class.member string rather than the plain value."""

    def test_str_of_provider_id_enum_is_not_plain_value(self):
        """Documents the Python 3.11 str() behaviour that caused the bug.
        str(ProviderID.anthropic) is NOT "anthropic" on Python 3.11 — it is
        "ProviderID.anthropic".  Code must never use str() for dict lookup."""
        from app.ai.models import ProviderID
        # .value is always the plain string regardless of Python version
        self.assertEqual(ProviderID.anthropic.value, "anthropic")
        self.assertEqual(ProviderID.openai.value,    "openai")
        self.assertEqual(ProviderID.gemini.value,    "gemini")
        # str() produces the qualified name on Python 3.11+ — wrong for lookup
        # (on Python 3.12+ this may change again, but .value is always stable)
        import sys
        if sys.version_info >= (3, 11):
            self.assertNotEqual(str(ProviderID.anthropic), "anthropic",
                msg="This confirms the Python 3.11 bug exists in this runtime; "
                    "the fix must use pid.value not str(pid)")

    def test_provider_dict_lookup_with_value_finds_provider(self):
        """Simulates the fixed default() lookup: _providers keyed by plain
        string, ProviderID.value also plain string → lookup succeeds."""
        from app.ai.models import ProviderID
        providers = {"anthropic": "AnthropicProvider", "openai": "OpenAIProvider"}
        # .value lookup — always correct
        self.assertEqual(providers.get(ProviderID.anthropic.value), "AnthropicProvider")
        self.assertEqual(providers.get(ProviderID.openai.value),    "OpenAIProvider")

    def test_provider_dict_lookup_with_str_fails_on_py311(self):
        """The broken lookup: str(ProviderID.anthropic) returns the wrong key
        on Python 3.11, so get() returns None even when the key is present."""
        from app.ai.models import ProviderID
        import sys
        providers = {"anthropic": "AnthropicProvider"}
        if sys.version_info >= (3, 11):
            self.assertIsNone(providers.get(str(ProviderID.anthropic)),
                msg="Confirms str(enum) produces wrong lookup key on Python 3.11")

    def test_default_returns_anthropic_when_api_key_set(self):
        """default() must return AnthropicProvider when ANTHROPIC_API_KEY is
        set, regardless of whether other provider keys are absent."""
        from unittest.mock import patch
        from app.core.ai.registry.registry import PlatformProviderRegistry
        # Use a dummy value — we only need is_available to be True
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test-key"}, clear=False):
            reg = PlatformProviderRegistry()
            provider = reg.default()
            self.assertEqual(provider.provider_id, "anthropic")

    def test_default_raises_when_no_key_set(self):
        """default() must raise RuntimeError when no provider keys are set."""
        from unittest.mock import patch
        from app.core.ai.registry.registry import PlatformProviderRegistry
        no_keys = {k: "" for k in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
            "OPENROUTER_API_KEY", "GROQ_API_KEY", "LOCAL_MODEL_BASE_URL",
        )}
        with patch.dict("os.environ", no_keys, clear=False):
            reg = PlatformProviderRegistry()
            with self.assertRaises(RuntimeError):
                reg.default()

    def test_available_includes_anthropic_when_api_key_set(self):
        """registry.available() must include 'anthropic' when key is set."""
        from unittest.mock import patch
        from app.core.ai.registry.registry import PlatformProviderRegistry
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test-key"}, clear=False):
            reg = PlatformProviderRegistry()
            self.assertIn("anthropic", reg.available())

    def test_resolve_chain_not_empty_when_anthropic_key_set(self):
        """resolve_chain() must return a non-empty list when ANTHROPIC_API_KEY
        is set and no explicit provider is specified (mirrors build.py path)."""
        from unittest.mock import patch
        from app.core.ai.registry.registry import PlatformProviderRegistry
        from app.ai.models import CompletionRequest, Message
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test-key"}, clear=False):
            reg = PlatformProviderRegistry()
            # Matches build.py: no provider specified, default chain
            req   = CompletionRequest(messages=[Message(role="user", content="hi")])
            chain = reg.resolve_chain(req)
            self.assertGreater(len(chain), 0,
                "resolve_chain() returned [] even though ANTHROPIC_API_KEY is set — "
                "this is the Python 3.11 str(enum) regression")
            self.assertEqual(chain[0].provider_id, "anthropic")

    def test_closed_circuit_does_not_block_provider(self):
        """A CLOSED circuit must allow the provider through both resolve_chain
        and stream_with_events.  circuit_breaker.allow() returns True for
        providers that have never failed (their circuit starts CLOSED)."""
        from app.ai.circuit_breaker import circuit_breaker
        from app.core.reliability import CircuitState
        # Fresh circuit state for "anthropic" is CLOSED
        state = circuit_breaker._get("anthropic").state
        self.assertEqual(state, CircuitState.CLOSED)
        self.assertTrue(circuit_breaker.allow("anthropic"))


# ── Reconciled model/pricing catalog ────────────────────────────────────────

class TestReconciledCatalog(unittest.TestCase):
    def test_no_duplicate_model_ids(self):
        from app.core.ai.models.catalog import catalog
        ids = [m.id for m in catalog.all()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_cost_router_has_no_duplicate_price_table(self):
        """Source-inspection guard: app/ai/cost_router.py must not define
        its own model/price table anymore — it must read from the single
        reconciled catalog instead. Checks for the actual assignment
        pattern (not a bare substring match, since the module's own
        docstring mentions the old name for historical context)."""
        source = inspect.getsource(__import__("app.ai.cost_router", fromlist=["_x"]))
        self.assertNotIn("_DEFAULT_MODELS: list[ModelSpec]", source)
        self.assertNotIn("_DEFAULT_MODELS =", source)
        self.assertIn("app.core.ai.models.catalog", source)

    def test_deferred_providers_are_catalogued_and_deprecated(self):
        from app.core.ai.models.catalog import catalog
        for model_id in ("deepseek-chat", "mistral-large", "mistral-small",
                         "ollama/llama3.1", "azure/gpt-4o", "bedrock/claude-sonnet"):
            info = catalog.get(model_id)
            self.assertIsNotNone(info, f"{model_id} should stay documented, not deleted")
            self.assertTrue(info.deprecated, f"{model_id} must be excluded from auto-selection")

    def test_cost_router_and_catalog_agree_on_price(self):
        """Regression guard for the exact disagreement the phase found:
        gpt-4o priced $2.50/$10 in the old cost_router.py vs $5/$15 in
        catalog.py. Both call sites must now report the same number."""
        from app.core.ai.models.catalog import catalog
        from app.ai.cost_router import get_cost_router
        catalog_price = catalog.get("gpt-4o").input_cost_m
        router_models = {m["id"]: m for m in get_cost_router().list_models()}
        self.assertEqual(router_models["gpt-4o"]["input_per_m"], catalog_price)


# ── Budget granularity — backward compatibility ─────────────────────────────

class TestBudgetGranularityBackwardCompat(unittest.TestCase):
    """A check/record with no project_id/workflow_id/agent_id must behave
    identically to before this phase — the literal backward-compatibility
    guarantee. Verified structurally (defaults) here; the full behavioral
    guarantee (a workflow budget exhausting while org budget has headroom)
    is exercised by this phase's live-Postgres verification script."""

    def test_scope_kwargs_default_to_empty_string(self):
        from app.billing.usage import UsageService
        for method_name in ("record", "check_quota", "get_limit", "get_usage", "set_override"):
            sig = inspect.signature(getattr(UsageService, method_name))
            for scope_param in ("project_id", "workflow_id", "agent_id"):
                self.assertIn(scope_param, sig.parameters, f"{method_name} missing {scope_param}")
                self.assertEqual(
                    sig.parameters[scope_param].default, "",
                    f"{method_name}.{scope_param} default must be '' (org-level) for backward compat",
                )


if __name__ == "__main__":
    unittest.main()
