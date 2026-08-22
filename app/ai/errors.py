"""
Normalized AI provider error classification.

All provider implementations raise AIProviderError for known failure modes
so that the registry, gateway, and routers can make routing and HTTP-status
decisions without parsing opaque exception messages.

Usage (provider side)::

    from app.ai.errors import AIProviderError, AIProviderErrorCode

    raise AIProviderError(
        AIProviderErrorCode.BILLING_REQUIRED,
        provider="anthropic",
        message="Credit balance is too low.",
        retryable=False,
        request_id=exc.request_id or "",
    )

Usage (caller side)::

    from app.ai.errors import AIProviderError, AIProviderErrorCode

    except AIProviderError as exc:
        if exc.code == AIProviderErrorCode.BILLING_REQUIRED:
            return http_402(...)
        raise
"""
from __future__ import annotations

from enum import Enum


class AIProviderErrorCode(str, Enum):
    """Normalized classification for every AI provider failure mode."""
    BILLING_REQUIRED      = "BILLING_REQUIRED"       # credits exhausted / payment needed
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"  # invalid or expired API key
    RATE_LIMITED          = "RATE_LIMITED"            # 429 — back off and retry
    INVALID_REQUEST       = "INVALID_REQUEST"         # malformed payload (4xx other than above)
    PROVIDER_UNAVAILABLE  = "PROVIDER_UNAVAILABLE"   # network / 5xx / overload
    TIMEOUT               = "TIMEOUT"                # request timed out
    UNKNOWN               = "UNKNOWN"                # unclassified


# Codes that must NOT be retried — re-sending the same request will not help.
NON_RETRYABLE_CODES: frozenset[AIProviderErrorCode] = frozenset({
    AIProviderErrorCode.BILLING_REQUIRED,
    AIProviderErrorCode.AUTHENTICATION_FAILED,
    AIProviderErrorCode.INVALID_REQUEST,
})

# Codes that must NOT open the circuit breaker.
# Billing and auth failures are permanent account-level conditions, not
# transient API instability.  Opening the circuit would (a) mask the real
# cause in health diagnostics and (b) give the misleading impression that the
# provider "recovered" once the circuit enters half-open and the request
# fails again for the exact same reason.
NO_CIRCUIT_CODES: frozenset[AIProviderErrorCode] = frozenset({
    AIProviderErrorCode.BILLING_REQUIRED,
    AIProviderErrorCode.AUTHENTICATION_FAILED,
})


class AIProviderError(Exception):
    """
    Raised by AI provider implementations for classified, known failure modes.

    Attributes
    ----------
    code        : Normalized failure category (AIProviderErrorCode).
    provider    : Provider that raised the error, e.g. "anthropic".
    message     : Human-readable description — NEVER includes secret values
                  (API keys, auth headers, credentials).
    retryable   : Whether the gateway should retry / fail over to the next
                  provider.  Derived from ``code`` by default; the caller may
                  override it only when the upstream response explicitly
                  signals retry-ability (e.g. Retry-After header).
    request_id  : Upstream request-ID for server-side diagnostics — safe to
                  log, safe to include in structured error responses.
    """

    def __init__(
        self,
        code: AIProviderErrorCode,
        provider: str,
        message: str,
        *,
        retryable: bool | None = None,
        request_id: str = "",
    ) -> None:
        super().__init__(message)
        self.code       = code
        self.provider   = provider
        self.message    = message
        # Derive retryable from code unless the caller supplies an explicit
        # override — useful when an upstream Retry-After header signals that
        # a normally-terminal error is actually temporary.
        self.retryable  = (code not in NON_RETRYABLE_CODES) if retryable is None else retryable
        self.request_id = request_id

    def to_dict(self) -> dict:
        """
        Serializable representation — safe to embed in API error responses.
        Never includes the API key or any other secret.
        """
        return {
            "code":       self.code.value,
            "provider":   self.provider,
            "message":    self.message,
            "retryable":  self.retryable,
            **({"request_id": self.request_id} if self.request_id else {}),
        }

    def __repr__(self) -> str:
        return (
            f"AIProviderError(code={self.code.value!r}, "
            f"provider={self.provider!r}, retryable={self.retryable})"
        )
