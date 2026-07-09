"""
coupons — a global promo-code catalog referencing Stripe's own
Coupon/PromotionCode objects. Discount math (percent/amount off, proration)
is never reimplemented locally; Stripe applies it at checkout when a
`discounts` entry is passed.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

COUPONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS coupons (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code                      VARCHAR(40) UNIQUE NOT NULL,
    stripe_promotion_code_id  TEXT,
    percent_off               NUMERIC(5,2),
    amount_off_cents          BIGINT,
    valid_until               TIMESTAMPTZ,
    active                    BOOLEAN NOT NULL DEFAULT true,
    created_by                UUID,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (percent_off IS NOT NULL OR amount_off_cents IS NOT NULL)
);
"""


async def init_coupons_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(COUPONS_SCHEMA)
    log.info("coupons schema initialised")


class CouponService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_by_code(self, code: str) -> Optional[dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT * FROM coupons WHERE code=$1 AND active=true "
            "AND (valid_until IS NULL OR valid_until > NOW())",
            code.upper(),
        )
        return dict(row) if row else None

    async def list_active(self) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            "SELECT * FROM coupons WHERE active=true "
            "AND (valid_until IS NULL OR valid_until > NOW()) ORDER BY created_at DESC",
        )
        return [dict(r) for r in rows]

    async def record_stripe_coupon(
        self, *, code: str, stripe_promotion_code_id: Optional[str] = None,
        percent_off: Optional[float] = None, amount_off_cents: Optional[int] = None,
        valid_until=None, created_by: Optional[str] = None,
    ) -> dict[str, Any]:
        if percent_off is None and amount_off_cents is None:
            raise ValueError("coupon needs percent_off or amount_off_cents")
        import uuid as _uuid
        row = await self._pool.fetchrow(
            """INSERT INTO coupons
                 (code, stripe_promotion_code_id, percent_off, amount_off_cents,
                  valid_until, created_by)
               VALUES ($1,$2,$3,$4,$5,$6)
               RETURNING *""",
            code.upper(), stripe_promotion_code_id, percent_off, amount_off_cents,
            valid_until, _uuid.UUID(created_by) if created_by else None,
        )
        return dict(row)

    async def deactivate(self, code: str) -> bool:
        result = await self._pool.execute(
            "UPDATE coupons SET active=false WHERE code=$1", code.upper(),
        )
        return result != "UPDATE 0"


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[CouponService] = None


def get_coupon_service(pool: asyncpg.Pool | None = None) -> CouponService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = CouponService(pool)
    return _service
