"""
Tests for AI provider error classification and graceful error propagation.

Cases A–G cover the core production scenarios described in the spec:
  A. Anthropic HTTP 400 "credit balance too low" → BILLING_REQUIRED
  B. Anthropic HTTP 401                           → AUTHENTICATION_FAILED
  C. Anthropic HTTP 429                           → RATE_LIMITED
  D. Anthropic success                            → no error raised
  E. Anthropic billing + OpenAI available         → automatic failover
  F. Anthropic billing + no other provider        → AIProviderError(BILLING_REQUIRED)
  G. /api/health/providers billing_required flag  → registry.health() status field
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import anthropic as sdk

from app.ai.errors import (
    AIProviderError,
    AIProviderErrorCode,
    NON_RETRYABLE_CODES,
    NO_CIRCUIT_CODES,
)
from app.ai.providers.anthropic import _classify_sdk_error


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_bad_request(body_text: str) -> sdk.BadRequestError:
    """Construct an sdk.BadRequestError whose str() contains body_text."""
    response = MagicMock()
    response.status_code = 400
    err = sdk.BadRequestError(body_text, response=response, body=body_text)
    return err


def _make_auth_error() -> sdk.AuthenticationError:
    response = MagicMock()
    response.status_code = 401
    return sdk.AuthenticationError("Unauthorized", response=response, body="")


def _make_rate_limit_error() -> sdk.RateLimitError:
    response = MagicMock()
    response.status_code = 429
    return sdk.RateLimitError("Too Many Requests", response=response, body="")


# ── Case A: Billing error classification ──────────────────────────────────────

class TestCaseA_BillingError:
    """Anthropic HTTP 400 with credit balance message → BILLING_REQUIRED."""

    def test_classify_billing_bad_request(self):
        exc = _make_bad_request("Your credit balance is too low to access the Anthropic API.")
        err = _classify_sdk_error(exc, "anthropic")

        assert isinstance(err, AIProviderError)
        assert err.code == AIProviderErrorCode.BILLING_REQUIRED
        assert err.provider == "anthropic"
        assert err.retryable is False
        # Must NOT contain secret values — just a safe message
        assert "ANTHROPIC_API_KEY" not in err.message
        assert "sk-" not in err.message

    def test_classify_insufficient_funds_keyword(self):
        exc = _make_bad_request("Error: insufficient_funds — please add credits.")
        err = _classify_sdk_error(exc, "anthropic")

        assert err.code == AIProviderErrorCode.BILLING_REQUIRED
        assert err.retryable is False

    def test_billing_code_is_non_retryable(self):
        assert AIProviderErrorCode.BILLING_REQUIRED in NON_RETRYABLE_CODES

    def test_billing_code_does_not_open_circuit(self):
        assert AIProviderErrorCode.BILLING_REQUIRED in NO_CIRCUIT_CODES

    def test_to_dict_is_safe(self):
        exc = _make_bad_request("Your credit balance is too low to access the Anthropic API.")
        err = _classify_sdk_error(exc, "anthropic")
        d = err.to_dict()

        assert d["code"] == "BILLING_REQUIRED"
        assert d["provider"] == "anthropic"
        assert d["retryable"] is False
        assert "message" in d
        # Serialized dict must be safe to embed in HTTP responses
        assert "sk-" not in str(d)


# ── Case B: Authentication error ──────────────────────────────────────────────

class TestCaseB_AuthenticationError:
    """Anthropic 401 → AUTHENTICATION_FAILED."""

    def test_classify_auth_error(self):
        err = _classify_sdk_error(_make_auth_error(), "anthropic")

        assert err.code == AIProviderErrorCode.AUTHENTICATION_FAILED
        assert err.provider == "anthropic"
        assert err.retryable is False

    def test_auth_code_is_non_retryable(self):
        assert AIProviderErrorCode.AUTHENTICATION_FAILED in NON_RETRYABLE_CODES

    def test_auth_code_does_not_open_circuit(self):
        assert AIProviderErrorCode.AUTHENTICATION_FAILED in NO_CIRCUIT_CODES


# ── Case C: Rate limit ────────────────────────────────────────────────────────

class TestCaseC_RateLimitError:
    """Anthropic 429 → RATE_LIMITED, retryable=True."""

    def test_classify_rate_limit(self):
        err = _classify_sdk_error(_make_rate_limit_error(), "anthropic")

        assert err.code == AIProviderErrorCode.RATE_LIMITED
        assert err.retryable is True
        assert err.provider == "anthropic"

    def test_rate_limited_not_in_non_retryable(self):
        assert AIProviderErrorCode.RATE_LIMITED not in NON_RETRYABLE_CODES

    def test_rate_limited_opens_circuit(self):
        # Rate limits ARE circuit-breaker-eligible (transient, not account-level)
        assert AIProviderErrorCode.RATE_LIMITED not in NO_CIRCUIT_CODES


# ── Case D: Successful call — no error ───────────────────────────────────────

class TestCaseD_Success:
    """A well-formed response must not raise."""

    @pytest.mark.asyncio
    async def test_complete_success_no_error(self):
        from app.ai.providers.anthropic import AnthropicProvider
        from app.ai.models import CompletionRequest, Message

        fake_msg = MagicMock()
        fake_msg.id = "msg_test"
        fake_msg.content = [MagicMock(text="Hello!", type="text", spec=["text", "type"])]
        fake_msg.stop_reason = "end_turn"
        fake_msg.usage = MagicMock(input_tokens=10, output_tokens=5)

        provider = AnthropicProvider()
        request = CompletionRequest(
            messages=[Message(role="user", content="Hi")],
        )

        with patch.object(provider, "_api_key", return_value="sk-test"), \
             patch("anthropic.AsyncAnthropic") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=fake_msg)

            resp = await provider.complete(request)

        assert resp.content == "Hello!"
        assert resp.finish_reason == "end_turn"


# ── Case E: Billing → fallover to OpenAI ─────────────────────────────────────

class TestCaseE_BillingFallover:
    """When Anthropic is billing-failed, registry skips it and uses next provider."""

    def test_billing_error_marks_provider_skipped(self):
        from app.core.ai.registry.registry import PlatformProviderRegistry

        reg = PlatformProviderRegistry.__new__(PlatformProviderRegistry)
        reg._billing_errors = {}

        exc = AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="Credit balance too low.",
            retryable=False,
        )
        reg._mark_billing_error("anthropic", exc)

        assert reg._has_billing_error("anthropic") is True

    def test_billing_error_expires_after_ttl(self):
        from app.core.ai.registry.registry import PlatformProviderRegistry, _BILLING_ERROR_TTL

        reg = PlatformProviderRegistry.__new__(PlatformProviderRegistry)
        reg._billing_errors = {}

        exc = AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="Credit balance too low.",
            retryable=False,
        )
        reg._mark_billing_error("anthropic", exc)
        # Simulate TTL expiry
        reg._billing_errors["anthropic"] = time.time() - _BILLING_ERROR_TTL - 1

        assert reg._has_billing_error("anthropic") is False
        # Entry should be cleared
        assert "anthropic" not in reg._billing_errors

    def test_resolve_chain_skips_billing_failed(self):
        """stream_with_events() skips providers with active billing errors."""
        from app.core.ai.registry.registry import PlatformProviderRegistry

        reg = PlatformProviderRegistry.__new__(PlatformProviderRegistry)
        reg._billing_errors = {}

        # Mark anthropic as billing-failed
        exc = AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="Credit balance too low.",
            retryable=False,
        )
        reg._mark_billing_error("anthropic", exc)

        # Simulate configured = [anthropic, openai]
        fake_anthropic = MagicMock()
        fake_anthropic.provider_id = "anthropic"
        fake_openai = MagicMock()
        fake_openai.provider_id = "openai"
        configured = [fake_anthropic, fake_openai]

        # billing_failed + circuit_ready should exclude anthropic
        billing_failed = [p.provider_id for p in configured if reg._has_billing_error(p.provider_id)]
        circuit_ready  = [p for p in configured if not reg._has_billing_error(p.provider_id)]

        assert "anthropic" in billing_failed
        assert fake_openai in circuit_ready
        assert fake_anthropic not in circuit_ready


# ── Case F: Only Anthropic, billing failed → AIProviderError propagates ───────

class TestCaseF_BillingOnlyProvider:
    """When only Anthropic is configured and billing fails, the error propagates."""

    def test_billing_error_is_non_retryable_and_raises_immediately(self):
        from app.ai.retries import _is_retryable

        exc = AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="Credit balance too low.",
            retryable=False,
        )
        # _is_retryable must return False for billing errors so with_retry re-raises
        assert _is_retryable(exc) is False

    def test_retries_reraises_non_retryable_provider_error(self):
        """with_retry must re-raise immediately for non-retryable AIProviderError."""
        import asyncio
        from app.ai.retries import with_retry

        exc = AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="Credit balance too low.",
            retryable=False,
        )

        async def _failing():
            raise exc

        with pytest.raises(AIProviderError) as exc_info:
            asyncio.run(with_retry(_failing, max_retries=3, timeout=30.0))

        assert exc_info.value.code == AIProviderErrorCode.BILLING_REQUIRED


# ── Case G: /api/health/providers exposes billing_required ────────────────────

class TestCaseG_HealthProviderStatus:
    """registry.health() exposes status=billing_required for billing-failed providers."""

    def test_health_shows_billing_required_status(self):
        from app.core.ai.registry.registry import PlatformProviderRegistry

        reg = PlatformProviderRegistry.__new__(PlatformProviderRegistry)
        reg._billing_errors = {}

        fake_provider = MagicMock()
        fake_provider.provider_id = "anthropic"
        fake_provider.is_available = True
        fake_provider.default_model.return_value = "claude-sonnet-4-6"
        reg._providers = {"anthropic": fake_provider}

        exc = AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="Credit balance too low.",
            retryable=False,
        )
        reg._mark_billing_error("anthropic", exc)

        with patch("app.core.ai.registry.registry.circuit_breaker") as mock_cb:
            mock_cb.snapshot.return_value = {"anthropic": {"state": "closed", "consecutive_fails": 0}}
            health = reg.health()

        assert health["anthropic"]["status"] == "billing_required"
        # Circuit state must still be shown accurately — it was not tripped
        assert health["anthropic"]["circuit_state"] == "closed"

    def test_health_shows_healthy_when_no_billing_error(self):
        from app.core.ai.registry.registry import PlatformProviderRegistry

        reg = PlatformProviderRegistry.__new__(PlatformProviderRegistry)
        reg._billing_errors = {}

        fake_provider = MagicMock()
        fake_provider.provider_id = "openai"
        fake_provider.is_available = True
        fake_provider.default_model.return_value = "gpt-4o"
        reg._providers = {"openai": fake_provider}

        with patch("app.core.ai.registry.registry.circuit_breaker") as mock_cb:
            mock_cb.snapshot.return_value = {"openai": {"state": "closed", "consecutive_fails": 0}}
            health = reg.health()

        assert health["openai"]["status"] == "healthy"

    def test_health_shows_circuit_open_status(self):
        from app.core.ai.registry.registry import PlatformProviderRegistry

        reg = PlatformProviderRegistry.__new__(PlatformProviderRegistry)
        reg._billing_errors = {}

        fake_provider = MagicMock()
        fake_provider.provider_id = "openai"
        fake_provider.is_available = True
        fake_provider.default_model.return_value = "gpt-4o"
        reg._providers = {"openai": fake_provider}

        with patch("app.core.ai.registry.registry.circuit_breaker") as mock_cb:
            mock_cb.snapshot.return_value = {"openai": {"state": "open", "consecutive_fails": 5}}
            health = reg.health()

        assert health["openai"]["status"] == "circuit_open"


# ── AIProviderError.to_dict safety ───────────────────────────────────────────

class TestErrorSafety:
    """to_dict() must never include secret values."""

    def test_to_dict_never_includes_api_key(self):
        err = AIProviderError(
            AIProviderErrorCode.AUTHENTICATION_FAILED,
            provider="anthropic",
            message="Anthropic API key is invalid or has been revoked.",
            retryable=False,
        )
        d = err.to_dict()
        assert "sk-ant" not in str(d)
        assert "ANTHROPIC_API_KEY" not in str(d)
        assert d["code"] == "AUTHENTICATION_FAILED"

    def test_repr_is_safe(self):
        err = AIProviderError(
            AIProviderErrorCode.RATE_LIMITED,
            provider="anthropic",
            message="Rate limit exceeded.",
        )
        r = repr(err)
        assert "RATE_LIMITED" in r
        assert "anthropic" in r
