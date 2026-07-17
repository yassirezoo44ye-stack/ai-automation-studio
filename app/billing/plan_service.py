"""
PlanService — DB-backed subscription plan catalog with an in-process cache.

Plans move from a hardcoded Python dict to a `subscription_plans` table so
they're admin-editable (POST /api/admin/plans/{id}) without a deploy. Reads
are served from an in-process cache (mirrors TenancyService._perm_cache) —
plans change rarely, so there's no TTL, only explicit invalidation on write.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import asyncpg

from app.billing.plans import Plan, _SEED_PLANS

log = logging.getLogger(__name__)

SUBSCRIPTION_PLANS_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscription_plans (
    id                   VARCHAR(20)  PRIMARY KEY,
    name                 VARCHAR(60)  NOT NULL,
    price_monthly_cents  BIGINT       NOT NULL DEFAULT 0,
    limits               JSONB        NOT NULL DEFAULT '{}',
    features             TEXT[]       NOT NULL DEFAULT '{}',
    trial_days           INTEGER      NOT NULL DEFAULT 0,
    max_agents           INTEGER      NOT NULL DEFAULT -1,
    max_workflows         INTEGER      NOT NULL DEFAULT -1,
    stripe_price_id      TEXT,
    is_purchasable       BOOLEAN      NOT NULL DEFAULT true,
    sort_order           INTEGER      NOT NULL DEFAULT 0,
    active               BOOLEAN      NOT NULL DEFAULT true,
    updated_by           UUID,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
"""


def _row_to_plan(row: asyncpg.Record) -> Plan:
    limits = row["limits"]
    if isinstance(limits, str):
        limits = json.loads(limits)
    return Plan(
        id=row["id"], name=row["name"],
        price_monthly_usd=row["price_monthly_cents"] / 100,
        limits={k: int(v) for k, v in dict(limits or {}).items()},
        features=tuple(row["features"] or ()),
        trial_days=row["trial_days"],
        max_agents=row["max_agents"], max_workflows=row["max_workflows"],
        stripe_price_id=row["stripe_price_id"],
        is_purchasable=row["is_purchasable"], active=row["active"],
    )


async def init_subscription_plans_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(SUBSCRIPTION_PLANS_SCHEMA)
    for i, plan in enumerate(_SEED_PLANS.values()):
        await conn.execute(
            """INSERT INTO subscription_plans
                 (id, name, price_monthly_cents, limits, features, trial_days,
                  max_agents, max_workflows, is_purchasable, sort_order)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (id) DO NOTHING""",
            plan.id, plan.name, round(plan.price_monthly_usd * 100),
            json.dumps(plan.limits), list(plan.features), plan.trial_days,
            plan.max_agents, plan.max_workflows, plan.is_purchasable, i,
        )
    log.info("subscription_plans schema initialised")


class PlanService:
    """Cached DB-backed plan catalog."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        self._cache: dict[str, Plan] = {}

    async def refresh_cache(self) -> None:
        # Caches EVERY plan, active or not — an org can already be assigned
        # a plan_id that an admin later deactivates (update_plan(active=
        # False)), and get_plan() must keep returning that plan's real
        # limits for it, not silently substitute the free tier's limits.
        # list_plans() below is what filters to active-only for display.
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM subscription_plans ORDER BY sort_order")
        self._cache = {r["id"]: _row_to_plan(r) for r in rows}

    async def list_plans(self) -> list[Plan]:
        if not self._cache:
            await self.refresh_cache()
        return [p for p in self._cache.values() if p.active]

    async def get_plan(self, plan_id: str) -> Plan:
        if not self._cache:
            await self.refresh_cache()
        plan = self._cache.get(plan_id)
        if plan is not None:
            return plan
        log.warning("unknown plan_id %r requested — falling back to free tier", plan_id)
        return self._cache.get("free") or _SEED_PLANS["free"]

    async def update_plan(self, plan_id: str, *, actor_id: Optional[str] = None, **fields: Any) -> Plan:
        """Admin edit — updates only the columns present in `fields`.
        Valid keys: name, price_monthly_usd, limits, features, trial_days,
        max_agents, max_workflows, stripe_price_id, is_purchasable, active."""
        import uuid as _uuid

        sets, params = [], []
        col_map = {
            "name": "name", "trial_days": "trial_days",
            "max_agents": "max_agents", "max_workflows": "max_workflows",
            "stripe_price_id": "stripe_price_id", "is_purchasable": "is_purchasable",
            "active": "active",
        }
        for key, col in col_map.items():
            if key in fields:
                params.append(fields[key])
                sets.append(f"{col}=${len(params)}")
        if "price_monthly_usd" in fields:
            params.append(round(fields["price_monthly_usd"] * 100))
            sets.append(f"price_monthly_cents=${len(params)}")
        if "limits" in fields:
            params.append(json.dumps(fields["limits"]))
            sets.append(f"limits=${len(params)}::jsonb")
        if "features" in fields:
            params.append(list(fields["features"]))
            sets.append(f"features=${len(params)}")
        if not sets:
            return await self.get_plan(plan_id)
        params.append(_uuid.UUID(actor_id) if actor_id else None)
        sets.append(f"updated_by=${len(params)}")
        sets.append("updated_at=NOW()")
        params.append(plan_id)
        row = await self._pool.fetchrow(
            f"UPDATE subscription_plans SET {', '.join(sets)} WHERE id=${len(params)} RETURNING *",
            *params,
        )
        if row is None:
            raise ValueError(f"unknown plan {plan_id!r}")
        await self.refresh_cache()
        # Other instances hold their own in-process plan cache — tell them
        # to refresh too (no-op extra hop on a single instance).
        from app.core.cache import invalidate
        await invalidate("plans:catalog")
        return _row_to_plan(row)


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[PlanService] = None


def get_plan_service(pool: asyncpg.Pool | None = None) -> PlanService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = PlanService(pool)
    return _service
