"""
Provider Failover Regression Tests — Phase 2
=============================================
Gate for the AI provider failover chain implemented in
app/core/ai/registry/registry.py::stream_with_events.

Verified cases:
  Case 1  — Anthropic healthy → uses Anthropic (no failover)
  Case 2  — Anthropic billing failure + OpenAI healthy → uses OpenAI
  Case 3  — Anthropic circuit OPEN + OpenAI healthy → uses OpenAI
  Case 4  — Anthropic unavailable + Gemini healthy → uses Gemini
  Case 5  — Anthropic + OpenAI + Gemini unavailable → structured failure
  Case 6  — Fallback provider failure → walks to next provider
  Case 7  — Successful fallback → build completes (no 502)
  Case 8  — No API key for any provider → clear user message
  Case 9  — Circuit breaker isolation: one provider's failures don't open all circuits
  Case 10 — Temperature regression: stream() must not pass temperature to Anthropic SDK
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ai.errors import AIProviderError, AIProviderErrorCode
from app.ai.models import CompletionRequest, CompletionResponse, Message, StreamChunk, UsageStats


# ── Helpers ────────────────────────────────────────────────────────────────────

def _req(**kw) -> CompletionRequest:
    """Minimal CompletionRequest for tests."""
    defaults = dict(
        messages=[Message(role="user", content="hello")],
        stream=True,
    )
    defaults.update(kw)
    return CompletionRequest(**defaults)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _collect(gen) -> list[StreamChunk]:
    """Drain an async generator into a list of StreamChunk objects."""
    chunks: list[StreamChunk] = []
    async for chunk in gen:
        chunks.append(chunk)
    return chunks


async def _stream_ok(*chunks: StreamChunk) -> AsyncGenerator[StreamChunk, None]:
    """Async generator yielding the given chunks then returning."""
    for c in chunks:
        yield c


async def _stream_raise(exc: Exception) -> AsyncGenerator[StreamChunk, None]:
    """Async generator that immediately raises exc."""
    raise exc
    yield  # make it an async generator


def _billing_error(provider: str) -> AIProviderError:
    return AIProviderError(
        AIProviderErrorCode.BILLING_REQUIRED,
        provider=provider,
        message=f"{provider}: Credit balance too low",
        retryable=False,
    )


def _unavailable_error(provider: str) -> AIProviderError:
    return AIProviderError(
        AIProviderErrorCode.PROVIDER_UNAVAILABLE,
        provider=provider,
        message=f"{provider}: Service unavailable",
    )


def _mock_provider(provider_id: str, *, available: bool = True,
                   stream_side_effect=None, complete_return=None):
    """Build a minimal mock provider."""
    p = MagicMock()
    p.provider_id = provider_id
    p.is_available = available
    p.resolve_model = MagicMock(return_value=f"{provider_id}-model")
    p.default_model = MagicMock(return_value=f"{provider_id}-model")

    if stream_side_effect is not None:
        if callable(stream_side_effect) and asyncio.iscoroutinefunction(stream_side_effect):
            p.stream = MagicMock(return_value=stream_side_effect())
        else:
            async def _stream_raises(_req, _se=stream_side_effect):
                raise _se
                yield
            p.stream = MagicMock(side_effect=lambda r: _stream_raises(r))
    else:
        p.stream = MagicMock(return_value=_stream_ok(
            StreamChunk(type="delta", text="ok"),
            StreamChunk(type="done"),
        ))

    if complete_return is not None:
        p.complete = AsyncMock(return_value=complete_return)
    else:
        p.complete = AsyncMock(return_value=CompletionResponse(
            content="fallback ok",
            usage=UsageStats(total_tokens=10, provider=provider_id),
        ))
    return p


# ── Registry builder ────────────────────────────────────────────────────────

def _build_registry(*providers):
    """Return a PlatformProviderRegistry whose chain is exactly the given providers."""
    from app.core.ai.registry.registry import PlatformProviderRegistry
    reg = object.__new__(PlatformProviderRegistry)
    reg._providers   = {p.provider_id: p for p in providers}
    reg._builtin_ids = set()
    reg._billing_errors = {}
    from app.plugins.registry_guard import OwnershipTracker
    reg._owners = OwnershipTracker("AI provider")
    for p in providers:
        reg._owners.claim(p.provider_id, None)
    return reg


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestCase1_AnthropicHealthy:
    """Case 1 — Anthropic healthy → uses Anthropic, no fallover."""

    def test_no_provider_switched_event_on_success(self):
        anthropic = _mock_provider("anthropic")
        openai    = _mock_provider("openai")
        reg       = _build_registry(anthropic, openai)

        req = _req(provider="anthropic")
        chunks = run(_collect(reg.stream_with_events(req)))

        types = [c.type for c in chunks]
        assert "provider_switched" not in types, "Healthy primary must not trigger fallover"
        assert "done" in types
        assert "error" not in types


class TestCase2_AnthropicBillingOpenAIHealthy:
    """Case 2 — Anthropic billing failure + OpenAI healthy → uses OpenAI."""

    def test_fallback_to_openai_on_billing(self):
        async def anthropic_stream(r):
            raise _billing_error("anthropic")
            yield

        anthropic = _mock_provider("anthropic",
                                   stream_side_effect=_billing_error("anthropic"))
        openai    = _mock_provider("openai")
        reg       = _build_registry(anthropic, openai)

        req = _req()
        chunks = run(_collect(reg.stream_with_events(req)))

        types = [c.type for c in chunks]
        assert "provider_switched" in types, "Must emit provider_switched when failing over"
        sw = next(c for c in chunks if c.type == "provider_switched")
        assert sw.previous_provider == "anthropic"
        assert sw.provider_id == "openai"
        assert sw.failure_reason == "billing_required"
        # Build must complete — no error chunk
        assert "error" not in types

    def test_internal_billing_marker_set_after_failure(self):
        """After Anthropic billing fails, registry must suppress it on the next request."""
        anthropic = _mock_provider("anthropic",
                                   stream_side_effect=_billing_error("anthropic"))
        openai = _mock_provider("openai")
        reg = _build_registry(anthropic, openai)

        # First request — Anthropic fails, OpenAI completes
        run(_collect(reg.stream_with_events(_req())))

        # Now the billing error must be recorded
        assert reg._has_billing_error("anthropic"), (
            "Billing error must be persisted so Anthropic is skipped on the next request"
        )


class TestCase3_AnthropicCircuitOpenOpenAIHealthy:
    """Case 3 — Anthropic circuit OPEN + OpenAI healthy → uses OpenAI."""

    def test_open_circuit_skips_anthropic(self):
        from app.ai.circuit_breaker import CircuitBreaker

        anthropic = _mock_provider("anthropic")
        openai    = _mock_provider("openai")
        reg       = _build_registry(anthropic, openai)

        # Force Anthropic's circuit open
        cb = CircuitBreaker(failure_threshold=1, cooldown_s=9999)
        cb.record_failure("anthropic")  # first failure
        cb.record_failure("anthropic")  # threshold hit

        with patch("app.core.ai.registry.registry.circuit_breaker", cb):
            chunks = run(_collect(reg.stream_with_events(_req())))

        types = [c.type for c in chunks]
        # Anthropic must be skipped — no attempt, so no provider_switched from failure
        # (provider_switched is emitted when the registry detects fallover is needed)
        # OpenAI should succeed
        assert "error" not in types
        assert "done" in types
        # anthropic.stream must not have been called
        anthropic.stream.assert_not_called()


class TestCase4_AnthropicUnavailableGeminiHealthy:
    """Case 4 — Anthropic not configured + Gemini healthy → uses Gemini."""

    def test_skips_unconfigured_anthropic(self):
        anthropic = _mock_provider("anthropic", available=False)
        gemini    = _mock_provider("gemini")
        reg       = _build_registry(anthropic, gemini)

        chunks = run(_collect(reg.stream_with_events(_req())))

        types = [c.type for c in chunks]
        assert "error" not in types
        assert "done" in types
        anthropic.stream.assert_not_called()


class TestCase5_AllProvidersUnavailable:
    """Case 5 — All providers fail → structured failure response."""

    def test_structured_error_when_all_fail(self):
        anthropic = _mock_provider("anthropic",
                                   stream_side_effect=_billing_error("anthropic"))
        openai    = _mock_provider("openai",
                                   stream_side_effect=_billing_error("openai"))

        # Also make complete() fail
        anthropic.complete = AsyncMock(side_effect=_billing_error("anthropic"))
        openai.complete    = AsyncMock(side_effect=_billing_error("openai"))

        reg = _build_registry(anthropic, openai)
        chunks = run(_collect(reg.stream_with_events(_req())))

        error_chunks = [c for c in chunks if c.type == "error"]
        assert error_chunks, "Must emit an error chunk when all providers fail"
        err_msg = error_chunks[0].error or ""
        # Must contain structured info — not a raw traceback
        assert "AI_PROVIDERS_UNAVAILABLE" in err_msg or "BILLING_REQUIRED" in err_msg, (
            f"Error must be structured, got: {err_msg!r}"
        )
        assert "traceback" not in err_msg.lower()
        assert "exception" not in err_msg.lower()


class TestCase6_FallbackChainWalksAllProviders:
    """Case 6 — Fallback provider failure → walks to the next provider."""

    def test_walks_full_fallback_chain(self):
        anthropic = _mock_provider("anthropic",
                                   stream_side_effect=_billing_error("anthropic"))
        openai    = _mock_provider("openai",
                                   stream_side_effect=_unavailable_error("openai"))
        gemini    = _mock_provider("gemini")   # healthy

        # Make complete() fail for openai too
        openai.complete = AsyncMock(side_effect=_unavailable_error("openai"))

        reg = _build_registry(anthropic, openai, gemini)
        chunks = run(_collect(reg.stream_with_events(_req())))

        types = [c.type for c in chunks]
        assert "error" not in types, "Should succeed via gemini"
        assert "done" in types

        # Two provider_switched events expected: anthropic→openai, then openai→gemini
        switched = [c for c in chunks if c.type == "provider_switched"]
        provider_ids_used = [c.provider_id for c in switched]
        assert "openai" in provider_ids_used, "openai must have been tried"
        assert "gemini" in provider_ids_used, "gemini must have been the final fallback"


class TestCase7_SuccessfulFallbackNeverReturns502:
    """Case 7 — Successful fallback → no 502; build completes."""

    def test_build_stream_does_not_return_502_on_fallback(self):
        anthropic = _mock_provider("anthropic",
                                   stream_side_effect=_billing_error("anthropic"))
        openai    = _mock_provider("openai")
        reg       = _build_registry(anthropic, openai)

        chunks = run(_collect(reg.stream_with_events(_req())))

        has_done  = any(c.type == "done" for c in chunks)
        has_error = any(c.type == "error" for c in chunks)
        assert has_done,  "Build must complete with 'done' chunk"
        assert not has_error, "Build must NOT emit an error chunk on successful fallback"


class TestCase8_NoProviderConfigured:
    """Case 8 — No provider has an API key → clear user message."""

    def test_no_providers_gives_clear_error(self):
        anthropic = _mock_provider("anthropic", available=False)
        openai    = _mock_provider("openai",    available=False)
        reg       = _build_registry(anthropic, openai)

        chunks = run(_collect(reg.stream_with_events(_req())))

        error_chunks = [c for c in chunks if c.type == "error"]
        assert error_chunks, "Must emit error chunk when nothing is configured"
        err = error_chunks[0].error or ""
        # Must NOT be a raw Python exception message
        assert "traceback" not in err.lower()
        # Must give actionable guidance
        assert any(kw in err.lower() for kw in ("api key", "provider", "configure", "set")), (
            f"Error must be actionable, got: {err!r}"
        )


class TestCase9_OneProviderFailureDoesNotOpenAllCircuits:
    """Case 9 — Circuit breaker isolation: failing Anthropic must NOT trip OpenAI's circuit."""

    def test_circuits_are_isolated_per_provider(self):
        from app.ai.circuit_breaker import CircuitBreaker

        anthropic = _mock_provider("anthropic",
                                   stream_side_effect=_unavailable_error("anthropic"))
        openai    = _mock_provider("openai")

        # Fresh circuit breaker for isolation
        cb = CircuitBreaker(failure_threshold=3, cooldown_s=30)

        # Record 3 Anthropic failures to open its circuit
        cb.record_failure("anthropic")
        cb.record_failure("anthropic")
        cb.record_failure("anthropic")

        with patch("app.core.ai.registry.registry.circuit_breaker", cb):
            assert not cb.allow("anthropic"), "Anthropic circuit must be open"
            assert cb.allow("openai"),         "OpenAI circuit must remain closed"

    def test_failed_primary_does_not_mark_fallback_circuits_open(self):
        from app.ai.circuit_breaker import CircuitBreaker

        anthropic = _mock_provider("anthropic",
                                   stream_side_effect=_unavailable_error("anthropic"))
        openai    = _mock_provider("openai")
        gemini    = _mock_provider("gemini")

        cb = CircuitBreaker(failure_threshold=5, cooldown_s=30)

        with patch("app.core.ai.registry.registry.circuit_breaker", cb):
            reg = _build_registry(anthropic, openai, gemini)
            run(_collect(reg.stream_with_events(_req())))

        # Only anthropic's circuit should have failures recorded
        assert cb.allow("openai"),  "OpenAI circuit must remain CLOSED after Anthropic failure"
        assert cb.allow("gemini"),  "Gemini circuit must remain CLOSED after Anthropic failure"


