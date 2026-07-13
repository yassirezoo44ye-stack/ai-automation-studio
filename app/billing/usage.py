"""
UsageService — metered usage recording and quota enforcement.

Records are aggregated per (organization, metric, period). The current
billing period is the calendar month (UTC). Quota checks compare the
period's running total against the organization's plan limit.

Enforcement is designed to be called on the hot path, so `check_quota`
does a single indexed SELECT and `record` a single UPSERT.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from app.billing.plans import METRICS
from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    metric          VARCHAR(40) NOT NULL,
    period          VARCHAR(7)  NOT NULL,          -- 'YYYY-MM'
    amount          BIGINT      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, metric, period)
);
CREATE INDEX IF NOT EXISTS idx_usage_org_period ON usage_records(organization_id, period);

CREATE TABLE IF NOT EXISTS usage_limits (
    organization_id UUID NOT NULL,
    metric          VARCHAR(40) NOT NULL,
    override_limit  BIGINT NOT NULL,               -- -1 = unlimited
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, metric)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    metric          VARCHAR(40) NOT NULL,
    amount          BIGINT NOT NULL,
    ref_type        VARCHAR(40),                   -- workflow / agent / project / user
    ref_id          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_usage_events_org ON usage_events(organization_id, created_at DESC);
"""

# AI Routing consolidation — budget granularity below organization. Scope
# columns default to '' (empty string), NOT NULL: unlike NULL, '' compares
# equal to itself in a UNIQUE/PRIMARY KEY constraint, so upserts (ON
# CONFLICT) keep matching correctly. '' in all three columns means
# "organization-level" — the exact rows every pre-existing call already
# writes, 100% unchanged in shape and behavior.
_SCOPE_COLUMNS_SCHEMA = """
ALTER TABLE usage_records ADD COLUMN IF NOT EXISTS project_id  TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_records ADD COLUMN IF NOT EXISTS workflow_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_records ADD COLUMN IF NOT EXISTS agent_id    TEXT NOT NULL DEFAULT '';

DO $$
BEGIN
    ALTER TABLE usage_records DROP CONSTRAINT usage_records_organization_id_metric_period_key;
    ALTER TABLE usage_records ADD CONSTRAINT usage_records_scope_key
        UNIQUE (organization_id, metric, period, project_id, workflow_id, agent_id);
EXCEPTION WHEN undefined_object THEN
    NULL;  -- old constraint already replaced by a prior boot (idempotent re-run)
END $$;

ALTER TABLE usage_limits ADD COLUMN IF NOT EXISTS project_id  TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_limits ADD COLUMN IF NOT EXISTS workflow_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_limits ADD COLUMN IF NOT EXISTS agent_id    TEXT NOT NULL DEFAULT '';

DO $$
BEGIN
    ALTER TABLE usage_limits DROP CONSTRAINT usage_limits_pkey;
    ALTER TABLE usage_limits ADD CONSTRAINT usage_limits_scope_pkey
        PRIMARY KEY (organization_id, metric, project_id, workflow_id, agent_id);
EXCEPTION WHEN undefined_object THEN
    NULL;
END $$;
"""


class QuotaExceeded(Exception):
    def __init__(self, metric: str, used: int, limit: int):
        super().__init__(f"quota exceeded for {metric}: {used}/{limit}")
        self.metric, self.used, self.limit = metric, used, limit


def _current_period() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


async def init_usage_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(USAGE_SCHEMA)
    await conn.execute(_SCOPE_COLUMNS_SCHEMA)
    log.info("usage schema initialised")


