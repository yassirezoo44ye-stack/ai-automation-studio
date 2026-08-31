"""
Enhanced ProviderRegistry — extends the base registry with:
- OpenRouter and Local provider support
- Event emission on provider selection / failure
- Health check API
- Capability introspection per provider

All AI code goes through this registry. Never instantiate providers directly.
"""
from __future__ import annotations

import logging
import os
import time

from app.ai.circuit_breaker import circuit_breaker
from app.ai.errors import AIProviderError, NO_CIRCUIT_CODES, AIProviderErrorCode
from app.ai.models import CompletionRequest, CompletionResponse, ProviderID, StreamChunk
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import BaseProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai import OpenAIProvider
from app.ai.retries import with_retry
from app.core.ai.events.bus import bus
from app.core.ai.events.events import (
    ProviderFailed, ProviderSelected, ModelSelected,
)
from app.core.ai.providers.openrouter import OpenRouterProvider
from app.core.ai.providers.groq import GroqProvider
from app.core.ai.providers.local import LocalProvider
from app.ai.providers.dev_mock import DevMockProvider
from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)

# How long to suppress a provider that returned a billing/auth error before
# re-attempting it. These are account-level failures — not transient — so we
# wait long enough to avoid hammering the API, but short enough that a
# freshly-added key or recharged account starts working within the hour.
_BILLING_ERROR_TTL: float = 3600.0  # 1 hour


