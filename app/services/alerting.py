"""
AlertingService — evaluates configurable threshold rules against
MetricsRegistry/HealthRegistry state and notifies via email/webhook.

Rules live in the alert_rules table (admin-configurable — adding a rule
never requires a code change). Firing/resolving is deduplicated via
alert_history: a rule with an unresolved alert_history row is already
"open" and won't re-notify every tick; when its condition clears, the
open row is closed. Notification delivery (email via app.core.email,
webhook via httpx) is always wrapped in try/except — a delivery failure
must never interrupt the tick loop or, by extension, production traffic.
"""
from __future__ import annotations

import logging

from app.services.registry import BaseService

log = logging.getLogger(__name__)

ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_rules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name                VARCHAR(100) NOT NULL,
    rule_type           VARCHAR(20) NOT NULL CHECK (rule_type IN ('gauge_above','counter_rate_above','health_unhealthy')),
    target              VARCHAR(100) NOT NULL,
    threshold           DOUBLE PRECISION,
    enabled             BOOLEAN NOT NULL DEFAULT true,
    notify_email        TEXT,
    notify_webhook_url  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON alert_rules(enabled);

CREATE TABLE IF NOT EXISTS alert_history (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id     UUID NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
    fired_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    value       DOUBLE PRECISION,
    message     TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_history_rule_open ON alert_history(rule_id) WHERE resolved_at IS NULL;
"""

# Platform-wide (organization_id NULL) starter rules covering the metrics
# and health probes this phase actually wired up. The rule engine itself
# is generic (gauge_above / counter_rate_above / health_unhealthy) — an
# admin can add rules for anything else in MetricsRegistry/HealthRegistry
# without a code change, this seed list just isn't exhaustive of every
# category the directive named (e.g. queue backlog, auth failure rate)
# since those don't have a wired metric yet.
_DEFAULT_RULES = [
    # (name, rule_type, target, threshold)
    ("High HTTP error rate",       "counter_rate_above", "http_errors_total",         5.0),
    ("High CPU usage",             "gauge_above",         "system_cpu_percent",        90.0),
    ("High disk usage",            "gauge_above",         "system_disk_used_percent",  90.0),
    ("AI provider unhealthy",      "health_unhealthy",    "ai_providers",              None),
    ("Database unhealthy",         "health_unhealthy",    "database",                  None),
    ("Elevated workflow failures", "counter_rate_above",  "workflow_runs_failed",      5.0),
]


async def init_alert_schema(conn) -> None:
    await conn.execute(ALERT_SCHEMA)
    existing = await conn.fetchval("SELECT count(*) FROM alert_rules")
    if not existing:
        for name, rule_type, target, threshold in _DEFAULT_RULES:
            await conn.execute(
                "INSERT INTO alert_rules (name, rule_type, target, threshold) VALUES ($1,$2,$3,$4)",
                name, rule_type, target, threshold,
            )
        log.info("alerting: seeded %d default rules", len(_DEFAULT_RULES))


class AlertingService(BaseService):
    name         = "alerting"
    description  = "Evaluates configurable threshold rules against metrics/health state (45s interval)"
    interval_s   = 45.0
    auto_restart = True

    def __init__(self) -> None:
        super().__init__()
        self._prev_counters: dict[str, float] = {}

    async def tick(self) -> None:
        from app.core.db import get_pool
        from app.core.observability.metrics import get_metrics
        pool = get_pool()
        if pool is None:
            return
        # One snapshot per tick, shared by every gauge_above/counter_rate_above
        # rule this tick evaluates — MetricsRegistry.snapshot() takes a lock
        # and copies every counter/gauge/histogram, so calling it once per
        # rule instead of once per tick is redundant, lock-contending work
        # for data that can't change within the same tick.
        snapshot = get_metrics().snapshot()
        async with pool.acquire() as conn:
            rules = await conn.fetch("SELECT * FROM alert_rules WHERE enabled = true")
            for rule in rules:
                try:
                    await self._evaluate(conn, rule, snapshot)
                except Exception:
                    log.warning("alert rule '%s' evaluation failed", rule["name"], exc_info=True)

    async def _evaluate(self, conn, rule, snapshot: dict) -> None:
        from app.core.observability.health import get_health_registry, HealthStatus

        breached = False
        value: float | None = None
        message = ""

        if rule["rule_type"] == "gauge_above":
            value = snapshot["gauges"].get(rule["target"])
            if value is not None and rule["threshold"] is not None and value > rule["threshold"]:
                breached = True
                message  = f"{rule['target']} = {value} > {rule['threshold']}"

        elif rule["rule_type"] == "counter_rate_above":
            # Keyed by rule id (not target alone) — two enabled rules
            # watching the same counter with different thresholds must not
            # share one baseline, or the second rule evaluated in a tick
            # would see delta=0 since the first rule already advanced the
            # baseline to `current`.
            current = snapshot["counters"].get(rule["target"], 0.0)
            prev    = self._prev_counters.get(rule["id"], current)
            delta   = current - prev
            self._prev_counters[rule["id"]] = current
            value = delta
            if rule["threshold"] is not None and delta > rule["threshold"]:
                breached = True
                message  = (f"{rule['target']} increased by {delta:.0f} in the last "
                            f"{self.interval_s:.0f}s (> {rule['threshold']})")

        elif rule["rule_type"] == "health_unhealthy":
            result = await get_health_registry().check(rule["target"])
            if result is not None and result.status != HealthStatus.HEALTHY:
                breached = True
                value    = 1.0
                message  = f"{rule['target']} is {result.status.value}: {result.message}"

        open_alert = await conn.fetchrow(
            "SELECT id FROM alert_history WHERE rule_id=$1 AND resolved_at IS NULL "
            "ORDER BY fired_at DESC LIMIT 1",
            rule["id"],
        )

        if breached and open_alert is None:
            await conn.execute(
                "INSERT INTO alert_history (rule_id, value, message) VALUES ($1,$2,$3)",
                rule["id"], value, message,
            )
            log.warning("ALERT FIRED: %s — %s", rule["name"], message)
            await self._notify(rule, message)
        elif not breached and open_alert is not None:
            await conn.execute(
                "UPDATE alert_history SET resolved_at = NOW() WHERE id=$1", open_alert["id"],
            )
            log.info("ALERT RESOLVED: %s", rule["name"])

    async def _notify(self, rule, message: str) -> None:
        """Delivery is always best-effort — a notification failure must
        never propagate into the tick loop or affect production traffic."""
        if rule["notify_email"]:
            try:
                from app.core.email import send_email
                await send_email(rule["notify_email"], f"[Axon Alert] {rule['name']}", f"<p>{message}</p>")
            except Exception:
                log.warning("alert email delivery failed for rule %s", rule["name"], exc_info=True)

        if rule["notify_webhook_url"]:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(rule["notify_webhook_url"], json={
                        "rule": rule["name"], "message": message,
                    })
            except Exception:
                log.warning("alert webhook delivery failed for rule %s", rule["name"], exc_info=True)