class UsageService:
    """Metered-usage bookkeeping against PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def record(
        self, org_id: str, metric: str, amount: int = 1, *,
        ref_type: str | None = None, ref_id: str | None = None,
        project_id: str = "", workflow_id: str = "", agent_id: str = "",
    ) -> int:
        """Add `amount` to the metric for the current period; returns new
        org-level total. When project_id/workflow_id/agent_id is given, ALSO
        accumulates a finer-scoped row (additive, not a replacement) — a
        workflow's spend counts toward both the workflow's own ceiling and
        the org's overall ceiling."""
        tracer = get_tracer()
        with tracer.start_span("usage.record", service="billing") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("organization_id", org_id)
            span.set_tag("metric", metric)

            if metric not in METRICS:
                raise ValueError(f"unknown metric {metric!r}")
            from app.core.db import acquire_scoped
            period = _current_period()
            async with acquire_scoped(org_id) as conn:
                total = await conn.fetchval(
                    """INSERT INTO usage_records (organization_id, metric, period, amount, project_id, workflow_id, agent_id)
                       VALUES ($1,$2,$3,$4,'','','')
                       ON CONFLICT (organization_id, metric, period, project_id, workflow_id, agent_id)
                       DO UPDATE SET amount = usage_records.amount + EXCLUDED.amount,
                                     updated_at = NOW()
                       RETURNING amount""",
                    uuid.UUID(org_id), metric, period, amount,
                )
                if project_id or workflow_id or agent_id:
                    await conn.execute(
                        """INSERT INTO usage_records (organization_id, metric, period, amount, project_id, workflow_id, agent_id)
                           VALUES ($1,$2,$3,$4,$5,$6,$7)
                           ON CONFLICT (organization_id, metric, period, project_id, workflow_id, agent_id)
                           DO UPDATE SET amount = usage_records.amount + EXCLUDED.amount,
                                         updated_at = NOW()""",
                        uuid.UUID(org_id), metric, period, amount, project_id, workflow_id, agent_id,
                    )
                if ref_type or ref_id:
                    await conn.execute(
                        "INSERT INTO usage_events (organization_id, metric, amount, ref_type, ref_id) "
                        "VALUES ($1,$2,$3,$4,$5)",
                        uuid.UUID(org_id), metric, amount, ref_type, ref_id,
                    )
            return int(total)

    async def set_metric(self, org_id: str, metric: str, amount: int) -> int:
        """Overwrite (not add to) the metric for the current period — for
        gauge-style metrics reconciled periodically from live state (e.g.
        active_users), as opposed to `record`'s counter/increment semantics."""
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric!r}")
        from app.core.db import acquire_scoped
        period = _current_period()
        async with acquire_scoped(org_id) as conn:
            total = await conn.fetchval(
                """INSERT INTO usage_records (organization_id, metric, period, amount)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (organization_id, metric, period)
                   DO UPDATE SET amount = EXCLUDED.amount, updated_at = NOW()
                   RETURNING amount""",
                uuid.UUID(org_id), metric, period, amount,
            )
        return int(total)

    async def get_usage(self, org_id: str, period: str | None = None, *,
                        project_id: str = "", workflow_id: str = "", agent_id: str = "") -> dict[str, int]:
        from app.core.db import acquire_scoped
        period = period or _current_period()
        async with acquire_scoped(org_id) as conn:
            rows = await conn.fetch(
                "SELECT metric, amount FROM usage_records "
                "WHERE organization_id=$1 AND period=$2 "
                "AND project_id=$3 AND workflow_id=$4 AND agent_id=$5",
                uuid.UUID(org_id), period, project_id, workflow_id, agent_id,
            )
        usage = {m: 0 for m in METRICS}
        usage.update({r["metric"]: int(r["amount"]) for r in rows})
        return usage

    async def get_limit(self, org_id: str, metric: str, *,
                        project_id: str = "", workflow_id: str = "", agent_id: str = "") -> int:
        """Effective limit at the given scope.

        Org-level (project_id=workflow_id=agent_id=""): per-org override
        wins over the plan default — unchanged existing behavior.
        Finer scope: only an explicit set_override() at that exact scope
        applies; with none set, the scope is unlimited (-1) — the org-level
        ceiling, checked separately, is what actually bounds it. A
        project/workflow/agent limit is an additional, tighter ceiling an
        admin opts into, not a replacement for the plan's org limit.
        """
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            override = await conn.fetchval(
                "SELECT override_limit FROM usage_limits "
                "WHERE organization_id=$1 AND metric=$2 "
                "AND project_id=$3 AND workflow_id=$4 AND agent_id=$5",
                uuid.UUID(org_id), metric, project_id, workflow_id, agent_id,
            )
            if override is not None:
                return int(override)
            if project_id or workflow_id or agent_id:
                return -1  # no scoped override set — unlimited at this granularity
            plan_id = await conn.fetchval(
                "SELECT plan FROM organizations WHERE id=$1", uuid.UUID(org_id)
            )
        from app.billing.plan_service import get_plan_service
        plan = await get_plan_service().get_plan(plan_id or "free")
        return plan.limits.get(metric, 0)

    async def check_quota(self, org_id: str, metric: str, amount: int = 1, *,
                          project_id: str = "", workflow_id: str = "", agent_id: str = "") -> None:
        """Raise QuotaExceeded if recording `amount` would breach the limit.

        Always checks the org-level ceiling first (unchanged behavior for
        every existing caller). When project_id/workflow_id/agent_id is
        given, ALSO checks that finer scope's own ceiling — a workflow
        budget doesn't replace the org budget, it's an additional, tighter
        one; whichever is hit first raises.
        """
        tracer = get_tracer()
        with tracer.start_span("usage.check_quota", service="billing") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("organization_id", org_id)
            span.set_tag("metric", metric)
            try:
                await self._check_quota_scope(org_id, metric, amount, "", "", "")
                if project_id or workflow_id or agent_id:
                    await self._check_quota_scope(org_id, metric, amount, project_id, workflow_id, agent_id)
            except QuotaExceeded as exc:
                span.set_tag("error", str(exc))
                raise

    async def _check_quota_scope(
        self, org_id: str, metric: str, amount: int,
        project_id: str, workflow_id: str, agent_id: str,
    ) -> None:
        from app.core.db import acquire_scoped
        limit = await self.get_limit(org_id, metric, project_id=project_id,
                                     workflow_id=workflow_id, agent_id=agent_id)
        if limit < 0:
            return  # unlimited
        period = _current_period()
        async with acquire_scoped(org_id) as conn:
            used = await conn.fetchval(
                "SELECT amount FROM usage_records "
                "WHERE organization_id=$1 AND metric=$2 AND period=$3 "
                "AND project_id=$4 AND workflow_id=$5 AND agent_id=$6",
                uuid.UUID(org_id), metric, period, project_id, workflow_id, agent_id,
            ) or 0
        if used + amount > limit:
            raise QuotaExceeded(metric, int(used), limit)

    async def set_override(self, org_id: str, metric: str, limit: int, *,
                           project_id: str = "", workflow_id: str = "", agent_id: str = "") -> None:
        """Set a limit override at the given scope (org-level by default;
        pass project_id/workflow_id/agent_id for a finer-grained ceiling)."""
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric!r}")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO usage_limits (organization_id, metric, override_limit, project_id, workflow_id, agent_id)
                   VALUES ($1,$2,$3,$4,$5,$6)
                   ON CONFLICT (organization_id, metric, project_id, workflow_id, agent_id)
                   DO UPDATE SET override_limit = EXCLUDED.override_limit""",
                uuid.UUID(org_id), metric, limit, project_id, workflow_id, agent_id,
            )

    async def summary(self, org_id: str) -> dict[str, Any]:
        """Usage + limits + percentage for dashboard display."""
        usage = await self.get_usage(org_id)
        out: dict[str, Any] = {"period": _current_period(), "metrics": {}}
        for metric in METRICS:
            limit = await self.get_limit(org_id, metric)
            used = usage.get(metric, 0)
            out["metrics"][metric] = {
                "used": used,
                "limit": limit,
                "pct": None if limit <= 0 else round(min(used / limit, 1.0) * 100, 1),
            }
        return out


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[UsageService] = None


def get_usage_service(pool: asyncpg.Pool | None = None) -> UsageService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = UsageService(pool)
    return _service
