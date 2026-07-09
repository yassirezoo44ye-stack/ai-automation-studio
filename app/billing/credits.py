"""
credits — an append-only ledger + thin wrapper around Stripe's native
`customer.balance` primitive. Stripe holds the real balance (applied
automatically to the next invoice); this table is the audit trail and local
read model so the UI doesn't need a live Stripe call on every page load.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

CREDITS_SCHEMA = """
CREATE TABLE IF NOT EXISTS credits (
    id                                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id                         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    amount_cents                            BIGINT NOT NULL,
    reason                                  TEXT NOT NULL,
    stripe_customer_balance_transaction_id  TEXT,
    created_by                              UUID,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_credits_org ON credits(organization_id, created_at DESC);
"""


async def init_credits_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(CREDITS_SCHEMA)
    log.info("credits schema initialised")


class CreditService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def grant(
        self, org_id: str, amount_cents: int, reason: str, *, actor_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Grant (positive) or consume (negative) credit. Applies to the
        org's Stripe customer balance (negative Stripe balance = credit
        available), then records the local ledger entry — best-effort on
        the Stripe call so a Stripe hiccup doesn't lose the audit intent,
        but the ledger row always records what was requested."""
        stripe_txn_id = None
        try:
            import stripe
            from app.billing.subscriptions import get_org_subscription_service
            customer_id = await get_org_subscription_service().get_stripe_customer_id(org_id)
            if customer_id:
                txn = stripe.Customer.create_balance_transaction(
                    customer_id, amount=-amount_cents, currency="usd", description=reason,
                )
                stripe_txn_id = txn["id"]
        except Exception:
            log.warning("stripe balance transaction failed for org=%s", org_id, exc_info=True)

        row = await self._pool.fetchrow(
            """INSERT INTO credits
                 (organization_id, amount_cents, reason, stripe_customer_balance_transaction_id, created_by)
               VALUES ($1,$2,$3,$4,$5)
               RETURNING *""",
            uuid.UUID(org_id), amount_cents, reason, stripe_txn_id,
            uuid.UUID(actor_id) if actor_id else None,
        )
        return dict(row)

    async def get_balance_cents(self, org_id: str) -> int:
        """Live Stripe balance if reachable (negative Stripe balance = credit
        available, so we invert sign to a positive credit amount), falling
        back to summing the local ledger if Stripe is unreachable so the UI
        still shows something rather than an error."""
        try:
            import stripe
            from app.billing.subscriptions import get_org_subscription_service
            customer_id = await get_org_subscription_service().get_stripe_customer_id(org_id)
            if customer_id:
                customer = stripe.Customer.retrieve(customer_id)
                return max(0, -(customer.get("balance") or 0))
        except Exception:
            log.debug("stripe balance read failed for org=%s, falling back to ledger", org_id, exc_info=True)
        total = await self._pool.fetchval(
            "SELECT COALESCE(SUM(amount_cents),0) FROM credits WHERE organization_id=$1",
            uuid.UUID(org_id),
        )
        return max(0, int(total or 0))

    async def list_ledger(self, org_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            rows = await conn.fetch(
                "SELECT * FROM credits WHERE organization_id=$1 ORDER BY created_at DESC LIMIT $2",
                uuid.UUID(org_id), min(limit, 500),
            )
        return [dict(r) for r in rows]


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[CreditService] = None


def get_credit_service(pool: asyncpg.Pool | None = None) -> CreditService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = CreditService(pool)
    return _service