class PlatformProviderRegistry:
    """
    Extended provider registry for the AI Platform.

    API::

        registry.get("anthropic")   → BaseProvider (or raises)
        registry.default()          → BaseProvider
        registry.available()        → list[str]
        registry.health()           → dict[str, bool]

    All methods are synchronous; async helpers delegate to the provider.
    """

    def __init__(self) -> None:
        self._providers:  dict[str, BaseProvider] = {}
        self._builtin_ids: set[str] = set()
        # See app.plugins.registry_guard's module docstring — without
        # this, a plugin could register provider_id="anthropic" (or any
        # other built-in/other-plugin id) and silently hijack every
        # completion request the platform routes to that id, redirecting
        # prompts/keys/responses into its own sandbox.
        from app.plugins.registry_guard import OwnershipTracker
        self._owners = OwnershipTracker("AI provider")
        # Per-provider billing/auth error timestamps — keyed by provider_id,
        # value is the time.time() when the error was last recorded.
        # Unlike the circuit breaker (which tracks transient failures), these
        # account-level errors must NOT open the circuit — doing so would
        # mask the real cause in health diagnostics and give the misleading
        # impression that the provider "recovered" once the circuit re-opens.
        self._billing_errors: dict[str, float] = {}
        self._register_defaults()

    # ── Registration ──────────────────────────────────────────────────────────

    def _register_defaults(self) -> None:
        for p in [
            AnthropicProvider(),
            OpenAIProvider(),
            GeminiProvider(),
            OpenRouterProvider(),
            GroqProvider(),
            LocalProvider(),
            DevMockProvider(),  # dev/owner account only — not in default() chain
        ]:
            self._providers[p.provider_id] = p
            self._builtin_ids.add(p.provider_id)
            self._owners.claim(p.provider_id, None)

    def register(self, provider: BaseProvider, *, owner: str | None = None) -> None:
        """Register or replace a provider at runtime (e.g. an AI_PROVIDER-type
        plugin). Built-in providers are still wired at module load time — this
        just lets a plugin add to the same dict.

        `owner` should be the plugin's installation_id
        (app.plugins.adapters.adapt_ai_provider supplies it) — raises
        RegistrationConflictError if provider_id is already held by a
        different owner (a built-in, or another plugin) instead of
        silently redirecting that id's traffic."""
        self._owners.claim(provider.provider_id, owner)
        self._providers[provider.provider_id] = provider
        log.info("PlatformRegistry: registered provider '%s' (owner=%s)", provider.provider_id, owner)

    def unregister(self, provider_id: str) -> None:
        if provider_id in self._builtin_ids:
            raise ValueError(f"cannot unregister built-in provider {provider_id!r}")
        self._owners.release(provider_id)
        self._providers.pop(provider_id, None)

    # ── Primary API ───────────────────────────────────────────────────────────

    def get(self, provider_id: str) -> BaseProvider:
        p = self._providers.get(provider_id)
        if not p:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not p.is_available:
            raise RuntimeError(
                f"Provider {provider_id!r} is not configured "
                f"(set {p._env_key()} environment variable)"
            )
        return p

    def default(self) -> BaseProvider:
        """Return the first available provider in preference order."""
        order = [
            ProviderID.anthropic, ProviderID.openai, ProviderID.gemini,
            "openrouter", "groq", "local",
        ]
        for pid in order:
            p = self._providers.get(pid.value if hasattr(pid, "value") else pid)
            if p and p.is_available:
                return p
        raise RuntimeError(
            "No AI provider is configured. Set at least one API key: "
            "ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, "
            "GROQ_API_KEY, or LOCAL_MODEL_BASE_URL."
        )

    def available(self) -> list[str]:
        """Return provider IDs of all configured providers."""
        return [pid for pid, p in self._providers.items() if p.is_available]

    def health(self) -> dict[str, dict]:
        """Return availability + circuit breaker + billing status for every known provider."""
        circuits = circuit_breaker.snapshot()
        result = {}
        for pid, p in self._providers.items():
            circuit_state = circuits.get(pid, {}).get("state", "closed")
            if not p.is_available:
                status = "unavailable"
            elif self._has_billing_error(pid):
                status = "billing_required"
            elif circuit_state == "open":
                status = "circuit_open"
            else:
                status = "healthy"
            result[pid] = {
                "available":     p.is_available,
                "provider_id":   pid,
                "default_model": p.default_model() if p.is_available else None,
                "circuit_state": circuit_state,
                "status":        status,
            }
        return result

    # ── Billing / auth error tracking ─────────────────────────────────────────

    def _mark_billing_error(self, provider_id: str, exc: AIProviderError) -> None:
        """Record a billing or auth failure for a provider.

        These are NOT forwarded to the circuit breaker — they are permanent
        account-level conditions, not transient API instability.
        """
        self._billing_errors[provider_id] = time.time()
        log.warning(
            "Provider %s marked as billing/auth error (code=%s) — "
            "will be skipped for %.0fs. Add credits or fix the API key.",
            provider_id, exc.code.value, _BILLING_ERROR_TTL,
        )

    def _has_billing_error(self, provider_id: str) -> bool:
        """Return True if this provider has an active (within TTL) billing error."""
        ts = self._billing_errors.get(provider_id)
        if ts is None:
            return False
        if time.time() - ts < _BILLING_ERROR_TTL:
            return True
        # TTL expired — clear the entry so re-attempts can flow through
        del self._billing_errors[provider_id]
        return False

    def capabilities(self, provider_id: str) -> dict:
        """Return static capability flags for a provider."""
        from app.core.ai.models.catalog import catalog
        models = catalog.for_provider(provider_id)
        return {
            "supports_tools":    any(m.supports_tools  for m in models),
            "supports_vision":   any(m.supports_vision for m in models),
            "supports_stream":   any(m.supports_stream for m in models),
            "reasoning_models":  [m.id for m in models if m.reasoning],
            "models":            [m.id for m in models],
        }

    # ── Failover chain ────────────────────────────────────────────────────────

    def resolve_chain(self, request: CompletionRequest) -> list[BaseProvider]:
        """Return ordered list: [primary, ...fallbacks], all available.

        When no explicit fallback_providers are supplied the method
        auto-appends every other configured provider in the global
        preference order so that billing failures and open circuits
        automatically route to the next healthy provider without the
        caller having to enumerate fallbacks.
        """
        primary_id   = str(request.provider or "")
        fallback_ids = [str(f) for f in (request.fallback_providers or [])]
        has_explicit_fallbacks = bool(request.fallback_providers)

        if primary_id:
            chain_ids = [primary_id] + [f for f in fallback_ids if f != primary_id]
        else:
            # No explicit preference — use the global default as first
            try:
                primary_id = self.default().provider_id
            except RuntimeError:
                return []
            chain_ids = [primary_id] + fallback_ids

        # Auto-populate the full preference order as implicit fallbacks when
        # the caller did not explicitly specify any.  This ensures billing/auth
        # failures and open circuits fall over to the next healthy provider
        # automatically rather than returning an error immediately.
        if not has_explicit_fallbacks:
            _preference_order = [
                ProviderID.anthropic.value, ProviderID.openai.value,
                ProviderID.gemini.value, "openrouter", "groq", "local",
            ]
            extra = [pid for pid in _preference_order if pid not in chain_ids]
            chain_ids = chain_ids + extra

        return [
            self._providers[pid]
            for pid in chain_ids
            if pid in self._providers and self._providers[pid].is_available
        ]

    # ── Completion with events ────────────────────────────────────────────────

    async def complete_with_events(
        self,
        request: CompletionRequest,
        *,
        request_id: str = "",
    ) -> tuple[CompletionResponse, str]:
        """Try each provider in chain; emit events on selection and failure.

        Each provider gets its own bounded retry-with-backoff (via
        app/ai/retries.py's with_retry) before failing over to the next —
        a transient 429 on the preferred provider no longer immediately
        burns the failover to a fallback. A provider whose circuit breaker
        is open (too many recent consecutive failures) is skipped entirely
        without being attempted.
        """
        chain = self.resolve_chain(request)
        if not chain:
            raise RuntimeError("No available AI providers.")

        tracer = get_tracer()
        last_err: Exception = RuntimeError("No providers tried")
        tries = 0  # count of providers actually attempted, not chain position —
                   # a skipped circuit-open provider must not shift "preferred"/
                   # "failover" labeling or the attempt index of the next one.
        # `with` owns finishing each span exactly once (on normal exit or
        # via a propagating exception) — never call span.finish() manually
        # inside a `with` block, that double-finishes it.
        with tracer.start_span("ai.complete", service="ai_gateway") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("request_id", request_id)
            for provider in chain:
                if self._has_billing_error(provider.provider_id):
                    log.debug("billing error active for %s — skipping", provider.provider_id)
                    continue
                if not circuit_breaker.allow(provider.provider_id):
                    log.debug("circuit open for %s — skipping without attempting", provider.provider_id)
                    continue

                attempt = tries
                tries += 1
                model = provider.resolve_model(request.model)
                await bus.emit(ProviderSelected(
                    provider_id=provider.provider_id,
                    model=model,
                    reason="preferred" if attempt == 0 else "failover",
                ))
                with tracer.start_span("ai.provider_call", service="ai_gateway") as pspan:
                    pspan.set_tag("provider_id", provider.provider_id)
                    pspan.set_tag("model", model)
                    pspan.set_tag("attempt", attempt)
                    try:
                        t0   = time.perf_counter()
                        resp = await with_retry(
                            lambda: provider.complete(request),
                            max_retries=1, base_delay=0.5, max_delay=2.0,
                            timeout=request.timeout,
                        )
                        log.info(
                            "complete via %s model=%s latency=%.0fms",
                            provider.provider_id, model, (time.perf_counter() - t0) * 1000,
                        )
                        circuit_breaker.record_success(provider.provider_id)
                        span.set_tag("provider_id", provider.provider_id)
                        span.set_tag("model", model)
                        return resp, provider.provider_id
                    except AIProviderError as exc:
                        pspan.set_tag("error", f"{exc.code.value}: {exc.message}")
                        if exc.code in NO_CIRCUIT_CODES:
                            # Billing/auth — permanent account condition; do NOT trip the
                            # circuit breaker. Track separately so health() shows the real cause.
                            self._mark_billing_error(provider.provider_id, exc)
                        else:
                            circuit_breaker.record_failure(provider.provider_id)
                        await bus.emit(ProviderFailed(
                            provider_id=provider.provider_id,
                            error=f"{exc.code.value}: {exc.message}",
                            attempt=attempt,
                        ))
                        log.warning(
                            "Provider %s failed (attempt %d, code=%s): %s",
                            provider.provider_id, attempt, exc.code.value, exc.message,
                        )
                        last_err = exc
                    except Exception as exc:
                        pspan.set_tag("error", str(exc))
                        circuit_breaker.record_failure(provider.provider_id)
                        await bus.emit(ProviderFailed(
                            provider_id=provider.provider_id,
                            error=str(exc),
                            attempt=attempt,
                        ))
                        log.warning("Provider %s failed (attempt %d): %s", provider.provider_id, attempt, exc)
                        last_err = exc
                        # falls through — this `with` exits normally (the
                        # exception was caught here, not left propagating),
                        # so pspan finishes without an error status; the
                        # "error" tag above still records what happened.

            if tries == 0:
                # Mirror stream_with_events: if all skips were billing/auth
                # errors, raise AIProviderError so the router can return 402
                # instead of a generic RuntimeError that becomes a 500.
                billing_failed = [
                    p.provider_id for p in chain
                    if self._has_billing_error(p.provider_id)
                ]
                if billing_failed:
                    primary = billing_failed[0]
                    raise AIProviderError(
                        AIProviderErrorCode.BILLING_REQUIRED,
                        provider=primary,
                        message=(
                            f"AI provider '{primary}' is unavailable due to an "
                            "account-level billing or authentication error. "
                            "Add credits at console.anthropic.com/plans or "
                            "verify the API key."
                        ),
                        retryable=False,
                    )
                raise RuntimeError("No available AI providers — every provider's circuit is open.")
            span.set_tag("error", str(last_err))
            raise last_err

    async def stream_with_events(
        self,
        request: CompletionRequest,
        *,
        request_id: str = "",
    ):
        """Stream from primary provider; emit events; fall back on failure.
        Skips any provider (primary or fallback) whose circuit is open."""
        # Two-stage check so the error message is actionable:
        #   Stage 1 — is anything configured (API key present)?
        #   Stage 2 — does any configured provider have an open circuit or billing error?
        configured = self.resolve_chain(request)  # already filtered to is_available=True
        if not configured:
            log.error(
                "stream_with_events: no providers configured — "
                "anthropic_configured=%s  openai_configured=%s",
                "true" if os.getenv("ANTHROPIC_API_KEY") else "false",
                "true" if os.getenv("OPENAI_API_KEY") else "false",
            )
            yield StreamChunk(
                type="error",
                error=(
                    "No AI provider is configured. "
                    "Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) in the Render "
                    "environment variables, then redeploy."
                ),
            )
            return

        # Exclude providers with active billing/auth errors (tracked separately from circuit breaker)
        billing_failed = [p.provider_id for p in configured if self._has_billing_error(p.provider_id)]
        circuit_ready  = [p for p in configured if not self._has_billing_error(p.provider_id)]

        chain = [p for p in circuit_ready if circuit_breaker.allow(p.provider_id)]
        if not chain:
            # Distinguish the two failure modes for actionable diagnostics
            if billing_failed and not circuit_ready:
                log.warning(
                    "stream_with_events: all providers billing/auth failed — providers=%s",
                    billing_failed,
                )
                # Prefix with "BILLING_REQUIRED:" so AppBuilderPage.tsx (and any
                # other SSE consumer that checks event.message.startsWith()) can
                # surface the dedicated BillingErrorOverlay instead of a generic
                # red error banner.  The primary provider is included so the
                # frontend can link to the correct provider billing page.
                primary_failed = billing_failed[0] if billing_failed else "unknown"
                yield StreamChunk(
                    type="error",
                    error=(
                        f"BILLING_REQUIRED:{primary_failed}: "
                        f"No available AI providers — "
                        f"provider{'s' if len(billing_failed) > 1 else ''} "
                        f"{', '.join(billing_failed)} require billing or authentication fix. "
                        f"Add API credits or verify your API key, then retry."
                    ),
                )
                return
            cooldown = int(circuit_breaker._cooldown)
            open_ids  = [p.provider_id for p in circuit_ready
                         if not circuit_breaker.allow(p.provider_id)]
            log.warning(
                "stream_with_events: all circuits open — providers=%s  cooldown=%ds",
                open_ids, cooldown,
            )
            yield StreamChunk(
                type="error",
                error=(
                    f"No available AI providers — all circuits are open "
                    f"({', '.join(open_ids)}). "
                    f"Retry in {cooldown}s or check GET /api/ai/providers."
                ),
            )
            return

        provider = chain[0]
        model    = provider.resolve_model(request.model)

        tracer = get_tracer()
        # Spans nest across `yield`s here — fine, since the generator is
        # driven to completion (or aclose()'d) by its caller either way,
        # which is when this `with` block's __exit__ finishes the span.
        with tracer.start_span("ai.stream", service="ai_gateway") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("request_id", request_id)
            span.set_tag("provider_id", provider.provider_id)
            span.set_tag("model", model)

            await bus.emit(ProviderSelected(
                provider_id=provider.provider_id,
                model=model,
                reason="preferred",
            ))
            await bus.emit(ModelSelected(
                provider_id=provider.provider_id,
                model=model,
                selection_reason="registry_default",
            ))

            primary_exc: Exception | None = None
            primary_failed_provider = provider.provider_id
            primary_failure_code: str = AIProviderErrorCode.UNKNOWN.value

            try:
                async for chunk in provider.stream(request):
                    yield chunk
                circuit_breaker.record_success(provider.provider_id)
                return  # primary succeeded — done
            except AIProviderError as exc:
                span.set_tag("error", f"{exc.code.value}: {exc.message}")
                if exc.code in NO_CIRCUIT_CODES:
                    self._mark_billing_error(provider.provider_id, exc)
                else:
                    circuit_breaker.record_failure(provider.provider_id)
                await bus.emit(ProviderFailed(
                    provider_id=provider.provider_id,
                    error=f"{exc.code.value}: {exc.message}",
                    attempt=0,
                ))
                log.warning(
                    "Stream failed on %s (code=%s): %s — attempting fallback",
                    provider.provider_id, exc.code.value, exc.message,
                )
                primary_exc = exc
                primary_failure_code = exc.code.value
            except Exception as exc:
                span.set_tag("error", str(exc))
                circuit_breaker.record_failure(provider.provider_id)
                await bus.emit(ProviderFailed(
                    provider_id=provider.provider_id,
                    error=str(exc),
                    attempt=0,
                ))
                log.warning("Stream failed on %s: %s — attempting fallback", provider.provider_id, exc)
                primary_exc = exc
                primary_failure_code = AIProviderErrorCode.UNKNOWN.value

            # ── Fallback chain ─────────────────────────────────────────────────
            # Walk remaining providers in order; try streaming first, fall back
            # to complete() only if the provider does not expose .stream().
            # Tracks which providers failed and why for a structured final error.
            all_failures: list[dict] = [
                {"id": primary_failed_provider, "reason": primary_failure_code.lower()}
            ]

            for fallback in chain[1:]:
                if self._has_billing_error(fallback.provider_id):
                    log.debug("billing error active for fallback %s — skipping", fallback.provider_id)
                    all_failures.append({"id": fallback.provider_id, "reason": "billing_required"})
                    continue
                if not circuit_breaker.allow(fallback.provider_id):
                    log.debug("circuit open for fallback %s — skipping", fallback.provider_id)
                    all_failures.append({"id": fallback.provider_id, "reason": "circuit_open"})
                    continue

                # Notify: automatic provider switch (logged internally; surfaced to UI)
                log.warning(
                    "provider_failover: %s → %s (primary_reason=%s)",
                    primary_failed_provider, fallback.provider_id, primary_failure_code,
                )
                yield StreamChunk(
                    type="provider_switched",
                    previous_provider=primary_failed_provider,
                    provider_id=fallback.provider_id,
                    failure_reason=primary_failure_code.lower(),
                )

                try:
                    # Prefer streaming if available (provider.stream is defined
                    # on all BaseProvider subclasses, so always try it first).
                    async for chunk in fallback.stream(request):
                        yield chunk
                    circuit_breaker.record_success(fallback.provider_id)
                    span.set_tag("provider_id", fallback.provider_id)
                    return
                except NotImplementedError:
                    # Provider does not support streaming — fall back to complete()
                    pass
                except AIProviderError as fb_exc:
                    if fb_exc.code in NO_CIRCUIT_CODES:
                        self._mark_billing_error(fallback.provider_id, fb_exc)
                    else:
                        circuit_breaker.record_failure(fallback.provider_id)
                    log.warning(
                        "Fallback stream %s failed (code=%s): %s — trying complete()",
                        fallback.provider_id, fb_exc.code.value, fb_exc.message,
                    )
                    # Fall through to complete() attempt below
                except Exception as fb_exc:
                    circuit_breaker.record_failure(fallback.provider_id)
                    log.warning(
                        "Fallback stream %s failed: %s — trying complete()",
                        fallback.provider_id, fb_exc,
                    )
                    # Fall through to complete() attempt below

                # complete() fallback for providers that don't support stream
                # or whose stream() failed transiently
                try:
                    resp = await fallback.complete(request)
                    circuit_breaker.record_success(fallback.provider_id)
                    span.set_tag("provider_id", fallback.provider_id)
                    yield StreamChunk(type="delta", text=resp.content)
                    if resp.tool_calls:
                        for tc in resp.tool_calls:
                            yield StreamChunk(type="tool_call", tool_call=tc)
                    yield StreamChunk(type="usage", usage=resp.usage)
                    yield StreamChunk(type="done")
                    return
                except AIProviderError as fb_exc:
                    if fb_exc.code in NO_CIRCUIT_CODES:
                        self._mark_billing_error(fallback.provider_id, fb_exc)
                    else:
                        circuit_breaker.record_failure(fallback.provider_id)
                    all_failures.append({"id": fallback.provider_id, "reason": fb_exc.code.value.lower()})
                    log.warning(
                        "Fallback complete() %s also failed (code=%s): %s",
                        fallback.provider_id, fb_exc.code.value, fb_exc.message,
                    )
                except Exception as fb_exc:
                    circuit_breaker.record_failure(fallback.provider_id)
                    all_failures.append({"id": fallback.provider_id, "reason": "unknown"})
                    log.warning("Fallback complete() %s also failed: %s", fallback.provider_id, fb_exc)

            # All providers exhausted — emit structured error
            all_billing = all(
                f["reason"] in ("billing_required", "authentication_failed")
                for f in all_failures
            )
            structured = {
                "code": "AI_PROVIDERS_UNAVAILABLE",
                "providers": all_failures,
            }
            import json as _json
            structured_msg = _json.dumps(structured)

            if all_billing and all_failures:
                primary_id = all_failures[0]["id"]
                yield StreamChunk(
                    type="error",
                    error=(
                        f"BILLING_REQUIRED:{primary_id}: "
                        f"No available AI providers — "
                        f"all configured providers require billing or authentication fix. "
                        f"Details: {structured_msg}"
                    ),
                )
            else:
                msg = str(primary_exc) if primary_exc else "Unknown error"
                yield StreamChunk(
                    type="error",
                    error=f"AI_PROVIDERS_UNAVAILABLE: {msg} Details: {structured_msg}",
                )


# Module-level singleton for the platform
platform_registry = PlatformProviderRegistry()
