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
import time
from typing import Optional

from app.ai.models import CompletionRequest, CompletionResponse, ProviderID, StreamChunk
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import BaseProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai import OpenAIProvider
from app.core.ai.events.bus import bus
from app.core.ai.events.events import (
    ProviderFailed, ProviderSelected, ModelSelected,
)
from app.core.ai.providers.openrouter import OpenRouterProvider
from app.core.ai.providers.local import LocalProvider

log = logging.getLogger(__name__)


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
        self._providers: dict[str, BaseProvider] = {}
        self._register_defaults()

    # ── Registration ──────────────────────────────────────────────────────────

    def _register_defaults(self) -> None:
        for p in [
            AnthropicProvider(),
            OpenAIProvider(),
            GeminiProvider(),
            OpenRouterProvider(),
            LocalProvider(),
        ]:
            self._providers[p.provider_id] = p

    def register(self, provider: BaseProvider) -> None:
        """Register or replace a provider at runtime."""
        self._providers[provider.provider_id] = provider
        log.info("PlatformRegistry: registered provider '%s'", provider.provider_id)

    def unregister(self, provider_id: str) -> None:
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
            "openrouter", "local",
        ]
        for pid in order:
            p = self._providers.get(str(pid) if hasattr(pid, "value") else pid)
            if p and p.is_available:
                return p
        raise RuntimeError(
            "No AI provider is configured. Set at least one API key: "
            "ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, "
            "or LOCAL_MODEL_BASE_URL."
        )

    def available(self) -> list[str]:
        """Return provider IDs of all configured providers."""
        return [pid for pid, p in self._providers.items() if p.is_available]

    def health(self) -> dict[str, dict]:
        """Return availability status for every known provider."""
        return {
            pid: {
                "available":    p.is_available,
                "provider_id":  pid,
                "default_model": p.default_model() if p.is_available else None,
            }
            for pid, p in self._providers.items()
        }

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
        """Return ordered list: [primary, ...fallbacks], all available."""
        primary_id   = str(request.provider or "")
        fallback_ids = [str(f) for f in (request.fallback_providers or [])]

        if primary_id:
            chain_ids = [primary_id] + [f for f in fallback_ids if f != primary_id]
        else:
            # No explicit preference — use the global default as first
            try:
                primary_id = self.default().provider_id
            except RuntimeError:
                return []
            chain_ids = [primary_id] + fallback_ids

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
        """Try each provider in chain; emit events on selection and failure."""
        chain = self.resolve_chain(request)
        if not chain:
            raise RuntimeError("No available AI providers.")

        last_err: Exception = RuntimeError("No providers tried")
        for attempt, provider in enumerate(chain):
            model = provider.resolve_model(request.model)
            await bus.emit(ProviderSelected(
                provider_id=provider.provider_id,
                model=model,
                reason="preferred" if attempt == 0 else "failover",
            ))
            try:
                t0   = time.perf_counter()
                resp = await provider.complete(request)
                log.info(
                    "complete via %s model=%s latency=%.0fms",
                    provider.provider_id, model, (time.perf_counter() - t0) * 1000,
                )
                return resp, provider.provider_id
            except Exception as exc:
                await bus.emit(ProviderFailed(
                    provider_id=provider.provider_id,
                    error=str(exc),
                    attempt=attempt,
                ))
                log.warning("Provider %s failed (attempt %d): %s", provider.provider_id, attempt, exc)
                last_err = exc

        raise last_err

    async def stream_with_events(
        self,
        request: CompletionRequest,
        *,
        request_id: str = "",
    ):
        """Stream from primary provider; emit events; fall back on failure."""
        chain = self.resolve_chain(request)
        if not chain:
            yield StreamChunk(type="error", error="No available AI providers.")
            return

        provider = chain[0]
        model    = provider.resolve_model(request.model)

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

        try:
            async for chunk in provider.stream(request):
                yield chunk
        except Exception as exc:
            await bus.emit(ProviderFailed(
                provider_id=provider.provider_id,
                error=str(exc),
                attempt=0,
            ))
            log.warning("Stream failed on %s: %s — attempting fallback", provider.provider_id, exc)

            for fallback in chain[1:]:
                try:
                    resp = await fallback.complete(request)
                    yield StreamChunk(type="delta", text=resp.content)
                    if resp.tool_calls:
                        for tc in resp.tool_calls:
                            yield StreamChunk(type="tool_call", tool_call=tc)
                    yield StreamChunk(type="usage", usage=resp.usage)
                    yield StreamChunk(type="done")
                    return
                except Exception as fb_exc:
                    log.warning("Fallback %s also failed: %s", fallback.provider_id, fb_exc)

            yield StreamChunk(type="error", error=str(exc))


# Module-level singleton for the platform
platform_registry = PlatformProviderRegistry()