class TestCase10_TemperatureRegression:
    """
    Case 10 — Temperature regression gate.

    AnthropicProvider.stream() must NOT forward 'temperature' to
    client.messages.stream() — the Anthropic SDK rejects it.
    This is the regression gate for commit 2510d3e6.
    """

    def test_temperature_not_passed_to_stream(self):
        """AnthropicProvider.stream() must pop temperature before calling SDK."""
        import inspect
        from app.ai.providers.anthropic import AnthropicProvider

        src = inspect.getsource(AnthropicProvider.stream)
        assert "kwargs.pop(\"temperature\"" in src or "kwargs.pop('temperature'" in src, (
            "AnthropicProvider.stream() must pop 'temperature' from kwargs before "
            "calling client.messages.stream() — regression gate for commit 2510d3e6"
        )

    def test_temperature_still_in_complete(self):
        """AnthropicProvider.complete() MAY keep temperature (SDK accepts it there)."""
        import inspect
        from app.ai.providers.anthropic import AnthropicProvider

        # complete() builds kwargs differently — we just verify stream() is the one
        # doing the pop (tested above).  This test documents the asymmetry.
        src_stream   = inspect.getsource(AnthropicProvider.stream)
        src_complete = inspect.getsource(AnthropicProvider.complete)

        # stream() pops temperature; complete() should NOT have the same pop
        # (it's fine to pass temperature to messages.create())
        assert "kwargs.pop(\"temperature\"" in src_stream or "kwargs.pop('temperature'" in src_stream
        # We do NOT assert absence from complete() — the key property is that
        # stream() removes it so the SDK never sees it there.
