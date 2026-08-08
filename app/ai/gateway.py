"""
AI Gateway — the single entry point for all AI calls.

Orchestrates: provider selection, caching, prompt versioning, memory,
              history, retries/timeouts, cost tracking, streaming.

No UI component or router should call provider APIs directly.
All AI calls go through AIGateway.complete() or AIGateway.stream().
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

from app.ai import memory as mem
from app.ai import cost_tracker
from app.ai import prompt_store
from app.ai.cache import cache
from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk, Message,
)
from app.ai.retries import with_retry
from app.core.ai.context.manager import budget_history

log = logging.getLogger(__name__)


def _message_to_dict(m: Message) -> dict[str, Any]:
    """budget_history() (app/core/ai/context/manager.py) works on plain
    role/content dicts, not Message instances — this is the adapter, not
    a new budgeting concept. A str content round-trips as-is; a
    list[ContentPart] (multimodal) is dumped to dicts via each part's own
    .model_dump(), which keeps the "text" key
    app.core.ai.utils.tokens.estimate_messages_tokens() already knows how
    to read for a TextPart, same as any other dict-shaped content list it
    was already designed to accept."""
    d: dict[str, Any] = {
        "role": m.role,
        "content": m.content if isinstance(m.content, str) else [p.model_dump() for p in m.content],
    }
    if m.name is not None:
        d["name"] = m.name
    return d


def _dict_to_message(d: dict[str, Any]) -> Message:
    """Inverse of _message_to_dict — pydantic re-validates a dumped
    ContentPart dict list back into the correct TextPart/ImagePart/
    ToolUsePart/ToolResultPart via its "type" discriminator field."""
    return Message(role=d["role"], content=d["content"], name=d.get("name"))


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
            key = cache.make_key(request, org_id=org_id)
            hit = cache.get(key)
            if hit:
                log.debug("Cache hit for request")
                return hit

        async def _call() -> CompletionResponse:
            # AI Routing consolidation: PlatformProviderRegistry
            # (app/core/ai/registry/registry.py) is the single provider
            # registry every real completion path uses — including the
            # Plugin SDK's dynamically-registered AI_PROVIDER plugins,
            # which only ever reach this registry (see app/plugins/
            # adapters.py's adapt_ai_provider).
            from app.core.ai.registry.registry import platform_registry
            resp, _ = await platform_registry.complete_with_events(request)
            return resp

        response = await with_retry(
            _call,
            max_retries=request.max_retries,
            timeout=request.timeout,
        )

        await self._post_complete(request, response, user_id=user_id, org_id=org_id)

        # Store in cache
        if request.cache_ttl:
            cache.set(cache.make_key(request, org_id=org_id), response, request.cache_ttl)

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

        from app.core.ai.registry.registry import platform_registry
        async for chunk in platform_registry.stream_with_events(request):
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
        4. Enforce the context budget (P1) on the result of 1-3 — same
           budget_history() built for chat.py/agents.py's P0 fix, applied
           here so /api/ai/complete, /api/ai/stream (both delegate to
           InferenceEngine, which calls this method directly — see
           app/core/ai/inference/engine.py) get the same protection.
           ContextBudgetError is intentionally left to propagate: neither
           complete() nor stream() below wrap this call in a try/except
           (InferenceEngine.complete()/stream() don't either — they call
           _enrich() before their own try blocks), so it reaches each
           real caller's own existing unclassified-exception handling
           unchanged — app/factory.py's app-wide 500 handler for
           /api/ai/complete, app/routers/inference.py::stream()'s
           existing generic SSE error for /api/ai/stream. No new
           HTTP/SSE behavior added.
        """
        messages = list(request.messages)
        system   = request.system

        # 1. Prompt template (ownership checked inside get_active_version)
        if request.prompt_id:
            version = await prompt_store.get_active_version(
                self._pool, request.prompt_id, user_id=user_id,
            )
            if version:
                rendered_sys, rendered_user = await prompt_store.render(
                    version, request.prompt_variables
                )
                if rendered_sys:
                    system = rendered_sys
                if rendered_user and not messages:
                    messages = [Message(role="user", content=rendered_user)]

        # 2. Conversation history (ownership is checked inside load_history)
        if request.conversation_id:
            history = await mem.load_history(
                self._pool, request.conversation_id, user_id=user_id,
            )
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

        # 4. Context budget (P1) — budget_history() works on role/content
        # dicts (see its docstring), not Message instances, so messages
        # are converted there and back. Content that's already a plain
        # string round-trips as-is; a list[ContentPart] (multimodal) is
        # converted via each part's own .model_dump() — which retains the
        # "text" key estimate_messages_tokens() already knows how to read
        # (app/core/ai/utils/tokens.py) — and reconstructed by handing
        # the dict list back to Message(), which pydantic re-validates
        # into the correct ContentPart subtype via its "type" tag.
        if messages:
            budgeted = budget_history(
                [_message_to_dict(m) for m in messages],
                model=request.model, max_tokens=request.max_tokens, system=system,
            )
            messages = [_dict_to_message(d) for d in budgeted]

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

        # Persist assistant message. Ownership is checked inside
        # append_message itself (single source of truth — see
        # memory.is_owned_by), so an unowned conversation_id silently
        # writes nothing rather than needing a duplicate check here.
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
                        user_id=user_id,
                    )
            await mem.append_message(
                self._pool,
                request.conversation_id,
                "assistant",
                response.content,
                user_id=user_id,
            )

        # Track cost
        if response.usage.total_tokens > 0:
            await cost_tracker.record(
                pool=self._pool,
                user_id=user_id,
                org_id=org_id,
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
