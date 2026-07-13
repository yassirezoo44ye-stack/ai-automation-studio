"""
TelemetryService — enriched metrics with latency tracking.

Extends app.ai.cost_tracker with:
- Per-request latency
- Retry count
- Stream chunk count
- Cache hit ratio
- Provider-level aggregates
- Active stream tracking

The service subscribes to EventBus events so nothing needs to call it directly.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.ai.events.bus import bus
from app.core.ai.events.events import (
    PromptCompleted, PromptStarted,
    StreamStarted, StreamEnded,
    ToolFinished,
)

log = logging.getLogger(__name__)


@dataclass
class RequestMetrics:
    request_id:   str
    provider_id:  str
    model:        str
    started_at:   float = field(default_factory=time.monotonic)
    input_tokens:  int   = 0
    output_tokens: int   = 0
    cost_usd:      float = 0.0
    latency_ms:    float = 0.0
    retries:       int   = 0
    cached:        bool  = False
    stream_chunks: int   = 0


@dataclass
class TelemetrySummary:
    total_requests:   int   = 0
    total_input_tokens:  int = 0
    total_output_tokens: int = 0
    total_cost_usd:   float = 0.0
    avg_latency_ms:   float = 0.0
    cache_hits:       int   = 0
    cache_hit_ratio:  float = 0.0
    total_tool_calls: int   = 0
    active_streams:   int   = 0
    by_provider:      dict  = field(default_factory=dict)


class TelemetryService:
    """
    Collects and aggregates AI platform metrics.

    Subscribes to the event bus — no caller needs to instrument manually.
    """

    def __init__(self, pool=None) -> None:
        self._pool = pool
        # In-process counters (reset on restart)
        self._in_flight:   dict[str, RequestMetrics] = {}
        self._active_streams: set[str] = set()
        self._counters: dict[str, int | float] = defaultdict(int)
        self._latencies: list[float] = []
        self._tool_latencies: dict[str, list[float]] = defaultdict(list)

        self._register_handlers()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _register_handlers(self) -> None:
        bus.subscribe(PromptStarted,   self._on_prompt_started)
        bus.subscribe(PromptCompleted, self._on_prompt_completed)
        bus.subscribe(StreamStarted,   self._on_stream_started)
        bus.subscribe(StreamEnded,     self._on_stream_ended)
        bus.subscribe(ToolFinished,    self._on_tool_finished)

    async def _on_prompt_started(self, event: PromptStarted) -> None:
        self._in_flight[event.request_id] = RequestMetrics(
            request_id=event.request_id,
            provider_id=event.provider_id,
            model=event.model,
        )

    async def _on_prompt_completed(self, event: PromptCompleted) -> None:
        self._counters["total_requests"] += 1
        self._counters["total_input_tokens"]  += event.input_tokens
        self._counters["total_output_tokens"] += event.output_tokens
        self._counters[f"provider.{event.provider_id}.requests"] += 1
        self._counters[f"provider.{event.provider_id}.cost_usd"] += event.cost_usd
        self._counters["total_cost_usd"] += event.cost_usd
        if event.cached:
            self._counters["cache_hits"] += 1
        if event.latency_ms > 0:
            self._latencies.append(event.latency_ms)
            if len(self._latencies) > 1000:
                self._latencies = self._latencies[-500:]

        self._in_flight.pop(event.request_id, None)

        # No DB persist here: AIGateway._post_complete() (app/ai/gateway.py)
        # already writes this same completion to ai_usage_log — with the
        # real user_id/org_id/conversation_id context this event lacks —
        # right before PromptCompleted is emitted (see InferenceEngine.
        # complete/stream). A second write here would double-count every
        # request's cost in ai_usage_log. TelemetryService's job is the
        # in-process counters above (used by summary()), not persistence.

    async def _on_stream_started(self, event: StreamStarted) -> None:
        self._active_streams.add(event.request_id)

    async def _on_stream_ended(self, event: StreamEnded) -> None:
        self._active_streams.discard(event.request_id)

    async def _on_tool_finished(self, event: ToolFinished) -> None:
        self._counters["total_tool_calls"] += 1
        if event.latency_ms:
            self._tool_latencies[event.tool_name].append(event.latency_ms)

    # ── Metrics API ───────────────────────────────────────────────────────────

    def summary(self) -> TelemetrySummary:
        total   = int(self._counters["total_requests"])
        hits    = int(self._counters["cache_hits"])
        latency = (sum(self._latencies) / len(self._latencies)) if self._latencies else 0.0

        providers: dict[str, dict] = {}
        for key, val in self._counters.items():
            if key.startswith("provider."):
                _, pid, metric = key.split(".", 2)
                providers.setdefault(pid, {})[metric] = val

        return TelemetrySummary(
            total_requests=total,
            total_input_tokens=int(self._counters["total_input_tokens"]),
            total_output_tokens=int(self._counters["total_output_tokens"]),
            total_cost_usd=float(self._counters["total_cost_usd"]),
            avg_latency_ms=round(latency, 1),
            cache_hits=hits,
            cache_hit_ratio=round(hits / total, 3) if total else 0.0,
            total_tool_calls=int(self._counters["total_tool_calls"]),
            active_streams=len(self._active_streams),
            by_provider=providers,
        )

    async def db_totals(self, *, user_id: Optional[str] = None, org_id: Optional[str] = None,
                        since: Optional[datetime] = None) -> dict:
        from app.ai import cost_tracker
        return await cost_tracker.totals(pool=self._pool, user_id=user_id, org_id=org_id, since=since)

    async def db_by_provider(self, *, user_id: Optional[str] = None, org_id: Optional[str] = None,
                             since: Optional[datetime] = None) -> list[dict]:
        from app.ai import cost_tracker
        return await cost_tracker.by_provider(pool=self._pool, user_id=user_id, org_id=org_id, since=since)

    def tool_stats(self) -> dict[str, dict]:
        result = {}
        for name, latencies in self._tool_latencies.items():
            result[name] = {
                "calls": len(latencies),
                "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
                "max_latency_ms": round(max(latencies), 1) if latencies else 0.0,
            }
        return result

    def reset_counters(self) -> None:
        self._counters.clear()
        self._latencies.clear()
        self._tool_latencies.clear()


# Module-level singleton (pool set at app startup via platform.init())
telemetry = TelemetryService()
