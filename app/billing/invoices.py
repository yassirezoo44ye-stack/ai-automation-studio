"""
Invoices, invoice line items, and payments — a local read model synced from
Stripe (Stripe is the source of truth; these tables exist so the Billing
page doesn't need a live Stripe call on every load).

`payments` rows are derived from invoice payment-status transitions rather
than a separate PaymentIntent/Charge webhook subscription, keeping the
webhook handler's event-type surface additive.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

INVOICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    stripe_invoice_id       TEXT UNIQUE NOT NULL,
    stripe_customer_id      TEXT NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'draft',
    amount_due_cents        BIGINT NOT NULL DEFAULT 0,
    amount_paid_cents       BIGINT NOT NULL DEFAULT 0,
    currency                VARCHAR(3)  NOT NULL DEFAULT 'usd',
    hosted_invoice_url      TEXT,
    invoice_pdf_url         TEXT,
    period_start            TIMESTAMPTZ,
    period_end              TIMESTAMPTZ,
    paid_at                 TIMESTAMPTZ,
    updated_by              UUID,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id, created_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS invoice_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id          UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description         TEXT,
    quantity            INTEGER NOT NULL DEFAULT 1,
    unit_amount_cents   BIGINT NOT NULL DEFAULT 0,
    amount_cents        BIGINT NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS payments (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    invoice_id               UUID REFERENCES invoices(id) ON DELETE SET NULL,
    stripe_payment_intent_id TEXT UNIQUE,
    status                   VARCHAR(20) NOT NULL DEFAULT 'pending',
    amount_cents             BIGINT NOT NULL DEFAULT 0,
    currency                 VARCHAR(3)  NOT NULL DEFAULT 'usd',
    failure_message          TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_payments_org ON payments(organization_id, created_at DESC);
"""

_STATUS_TO_PAYMENT_STATUS = {
    "paid": "succeeded",
    "open": "pending",
    "draft": "pending",
    "uncollectible": "failed",
    "void": "failed",
}


def _ts(epoch: Optional[int]) -> Optional[datetime]:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None


async def init_invoices_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(INVOICES_SCHEMA)
    log.info("invoices/invoice_items/payments schema initialised")


