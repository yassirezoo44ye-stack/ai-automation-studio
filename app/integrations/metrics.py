"""
Thin helpers over the EXISTING metrics registry
(app/core/observability/metrics.py) — no separate metrics store.
"""
from __future__ import annotations


def record_sync(*, succeeded: bool) -> None:
    from app.core.observability.metrics import get_metrics
    m = get_metrics()
    m.counter("integration_syncs_total", "Total integration sync runs").inc()
    if not succeeded:
        m.counter("integration_sync_failures_total", "Total failed integration sync runs").inc()


def record_webhook_received() -> None:
    from app.core.observability.metrics import get_metrics
    get_metrics().counter("integration_webhooks_total", "Total inbound integration webhooks received").inc()


def record_connection_change(*, connected: bool) -> None:
    from app.core.observability.metrics import get_metrics
    gauge = get_metrics().gauge("integration_active_connections", "Currently connected integrations")
    gauge.inc() if connected else gauge.dec()
