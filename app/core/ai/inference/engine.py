"""
InferenceEngine — the authoritative AI request executor.

Replaces direct AIGateway calls in routers. Adds:
- Event emission (PromptStarted, PromptCompleted, StreamStarted, StreamEnded)
- Latency tracking
- ModelRouter integration (auto-selects best model if none specified)
- MemoryManager integration
- Agentic tool loop (delegates to tool_loop module)
- Caching via the existing ResponseCache

Routers call the engine — the engine calls providers. Nothing else does.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import AsyncGenerator, Optional

from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk,
)
from app.core.ai.events.bus import bus
from app.core.ai.events.events import (
    PromptCompleted, PromptStarted,
    StreamEnded, StreamStarted,
)
from app.core.ai.inference.tool_loop import run_tool_loop, stream_tool_loop
from app.core.ai.registry.registry import platform_registry
from app.core.ai.router.model_router import model_router
from app.core.ai.telemetry.service import telemetry

log = logging.getLogger(__name__)


class InferenceEngine:
    """
    Central AI request executor.

    Usage::

        engine = InferenceEngine(pool=db_pool)
        resp   = await engine.complete(request, user_id=uid)

        async for chunk in engine.stream(request, user_id=uid):
            ...
    """

    def __init__(self, pool=None) -> None:
        self._pool = pool

    # ── Non-streaming ─────────────────────────────────────────────────────────

    async def complete(
        self,
        request: CompletionRequest,
        *,
        user_id:     Optional[str] = None,
        org_id:      Optional[str] = None,
        auto_tools:  bool          = True,
    ) -> CompletionResponse:
        """
        Execute a completion request end-to-end.

        If auto_tools=True and the response contains tool_calls, runs the
        agentic tool loop until a final answer is produced.

        When org_id is supplied, the request is metered and quota-checked
        against that organization's plan (see app/billing/usage.py); omit
        it for personal/legacy callers with no org context.
        """
        request_id = str(uuid.uuid4())

        # Auto-select model if not set
        request = self._apply_model_selection(request)

        # Enrich via legacy gateway (prompt templates, memory, history)
        gw = self._gateway()
        if org_id:
            await gw._check_quota(org_id)
        enriched = await gw._enrich(request, user_id=user_id)

        provider_id = platform_registry.resolve_chain(enriched)[0].provider_id if platform_registry.resolve_chain(enriched) else "unknown"
        model       = enriched.model or "unknown"

        await bus.emit(PromptStarted(
            request_id=request_id,
            provider_id=provider_id,
            model=model,
            user_id=user_id,
            conversation_id=enriched.conversation_id,
        ))

        t0 = time.perf_counter()
        try:
            resp, used_provider = await platform_registry.complete_with_events(
                enriched, request_id=request_id
            )

            if auto_tools and resp.tool_calls:
                resp = await run_tool_loop(
                    enriched, resp,
                    gateway=gw,
                    user_id=user_id,
                )

            await gw._post_complete(enriched, resp, user_id=user_id, org_id=org_id)

            latency_ms = (time.perf_counter() - t0) * 1000
            await bus.emit(PromptCompleted(
                request_id=request_id,
                provider_id=resp.usage.provider or used_provider,
                model=resp.usage.model or model,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                cost_usd=resp.usage.cost_usd,
                latency_ms=latency_ms,
                cached=resp.cached,
            ))
            return resp

        except Exception:
            latency_ms = (time.perf_counter() - t0) * 1000
            log.exception("InferenceEngine.complete failed after %.0fms", latency_ms)
            raise

    # ── Streaming ─────────────────────────────────────────────────────────────

    async def stream(
        self,
        request: CompletionRequest,
        *,
        user_id:    Optional[str] = None,
        org_id:     Optional[str] = None,
        auto_tools: bool          = True,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a completion request end-to-end.

        Yields dicts suitable for JSON serialization in SSE responses.
        Includes tool execution between stream segments when auto_tools=True.

        When org_id is supplied, the request is quota-checked up front and
        metered on completion (see app/billing/usage.py).
        """
        request_id = str(uuid.uuid4())
        request    = self._apply_model_selection(request)
        gw         = self._gateway()
        if org_id:
            await gw._check_quota(org_id)
        enriched   = await gw._enrich(request, user_id=user_id)

        chain       = platform_registry.resolve_chain(enriched)
        provider_id = chain[0].provider_id if chain else "unknown"
        model       = enriched.model or "unknown"

        await bus.emit(StreamStarted(
            request_id=request_id,
            provider_id=provider_id,
            model=model,
            user_id=user_id,
        ))

        # Emit conv_id first if known
        if enriched.conversation_id:
            yield {"type": "conv_id", "conv_id": enriched.conversation_id}

        t0 = time.perf_counter()
        chunks_emitted = 0

        try:
            if auto_tools:
                gen = stream_tool_loop(
                    enriched,
                    gateway=gw,
                    user_id=user_id,
                )
            else:
                gen = self._raw_stream(enriched, gw, user_id=user_id)

            full_text  = ""
            last_usage = None

            async for chunk_dict in gen:
                yield chunk_dict
                chunks_emitted += 1
                if isinstance(chunk_dict, dict):
                    if chunk_dict.get("type") == "delta":
                        full_text += chunk_dict.get("text", "")
                    if chunk_dict.get("type") == "usage":
                        last_usage = chunk_dict.get("usage")

            # Post-complete persistence
            if full_text:
                from app.ai.models import CompletionResponse, UsageStats
                dummy = CompletionResponse(
                    content=full_text,
                    usage=UsageStats(**(last_usage or {})) if last_usage else UsageStats(),
                    conversation_id=enriched.conversation_id,
                )
                await gw._post_complete(enriched, dummy, user_id=user_id, org_id=org_id)

        finally:
            latency_ms = (time.perf_counter() - t0) * 1000
            await bus.emit(StreamEnded(
                request_id=request_id,
                provider_id=provider_id,
                chunks_emitted=chunks_emitted,
                latency_ms=latency_ms,
            ))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _gateway(self):
        from app.ai.gateway import AIGateway
        return AIGateway(self._pool)

    def _apply_model_selection(self, request: CompletionRequest) -> CompletionRequest:
        if request.model:
            return request  # caller was explicit
        available = platform_registry.available()
        selection = model_router.select(request, available_providers=available)
        return request.model_copy(update={"model": selection.model_id})

    async def _raw_stream(self, request, gw, user_id):
        """Non-tool stream directly from gateway."""
        from app.ai.models import StreamChunk
        async for chunk in gw.stream(request, user_id=user_id):
            if isinstance(chunk, StreamChunk):
                yield chunk.model_dump()
            else:
                yield chunk