class InvoiceService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def upsert_from_stripe_invoice(
        self, invoice_obj: dict[str, Any], *, organization_id: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Upsert an `invoices` row (+ replace its line items, + derive a
        `payments` row) from a Stripe Invoice API object. `organization_id`
        is resolved by the caller (via subscription/customer metadata) since
        the invoice object itself doesn't always carry it directly."""
        if organization_id is None:
            organization_id = (invoice_obj.get("subscription_details") or {}).get(
                "metadata", {}
            ).get("organization_id") or (invoice_obj.get("metadata") or {}).get("organization_id")
        if not organization_id:
            log.warning(
                "invoice %s has no resolvable organization_id — skipping local persistence",
                invoice_obj.get("id"),
            )
            return None

        org_uuid = uuid.UUID(organization_id)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO invoices
                         (organization_id, stripe_invoice_id, stripe_customer_id, status,
                          amount_due_cents, amount_paid_cents, currency,
                          hosted_invoice_url, invoice_pdf_url,
                          period_start, period_end, paid_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                       ON CONFLICT (stripe_invoice_id) DO UPDATE SET
                         status              = EXCLUDED.status,
                         amount_due_cents    = EXCLUDED.amount_due_cents,
                         amount_paid_cents   = EXCLUDED.amount_paid_cents,
                         hosted_invoice_url  = EXCLUDED.hosted_invoice_url,
                         invoice_pdf_url     = EXCLUDED.invoice_pdf_url,
                         paid_at             = EXCLUDED.paid_at,
                         updated_at          = NOW()
                       RETURNING *""",
                    org_uuid, invoice_obj["id"], invoice_obj.get("customer") or "",
                    invoice_obj.get("status") or "draft",
                    invoice_obj.get("amount_due") or 0, invoice_obj.get("amount_paid") or 0,
                    invoice_obj.get("currency") or "usd",
                    invoice_obj.get("hosted_invoice_url"), invoice_obj.get("invoice_pdf"),
                    _ts(invoice_obj.get("period_start")), _ts(invoice_obj.get("period_end")),
                    _ts(invoice_obj.get("status_transitions", {}).get("paid_at")),
                )
                await conn.execute("DELETE FROM invoice_items WHERE invoice_id=$1", row["id"])
                for line in (invoice_obj.get("lines") or {}).get("data", []):
                    await conn.execute(
                        """INSERT INTO invoice_items
                             (invoice_id, description, quantity, unit_amount_cents, amount_cents)
                           VALUES ($1,$2,$3,$4,$5)""",
                        row["id"], line.get("description"), line.get("quantity") or 1,
                        (line.get("price") or {}).get("unit_amount") or 0,
                        line.get("amount") or 0,
                    )

                # One derived `payments` row per invoice (not per webhook
                # delivery) — replace any prior placeholder row for this
                # invoice each time, then insert the current snapshot. This
                # keeps repeated invoice.* deliveries (created -> finalized
                # -> paid) idempotent even before a payment_intent exists.
                # Idempotency here comes from the DELETE-then-INSERT pair
                # running inside this same transaction, NOT from the
                # ON CONFLICT clause below — Postgres UNIQUE constraints
                # never dedupe NULL values, so ON CONFLICT (stripe_payment_
                # intent_id) is a no-op whenever payment_intent_id is still
                # NULL (draft/open invoices). Any future caller that inserts
                # into `payments` without first deleting by invoice_id would
                # accumulate duplicate NULL-payment-intent rows.
                payment_status = _STATUS_TO_PAYMENT_STATUS.get(row["status"], "pending")
                payment_intent_id = invoice_obj.get("payment_intent") or None
                await conn.execute("DELETE FROM payments WHERE invoice_id=$1", row["id"])
                await conn.execute(
                    """INSERT INTO payments
                         (organization_id, invoice_id, stripe_payment_intent_id, status,
                          amount_cents, currency, failure_message)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)
                       ON CONFLICT (stripe_payment_intent_id) DO UPDATE SET
                         invoice_id      = EXCLUDED.invoice_id,
                         status          = EXCLUDED.status,
                         amount_cents    = EXCLUDED.amount_cents,
                         failure_message = EXCLUDED.failure_message,
                         updated_at      = NOW()""",
                    org_uuid, row["id"], payment_intent_id,
                    payment_status, row["amount_due_cents"], row["currency"], failure_message,
                )
        return dict(row)

    async def list_for_org(self, org_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            rows = await conn.fetch(
                "SELECT * FROM invoices WHERE organization_id=$1 AND deleted_at IS NULL "
                "ORDER BY created_at DESC LIMIT $2",
                uuid.UUID(org_id), min(limit, 200),
            )
        return [dict(r) for r in rows]

    async def get(self, org_id: str, invoice_id: str) -> Optional[dict[str, Any]]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM invoices WHERE id=$1 AND organization_id=$2 AND deleted_at IS NULL",
                uuid.UUID(invoice_id), uuid.UUID(org_id),
            )
            if row is None:
                return None
            items = await conn.fetch(
                "SELECT * FROM invoice_items WHERE invoice_id=$1 ORDER BY created_at", row["id"],
            )
        return {**dict(row), "items": [dict(i) for i in items]}

    async def list_payments_for_org(self, org_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            rows = await conn.fetch(
                "SELECT * FROM payments WHERE organization_id=$1 ORDER BY created_at DESC LIMIT $2",
                uuid.UUID(org_id), min(limit, 200),
            )
        return [dict(r) for r in rows]

    async def backfill_from_stripe(self, org_id: str, stripe_customer_id: str) -> None:
        """Lazy one-time sync for orgs with pre-existing Stripe history that
        predates this phase — called on first read if the local table is
        empty for that customer, not a bulk migration job."""
        import stripe
        try:
            invoices = stripe.Invoice.list(customer=stripe_customer_id, limit=100)
            for inv in invoices.auto_paging_iter():
                await self.upsert_from_stripe_invoice(inv, organization_id=org_id)
        except Exception:
            log.warning("stripe invoice backfill failed for org=%s", org_id, exc_info=True)


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[InvoiceService] = None


def get_invoice_service(pool: asyncpg.Pool | None = None) -> InvoiceService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = InvoiceService(pool)
    return _service
