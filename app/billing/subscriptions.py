"""
Org-scoped Stripe subscriptions.

Separate from the legacy email-scoped `subscriptions` table used by
app/routers/subscriptions.py (the original flat $/mo trial gate) — that
system is untouched for backward compatibility. This table links a
Stripe subscription to an organization and is the source of truth the
webhook writes to before syncing `organizations.plan`.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

ORG_SUBSCRIPTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS org_subscriptions (
    organization_id         UUID PRIMARY KEY,
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT UNIQUE,
    plan_id                 VARCHAR(20) NOT NULL DEFAULT 'free',
    status                  VARCHAR(20) NOT NULL DEFAULT 'inactive',
    current_period_end      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_org_subs_customer ON org_subscriptions(stripe_customer_id);
"""


async def init_org_subscriptions_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(ORG_SUBSCRIPTIONS_SCHEMA)
    log.info("org_subscriptions schema initialised")


class OrgSubscriptionService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get(self, org_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM org_subscriptions WHERE organization_id=$1",
                uuid.UUID(org_id),
            )
        return dict(row) if row else None

    async def get_stripe_customer_id(self, org_id: str) -> Optional[str]:
        row = await self.get(org_id)
        return row["stripe_customer_id"] if row else None

    async def upsert_customer(self, org_id: str, stripe_customer_id: str) -> None:
        """Record a Stripe customer id for an org before checkout (idempotent)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO org_subscriptions (organization_id, stripe_customer_id)
                   VALUES ($1, $2)
                   ON CONFLICT (organization_id) DO UPDATE
                   SET stripe_customer_id = EXCLUDED.stripe_customer_id, updated_at = NOW()""",
                uuid.UUID(org_id), stripe_customer_id,
            )

    async def apply_webhook_update(
        self, *, organization_id: str, stripe_customer_id: str | None,
        stripe_subscription_id: str | None, plan_id: str, status: str,
        current_period_end,
    ) -> None:
        """Upsert the subscription row AND sync organizations.plan — one
        transaction so the two never drift apart."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO org_subscriptions
                         (organization_id, stripe_customer_id, stripe_subscription_id,
                          plan_id, status, current_period_end)
                       VALUES ($1,$2,$3,$4,$5,$6)
                       ON CONFLICT (organization_id) DO UPDATE SET
                         stripe_customer_id     = COALESCE(EXCLUDED.stripe_customer_id, org_subscriptions.stripe_customer_id),
                         stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id, org_subscriptions.stripe_subscription_id),
                         plan_id                = EXCLUDED.plan_id,
                         status                 = EXCLUDED.status,
                         current_period_end     = EXCLUDED.current_period_end,
                         updated_at              = NOW()""",
                    uuid.UUID(organization_id), stripe_customer_id, stripe_subscription_id,
                    plan_id, status, current_period_end,
                )
                # An inactive/cancelled subscription drops the org back to free;
                # an active one promotes it to the purchased tier.
                effective_plan = plan_id if status == "active" else "free"
                await conn.execute(
                    "UPDATE organizations SET plan=$2, updated_at=NOW() WHERE id=$1",
                    uuid.UUID(organization_id), effective_plan,
                )

    async def find_org_by_subscription_id(self, stripe_subscription_id: str) -> Optional[str]:
        async with self._pool.acquire() as conn:
            org_id = await conn.fetchval(
                "SELECT organization_id FROM org_subscriptions WHERE stripe_subscription_id=$1",
                stripe_subscription_id,
            )
        return str(org_id) if org_id else None


_service: Optional[OrgSubscriptionService] = None


def get_org_subscription_service(pool: asyncpg.Pool | None = None) -> OrgSubscriptionService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = OrgSubscriptionService(pool)
    return _service
