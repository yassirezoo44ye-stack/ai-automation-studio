"""
AI Diagnostics — observability dashboard data.

Aggregates:
- Active providers + models
- Latency (avg, p95)
- Token usage and cost
- Cache hit ratio
- Tool usage stats
- Active streams
- Memory statistics
- Event bus handler registry

Consumed by /api/ai/diagnostics endpoint.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class ProviderStatus:
    provider_id:   str
    available:     bool
    default_model: Optional[str]
    models:        list[str]
    supports_tools: bool
    supports_vision: bool


@dataclass
class DiagnosticsReport:
    timestamp:       str
    uptime_seconds:  float
    providers:       list[ProviderStatus]
    available_models: list[dict]
    metrics:         dict[str, Any]    # from TelemetryService
    cache_stats:     dict[str, Any]
    tool_stats:      dict[str, dict]
    event_handlers:  dict[str, list[str]]
    memory_stats:    dict[str, Any]

    def as_dict(self) -> dict:
        return asdict(self)


_START_TIME = time.monotonic()


class AIDiagnostics:
    """
    Collects and returns a complete AI platform health snapshot.

    Instantiated once at startup and called by the diagnostics endpoint.
    """

    async def report(
        self,
        *,
        pool=None,
        include_db_metrics: bool = False,
    ) -> DiagnosticsReport:
        from datetime import datetime, timezone

        from app.core.ai.registry.registry import platform_registry
        from app.core.ai.models.catalog import catalog
        from app.core.ai.telemetry.service import telemetry
        from app.core.ai.events.bus import bus
        from app.ai.cache import cache

        # Provider status
        provider_statuses = []
        for pid, info in platform_registry.health().items():
            caps = platform_registry.capabilities(pid)
            provider_statuses.append(ProviderStatus(
                provider_id=pid,
                available=info["available"],
                default_model=info.get("default_model"),
                models=caps.get("models", []),
                supports_tools=caps.get("supports_tools", False),
                supports_vision=caps.get("supports_vision", False),
            ))

        # Available models (available providers only)
        available_pids = platform_registry.available()
        available_models = [
            {
                "id":             m.id,
                "provider":       m.provider_id,
                "display_name":   m.display_name,
                "context_window": m.context_window,
                "latency_tier":   m.latency_tier,
                "supports_tools": m.supports_tools,
                "reasoning":      m.reasoning,
                "input_cost_m":   m.input_cost_m,
                "output_cost_m":  m.output_cost_m,
            }
            for m in catalog.all()
            if m.provider_id in available_pids and not m.deprecated
        ]

        summary = telemetry.summary()

        # DB metrics (optional, skipped if no pool or too slow)
        db_metrics: dict = {}
        if include_db_metrics and pool:
            try:
                from app.ai import cost_tracker
                db_metrics = await cost_tracker.totals(pool=pool)
            except Exception:
                pass

        return DiagnosticsReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_seconds=round(time.monotonic() - _START_TIME, 1),
            providers=provider_statuses,
            available_models=available_models,
            metrics={
                "total_requests":    summary.total_requests,
                "total_input_tokens": summary.total_input_tokens,
                "total_output_tokens": summary.total_output_tokens,
                "total_cost_usd":    round(summary.total_cost_usd, 6),
                "avg_latency_ms":    summary.avg_latency_ms,
                "cache_hit_ratio":   summary.cache_hit_ratio,
                "total_tool_calls":  summary.total_tool_calls,
                "active_streams":    summary.active_streams,
                "by_provider":       summary.by_provider,
                "db":                db_metrics,
            },
            cache_stats=cache.stats(),
            tool_stats=telemetry.tool_stats(),
            event_handlers=bus.all_handlers(),
            memory_stats={},   # populated if MemoryManager is wired in
        )


# Module-level singleton
diagnostics = AIDiagnostics()
