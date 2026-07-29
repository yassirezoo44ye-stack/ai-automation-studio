"""
GroqProvider tests (app/core/ai/providers/groq.py) — Manus M5: additional
LLM providers. Mirrors app/core/ai/providers/openrouter.py's structure
(OpenAI-compatible chat completions), and this file mirrors
test_integrations.py's httpx-mocking convention: patch
"httpx.AsyncClient.post" with an AsyncMock returning a MagicMock response.

No live network calls — GROQ_API_KEY is never read from a real environment
here except where explicitly patched.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _request(**overrides):
    from app.ai.models import CompletionRequest, Message
    return CompletionRequest(
        messages=[Message(role="user", content="hi")],
        **overrides,
    )


class TestGroqProviderAvailability:
    def test_provider_id_is_groq(self):
        from app.core.ai.providers.groq import GroqProvider
        assert GroqProvider().provider_id == "groq"

    def test_default_env_key_is_groq_api_key(self):
        # BaseProvider._env_key() defaults to f"{provider_id.upper()}_API_KEY"
        # — GroqProvider relies on that default rather than overriding it.
        from app.core.ai.providers.groq import GroqProvider
        assert GroqProvider()._env_key() == "GROQ_API_KEY"

    def test_unavailable_without_api_key(self):
        from app.core.ai.providers.groq import GroqProvider
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            assert GroqProvider().is_available is False

    def test_available_with_api_key(self):
        from app.core.ai.providers.groq import GroqProvider
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            assert GroqProvider().is_available is True

    def test_default_model(self):
        from app.core.ai.providers.groq import GroqProvider
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_DEFAULT_MODEL", None)
            assert GroqProvider().default_model() == "llama-3.3-70b-versatile"

    def test_default_model_overridable_via_env(self):
        from app.core.ai.providers.groq import GroqProvider
        with patch.dict(os.environ, {"GROQ_DEFAULT_MODEL": "llama-3.1-8b-instant"}):
            assert GroqProvider().default_model() == "llama-3.1-8b-instant"


class TestGroqProviderCost:
    def test_known_model_cost_per_token(self):
        from app.core.ai.providers.groq import GroqProvider
        p = GroqProvider()
        in_cost, out_cost = p.cost_per_token("llama-3.1-8b-instant")
        assert in_cost > 0
        assert out_cost > 0

    def test_unknown_model_costs_nothing(self):
        from app.core.ai.providers.groq import GroqProvider
        assert GroqProvider().cost_per_token("some-future-model") == (0.0, 0.0)

    def test_calculate_cost_matches_catalog_pricing(self):
        """Regression guard mirroring test_ai_routing.py's
        test_cost_router_and_catalog_agree_on_price — the provider's own
        _PRICING table and the catalog's per-million figures must not
        silently drift apart."""
        from app.core.ai.providers.groq import GroqProvider
        from app.core.ai.models.catalog import catalog
        info = catalog.get("llama-3.3-70b-versatile")
        p = GroqProvider()
        in_cost, out_cost = p.cost_per_token("llama-3.3-70b-versatile")
        assert round(in_cost * 1_000_000, 2) == info.input_cost_m
        assert round(out_cost * 1_000_000, 2) == info.output_cost_m


class TestGroqProviderComplete:
    def test_complete_parses_a_basic_response(self):
        from app.core.ai.providers.groq import GroqProvider

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={
            "model": "llama-3.3-70b-versatile",
            "choices": [{
                "message": {"content": "hello there"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
            resp = run(GroqProvider().complete(_request()))

        assert resp.content == "hello there"
        assert resp.finish_reason == "stop"
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert resp.usage.provider == "groq"

    def test_complete_computes_nonzero_cost_for_a_known_model(self):
        from app.core.ai.providers.groq import GroqProvider

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={
            "model": "llama-3.1-8b-instant",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
        })

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
            resp = run(GroqProvider().complete(_request(model="llama-3.1-8b-instant")))

        assert resp.usage.cost_usd > 0

    def test_complete_parses_tool_calls(self):
        from app.core.ai.providers.groq import GroqProvider

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={
            "model": "llama-3.3-70b-versatile",
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {"name": "get_weather", "arguments": '{"city": "Cairo"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8},
        })

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
            resp = run(GroqProvider().complete(_request()))

        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_weather"
        assert resp.tool_calls[0].arguments == {"city": "Cairo"}

    def test_headers_carry_the_configured_api_key(self):
        from app.core.ai.providers.groq import GroqProvider
        with patch.dict(os.environ, {"GROQ_API_KEY": "secret-abc"}):
            headers = GroqProvider()._headers()
        assert headers["Authorization"] == "Bearer secret-abc"


class TestGroqProviderRegistration:
    def test_registered_in_platform_registry(self):
        from app.core.ai.registry.registry import platform_registry
        assert "groq" in platform_registry._providers

    def test_appears_in_health(self):
        from app.core.ai.registry.registry import platform_registry
        health = platform_registry.health()
        assert "groq" in health

    def test_catalog_lists_two_groq_models(self):
        from app.core.ai.models.catalog import catalog
        groq_models = catalog.for_provider("groq")
        ids = {m.id for m in groq_models}
        assert ids == {"llama-3.3-70b-versatile", "llama-3.1-8b-instant"}
        assert all(not m.deprecated for m in groq_models)
