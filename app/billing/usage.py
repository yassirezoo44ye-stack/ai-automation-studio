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

from app.billing.plans import METRICS, get_plan

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


class QuotaExceeded(Exception):
    def __init__(self, metric: str, used: int, limit: int):
        super().__init__(f"quota exceeded for {metric}: {used}/{limit}")
        self.metric, self.used, self.limit = metric, used, limit


def _current_period() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


async def init_usage_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(USAGE_SCHEMA)
    log.info("usage schema initialised")


class UsageService:
    """Metered-usage bookkeeping against PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def record(
        self, org_id: str, metric: str, amount: int = 1, *,
        ref_type: str | None = None, ref_id: str | None = None,
    ) -> int:
        """Add `amount` to the metric for the current period; returns new total."""
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric!r}")
        from app.core.db import acquire_scoped
        period = _current_period()
        async with acquire_scoped(org_id) as conn:
            total = await conn.fetchval(
                """INSERT INTO usage_records (organization_id, metric, period, amount)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (organization_id, metric, period)
                   DO UPDATE SET amount = usage_records.amount + EXCLUDED.amount,
                                 updated_at = NOW()
                   RETURNING amount""",
                uuid.UUID(org_id), metric, period, amount,
            )
            if ref_type or ref_id:
                await conn.execute(
                    "INSERT INTO usage_events (organization_id, metric, amount, ref_type, ref_id) "
                    "VALUES ($1,$2,$3,$4,$5)",
                    uuid.UUID(org_id), metric, amount, ref_type, ref_id,
                )
        return int(total)

    async def get_usage(self, org_id: str, period: str | None = None) -> dict[str, int]:
        from app.core.db import acquire_scoped
        period = period or _current_period()
        async with acquire_scoped(org_id) as conn:
            rows = await conn.fetch(
                "SELECT metric, amount FROM usage_records "
                "WHERE organization_id=$1 AND period=$2",
                uuid.UUID(org_id), period,
            )
        usage = {m: 0 for m in METRICS}
        usage.update({r["metric"]: int(r["amount"]) for r in rows})
        return usage

    async def get_limit(self, org_id: str, metric: str) -> int:
        """Effective limit: per-org override wins over the plan default."""
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            override = await conn.fetchval(
                "SELECT override_limit FROM usage_limits "
                "WHERE organization_id=$1 AND metric=$2",
                uuid.UUID(org_id), metric,
            )
            if override is not None:
                return int(override)
            plan_id = await conn.fetchval(
                "SELECT plan FROM organizations WHERE id=$1", uuid.UUID(org_id)
            )
        return get_plan(plan_id or "free").limits.get(metric, 0)

    async def check_quota(self, org_id: str, metric: str, amount: int = 1) -> None:
        """Raise QuotaExceeded if recording `amount` would breach the limit."""
        from app.core.db import acquire_scoped
        limit = await self.get_limit(org_id, metric)
        if limit < 0:
            return  # unlimited
        period = _current_period()
        async with acquire_scoped(org_id) as conn:
            used = await conn.fetchval(
                "SELECT amount FROM usage_records "
                "WHERE organization_id=$1 AND metric=$2 AND period=$3",
                uuid.UUID(org_id), metric, period,
            ) or 0
        if used + amount > limit:
            raise QuotaExceeded(metric, int(used), limit)

    async def set_override(self, org_id: str, metric: str, limit: int) -> None:
        """Set a per-organization limit override (admin/enterprise negotiation)."""
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric!r}")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO usage_limits (organization_id, metric, override_limit)
                   VALUES ($1,$2,$3)
                   ON CONFLICT (organization_id, metric)
                   DO UPDATE SET override_limit = EXCLUDED.override_limit""",
                uuid.UUID(org_id), metric, limit,
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
