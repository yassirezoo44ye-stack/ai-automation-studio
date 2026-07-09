"""
AI Gateway — the single entry point for all AI calls.

Orchestrates: provider selection, caching, prompt versioning, memory,
              history, retries/timeouts, cost tracking, streaming.

No UI component or router should call provider APIs directly.
All AI calls go through AIGateway.complete() or AIGateway.stream().
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Optional

from app.ai import memory as mem
from app.ai import cost_tracker
from app.ai import prompt_store
from app.ai.cache import cache
from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk, Message,
)
from app.ai.providers.registry import registry
from app.ai.retries import with_retry

log = logging.getLogger(__name__)


class AIGateway:
    """
    Usage::

        gw = AIGateway(pool)
        response = await gw.complete(request)
        async for chunk in gw.stream(request):
            ...
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    # ── Public: non-streaming ─────────────────────────────────────────────────

    async def complete(
        self,
        request: CompletionRequest,
        *,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> CompletionResponse:
        if org_id:
            await self._check_quota(org_id)

        request = await self._enrich(request, user_id=user_id)

        # Cache check
        if request.cache_ttl:
            key = cache.make_key(request)
            hit = cache.get(key)
            if hit:
                log.debug("Cache hit for request")
                return hit

        async def _call() -> CompletionResponse:
            resp, _ = await registry.complete_with_failover(request)
            return resp

        response = await with_retry(
            _call,
            max_retries=request.max_retries,
            timeout=request.timeout,
        )

        await self._post_complete(request, response, user_id=user_id, org_id=org_id)

        # Store in cache
        if request.cache_ttl:
            cache.set(cache.make_key(request), response, request.cache_ttl)

        return response

    # ── Public: streaming ─────────────────────────────────────────────────────

    async def stream(
        self,
        request: CompletionRequest,
        *,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        if org_id:
            await self._check_quota(org_id)

        request = await self._enrich(request, user_id=user_id)

        # Emit conversation ID immediately if we have one
        if request.conversation_id:
            yield StreamChunk(type="conv_id", conv_id=request.conversation_id)

        full_text = ""
        last_usage = None

        async for chunk in registry.stream_with_failover(request):
            if chunk.type == "delta" and chunk.text:
                full_text += chunk.text
            if chunk.type == "usage":
                last_usage = chunk.usage
            yield chunk

        # Persist after stream completes
        if full_text or last_usage:
            dummy_response = CompletionResponse(
                content=full_text,
                usage=last_usage or CompletionResponse().usage,
                conversation_id=request.conversation_id,
            )
            await self._post_complete(request, dummy_response, user_id=user_id, org_id=org_id)

    # ── Enrichment ────────────────────────────────────────────────────────────

    async def _enrich(
        self,
        request: CompletionRequest,
        *,
        user_id: Optional[str],
    ) -> CompletionRequest:
        """
        1. Load versioned prompt template and render variables.
        2. Load conversation history.
        3. Inject long-term memory into system prompt.
        """
        messages = list(request.messages)
        system   = request.system

        # 1. Prompt template
        if request.prompt_id:
            version = await prompt_store.get_active_version(self._pool, request.prompt_id)
            if version:
                rendered_sys, rendered_user = await prompt_store.render(
                    version, request.prompt_variables
                )
                if rendered_sys:
                    system = rendered_sys
                if rendered_user and not messages:
                    messages = [Message(role="user", content=rendered_user)]

        # 2. Conversation history
        if request.conversation_id:
            history = await mem.load_history(self._pool, request.conversation_id)
            # Prepend history before new messages (skip if history already present)
            if history and messages:
                messages = history + messages
            elif history:
                messages = history

        # 3. Long-term memory injection
        if request.memory_enabled and user_id:
            mem_ctx = await mem.build_memory_context(self._pool, user_id=user_id)
            if mem_ctx:
                system = (system + "\n\n" + mem_ctx) if system else mem_ctx

        return request.model_copy(update={
            "messages": messages,
            "system":   system,
        })

    # ── Post-completion side-effects ──────────────────────────────────────────

    async def _post_complete(
        self,
        request: CompletionRequest,
        response: CompletionResponse,
        *,
        user_id: Optional[str],
        org_id: Optional[str] = None,
    ) -> None:
        """Persist history, track cost, meter org usage. All failures are non-fatal."""

        # Persist assistant message
        if request.conversation_id and response.content:
            # Persist last user message (the one not in history yet)
            last_user = next(
                (m for m in reversed(request.messages) if m.role == "user"), None
            )
            if last_user:
                content = last_user.content if isinstance(last_user.content, str) else ""
                if content:
                    await mem.append_message(
                        self._pool,
                        request.conversation_id,
                        "user",
                        content,
                    )
            await mem.append_message(
                self._pool,
                request.conversation_id,
                "assistant",
                response.content,
            )

        # Track cost
        if response.usage.total_tokens > 0:
            await cost_tracker.record(
                pool=self._pool,
                user_id=user_id,
                conversation_id=request.conversation_id,
                stats=response.usage,
                cached=response.cached,
            )

        # Meter organization token quota (best-effort — never blocks the response)
        if org_id and response.usage.total_tokens > 0:
            try:
                from app.billing import get_usage_service
                await get_usage_service().record(
                    org_id, "tokens", response.usage.total_tokens,
                    ref_type="ai_gateway", ref_id=request.conversation_id,
                )
            except Exception:
                log.warning("usage record failed for org=%s", org_id, exc_info=True)

    async def _check_quota(self, org_id: str) -> None:
        """Raise QuotaExceeded (mapped to HTTP 429 by the app's exception
        handler) BEFORE spending money on a provider call."""
        from app.billing import get_usage_service
        await get_usage_service().check_quota(org_id, "tokens", 1)
