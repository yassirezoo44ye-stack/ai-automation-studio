"""
payment_methods — a display cache synced from Stripe, never a source of
truth for card data. Only non-sensitive display fields (brand/last4/exp)
are ever stored; adding or changing a card happens exclusively through the
Stripe Customer/Billing Portal (app/billing/portal.py).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

PAYMENT_METHODS_SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_methods (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    stripe_payment_method_id  TEXT UNIQUE NOT NULL,
    brand                     VARCHAR(20),
    last4                     VARCHAR(4),
    exp_month                 SMALLINT,
    exp_year                  SMALLINT,
    is_default                BOOLEAN NOT NULL DEFAULT false,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at                TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_payment_methods_org ON payment_methods(organization_id) WHERE deleted_at IS NULL;
"""


async def init_payment_methods_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(PAYMENT_METHODS_SCHEMA)
    log.info("payment_methods schema initialised")


class PaymentMethodService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def sync_for_org(self, org_id: str) -> list[dict[str, Any]]:
        """Live Stripe call — refreshes the local cache for one org. Never
        called on the hot read path; triggered explicitly (manual refresh
        button, or webhook on payment_method.attached/customer.updated)."""
        import stripe
        from app.billing.subscriptions import get_org_subscription_service

        customer_id = await get_org_subscription_service().get_stripe_customer_id(org_id)
        if not customer_id:
            return []
        try:
            methods = stripe.PaymentMethod.list(customer=customer_id, type="card")
            customer = stripe.Customer.retrieve(customer_id)
            default_pm = (customer.get("invoice_settings") or {}).get("default_payment_method")
        except Exception:
            log.warning("stripe payment-method sync failed for org=%s", org_id, exc_info=True)
            return await self.list_for_org(org_id)

        org_uuid = uuid.UUID(org_id)
        seen_ids = []
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for pm in methods.auto_paging_iter():
                    card = pm.get("card") or {}
                    seen_ids.append(pm["id"])
                    await conn.execute(
                        """INSERT INTO payment_methods
                             (organization_id, stripe_payment_method_id, brand, last4,
                              exp_month, exp_year, is_default, deleted_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,NULL)
                           ON CONFLICT (stripe_payment_method_id) DO UPDATE SET
                             brand=EXCLUDED.brand, last4=EXCLUDED.last4,
                             exp_month=EXCLUDED.exp_month, exp_year=EXCLUDED.exp_year,
                             is_default=EXCLUDED.is_default, deleted_at=NULL""",
                        org_uuid, pm["id"], card.get("brand"), card.get("last4"),
                        card.get("exp_month"), card.get("exp_year"), pm["id"] == default_pm,
                    )
                if seen_ids:
                    await conn.execute(
                        "UPDATE payment_methods SET deleted_at=NOW() "
                        "WHERE organization_id=$1 AND stripe_payment_method_id != ALL($2::text[]) "
                        "AND deleted_at IS NULL",
                        org_uuid, seen_ids,
                    )
                else:
                    await conn.execute(
                        "UPDATE payment_methods SET deleted_at=NOW() "
                        "WHERE organization_id=$1 AND deleted_at IS NULL",
                        org_uuid,
                    )
        return await self.list_for_org(org_id)

    async def list_for_org(self, org_id: str) -> list[dict[str, Any]]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            rows = await conn.fetch(
                "SELECT * FROM payment_methods WHERE organization_id=$1 AND deleted_at IS NULL "
                "ORDER BY is_default DESC, created_at DESC",
                uuid.UUID(org_id),
            )
        return [dict(r) for r in rows]

    async def mark_default(self, org_id: str, stripe_payment_method_id: str) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE payment_methods SET is_default=false WHERE organization_id=$1",
                    uuid.UUID(org_id),
                )
                await conn.execute(
                    "UPDATE payment_methods SET is_default=true "
                    "WHERE organization_id=$1 AND stripe_payment_method_id=$2",
                    uuid.UUID(org_id), stripe_payment_method_id,
                )


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[PaymentMethodService] = None


def get_payment_method_service(pool: asyncpg.Pool | None = None) -> PaymentMethodService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = PaymentMethodService(pool)
    return _service
