"""
Provider registry with failover logic.
Knows about all available providers and selects/falls back between them.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator

from app.ai.models import CompletionRequest, CompletionResponse, ProviderID, StreamChunk
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import BaseProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai import OpenAIProvider

log = logging.getLogger(__name__)

_ALL: dict[str, BaseProvider] = {
    ProviderID.anthropic: AnthropicProvider(),
    ProviderID.openai:    OpenAIProvider(),
    ProviderID.gemini:    GeminiProvider(),
}

# Ordered preference when provider=None
_DEFAULT_ORDER = [ProviderID.anthropic, ProviderID.openai, ProviderID.gemini]


class ProviderRegistry:
    """Single instance shared across the app."""

    def register_provider(self, provider_id: str, provider: BaseProvider) -> None:
        """Dynamic registration — for a Plugin SDK AI_PROVIDER-type plugin.
        The built-in providers above are still wired at module load time;
        this just lets a plugin add to the same `_ALL` dict at runtime."""
        _ALL[provider_id] = provider
        log.info("registered AI provider: %s", provider_id)

    def unregister_provider(self, provider_id: str) -> bool:
        if provider_id in _DEFAULT_ORDER:
            raise ValueError(f"cannot unregister built-in provider {provider_id!r}")
        return _ALL.pop(provider_id, None) is not None

    def get(self, provider_id: str) -> BaseProvider:
        p = _ALL.get(provider_id)
        if not p:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not p.is_available:
            raise RuntimeError(f"Provider {provider_id!r} has no API key configured")
        return p

    def resolve(self, request: CompletionRequest) -> BaseProvider:
        """Pick the primary provider, respecting the request preference."""
        preferred = request.provider or self._first_available()
        return self.get(preferred)

    def failover_chain(self, request: CompletionRequest) -> list[BaseProvider]:
        """Return ordered list: [primary, ...fallbacks] all filtered to available."""
        primary_id = request.provider or self._first_available()
        fallback_ids = request.fallback_providers or []
        chain_ids = [primary_id] + [f for f in fallback_ids if f != primary_id]
        return [_ALL[pid] for pid in chain_ids if pid in _ALL and _ALL[pid].is_available]

    def _first_available(self) -> str:
        for pid in _DEFAULT_ORDER:
            if _ALL.get(pid, None) and _ALL[pid].is_available:
                return pid
        raise RuntimeError(
            "No AI provider is available. Set at least one of: "
            "ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY"
        )

    def list_available(self) -> list[str]:
        return [pid for pid, p in _ALL.items() if p.is_available]

    # ── Completion with failover ──────────────────────────────────────────────

    async def complete_with_failover(
        self,
        request: CompletionRequest,
    ) -> tuple[CompletionResponse, str]:
        """Try each provider in the failover chain. Returns (response, provider_id)."""
        chain = self.failover_chain(request)
        if not chain:
            raise RuntimeError("No available AI providers.")

        last_err: Exception = RuntimeError("No providers tried")
        for provider in chain:
            try:
                log.info("AI complete via %s model=%s", provider.provider_id, request.model)
                resp = await provider.complete(request)
                return resp, provider.provider_id
            except Exception as exc:
                log.warning("Provider %s failed: %s — trying next", provider.provider_id, exc)
                last_err = exc

        raise last_err

    async def stream_with_failover(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream from primary provider; on error, yield an error chunk."""
        chain = self.failover_chain(request)
        if not chain:
            yield StreamChunk(type="error", error="No available AI providers.")
            return

        provider = chain[0]
        try:
            log.info("AI stream via %s model=%s", provider.provider_id, request.model)
            async for chunk in provider.stream(request):
                yield chunk
        except Exception as exc:
            log.warning("Stream failed on %s: %s", provider.provider_id, exc)
            # Attempt non-streaming fallback on next provider
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


# Module-level singleton
registry = ProviderRegistry()
