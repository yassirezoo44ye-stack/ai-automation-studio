"""
Observability bridges — subscribe to events that already exist and feed the
shared MetricsRegistry, instead of teaching each domain to maintain its own
metrics store. Each wire_*() function is idempotent (safe to call more than
once) and should be called exactly once at app startup.

MetricsRegistry has no per-label cardinality (each metric name is one
counter/gauge, not a {label=value} matrix — see app/core/observability/
metrics.py's Counter/Gauge dataclasses), so these bridges only feed
aggregate totals. Per-provider/per-agent breakdowns already exist in their
own domain services (TelemetryService.summary()'s by_provider, for
example) and are intentionally not duplicated here.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_wired: dict[str, bool] = {}


def wire_ai_metrics() -> None:
    """AI request/token/cost/latency/failure-rate — subscribes to the same
    AI event bus TelemetryService already subscribes to."""
    if _wired.get("ai"):
        return
    _wired["ai"] = True

    from app.core.ai.events.bus import bus
    from app.core.ai.events.events import (
        PromptCompleted, ProviderFailed, StreamStarted, StreamEnded,
    )
    from app.core.observability.metrics import get_metrics

    async def _on_prompt_completed(event: PromptCompleted) -> None:
        m = get_metrics()
        m.counter("ai_requests_total",       "Total completed AI requests").inc()
        m.counter("ai_tokens_input_total",   "Total input tokens consumed").inc(event.input_tokens)
        m.counter("ai_tokens_output_total",  "Total output tokens generated").inc(event.output_tokens)
        m.counter("ai_cost_usd_total",       "Total AI spend in USD").inc(event.cost_usd)
        if event.latency_ms > 0:
            m.histogram("ai_request_latency_ms", "AI request latency in ms").observe(event.latency_ms)

    async def _on_provider_failed(event: ProviderFailed) -> None:
        get_metrics().counter("ai_provider_failures_total", "Total AI provider call failures").inc()

    async def _on_stream_started(event: StreamStarted) -> None:
        get_metrics().gauge("ai_active_streams", "Currently open AI streaming responses").inc()

    async def _on_stream_ended(event: StreamEnded) -> None:
        get_metrics().gauge("ai_active_streams", "Currently open AI streaming responses").dec()

    bus.subscribe(PromptCompleted, _on_prompt_completed)
    bus.subscribe(ProviderFailed,  _on_provider_failed)
    bus.subscribe(StreamStarted,   _on_stream_started)
    bus.subscribe(StreamEnded,     _on_stream_ended)


def wire_workflow_metrics() -> None:
    """Workflow run counts — subscribes to the tenancy event bus's
    workflow.* events (already emitted by WorkflowEngine.execute())."""
    if _wired.get("workflow"):
        return
    _wired["workflow"] = True

    from app.core.events import get_event_bus
    from app.core.observability.metrics import get_metrics

    async def _on_workflow_event(event) -> None:
        m = get_metrics()
        if event.type == "workflow.started":
            m.counter("workflow_runs_total",  "Total workflow runs started").inc()
            m.gauge("workflow_active_runs",   "Currently executing workflow runs").inc()
        elif event.type == "workflow.completed":
            m.counter("workflow_runs_success", "Total workflow runs completed successfully").inc()
            m.gauge("workflow_active_runs",    "Currently executing workflow runs").dec()
        elif event.type == "workflow.failed":
            m.counter("workflow_runs_failed", "Total workflow runs that failed").inc()
            m.gauge("workflow_active_runs",   "Currently executing workflow runs").dec()

    get_event_bus().subscribe("workflow.*", _on_workflow_event)


def wire_marketplace_metrics() -> None:
    """Marketplace install/publish counts — subscribes to the tenancy event
    bus's marketplace.* events (already emitted by InstallationPipeline)."""
    if _wired.get("marketplace"):
        return
    _wired["marketplace"] = True

    from app.core.events import get_event_bus
    from app.core.observability.metrics import get_metrics

    async def _on_marketplace_event(event) -> None:
        m = get_metrics()
        if event.type == "marketplace.installed":
            m.counter("marketplace_installs_total", "Total marketplace listing installs").inc()
        elif event.type == "marketplace.published":
            m.counter("marketplace_publishes_total", "Total marketplace listing publishes").inc()

    get_event_bus().subscribe("marketplace.*", _on_marketplace_event)


def wire_billing_metrics() -> None:
    """Billing event counts — subscribes to the tenancy event bus's
    billing.updated events (already emitted by the webhook handler)."""
    if _wired.get("billing"):
        return
    _wired["billing"] = True

    from app.core.events import get_event_bus
    from app.core.observability.metrics import get_metrics

    async def _on_billing_event(event) -> None:
        get_metrics().counter("billing_events_total", "Total billing.updated events processed").inc()

    get_event_bus().subscribe("billing.*", _on_billing_event)


def wire_all() -> None:
    """Call once from app startup — wires every bridge."""
    wire_ai_metrics()
    wire_workflow_metrics()
    wire_marketplace_metrics()
    wire_billing_metrics()
