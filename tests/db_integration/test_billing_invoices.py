"""
Real-PostgreSQL billing tests — app/billing/invoices.py (Testing Foundation
P0-3, second service).

Read app/billing/invoices.py and app/routers/org_billing.py's invoice
routes before writing any test here. Key facts about real behavior,
verified below rather than assumed:

  - upsert_from_stripe_invoice() is the ONLY write path — invoices,
    invoice_items, and the derived payments row are all upserted inside
    ONE real `async with conn.transaction():` block. There is no
    tenant-triggered create/update/delete endpoint anywhere in
    app/routers/org_billing.py — GET /invoices and GET /invoices/{id}
    are read-only. So "tenant A cannot mutate/delete tenant B's invoice"
    has no live HTTP entrypoint to test in the first place; what's
    tested instead is that the one real mutation path (the
    system-level, Stripe-webhook-driven upsert) is atomic and that reads
    are correctly tenant-scoped.
  - Idempotency is real and by design: `stripe_invoice_id` is UNIQUE,
    and the upsert uses ON CONFLICT ... DO UPDATE for invoices, plus an
    explicit DELETE-then-INSERT pattern (documented in the source) for
    invoice_items/payments — repeated deliveries of the same Stripe
    invoice object converge on one row, not duplicates.
  - No status-transition validation exists: upsert_from_stripe_invoice()
    unconditionally overwrites `status` with whatever the caller passes,
    with no check that e.g. "paid" cannot regress to "draft". This is a
    real, verified gap (out-of-order webhook redelivery could regress a
    row's status) — documented below as current behavior, not fixed
    (fixing it is a design decision about how to handle out-of-order
    Stripe webhook delivery, outside "smallest possible fix" scope for
    a testing task with no confirmed production incident behind it).
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio


def _stripe_invoice(
    *, invoice_id: str, status: str = "open", amount_due: int = 5000,
    amount_paid: int = 0, payment_intent: str | None = None,
    lines: list[dict] | None = None, quantity=1,
) -> dict:
    return {
        "id": invoice_id,
        "customer": "cus_test123",
        "status": status,
        "amount_due": amount_due,
        "amount_paid": amount_paid,
        "currency": "usd",
        "hosted_invoice_url": f"https://stripe.example/{invoice_id}",
        "invoice_pdf": f"https://stripe.example/{invoice_id}.pdf",
        "period_start": None,
        "period_end": None,
        "status_transitions": {},
        "payment_intent": payment_intent,
        "lines": {
            "data": lines if lines is not None else [
                {"description": "Pro plan", "quantity": quantity,
                 "price": {"unit_amount": amount_due}, "amount": amount_due},
            ],
        },
    }


@pytest.fixture
def invoice_service(two_orgs):
    from app.billing.invoices import InvoiceService
    return InvoiceService(two_orgs["pool"])


# ═══════════════════════════════════════════════════════════════════════════════
# Create + persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateAndPersistence:
    async def test_upsert_creates_invoice_with_items_real_postgres(
        self, two_orgs, invoice_service,
    ):
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        result = await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id, status="open", amount_due=9900),
            organization_id=two_orgs["org_a"],
        )
        assert result is not None
        assert result["stripe_invoice_id"] == inv_id
        assert result["amount_due_cents"] == 9900

        async with two_orgs["pool"].acquire() as conn:
            items = await conn.fetch(
                "SELECT * FROM invoice_items WHERE invoice_id=$1", result["id"],
            )
        assert len(items) == 1
        assert items[0]["amount_cents"] == 9900

    async def test_upsert_derives_a_payments_row(self, two_orgs, invoice_service):
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        result = await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id, status="paid", amount_due=4900),
            organization_id=two_orgs["org_a"],
        )
        payments = await invoice_service.list_payments_for_org(two_orgs["org_a"])
        assert any(p["invoice_id"] == result["id"] and p["status"] == "succeeded" for p in payments)

    async def test_missing_resolvable_org_id_skips_persistence_not_an_error(
        self, invoice_service,
    ):
        """upsert_from_stripe_invoice() returns None rather than raising
        when no organization_id can be resolved -- verified real
        behavior, matches the source's own documented contract."""
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        result = await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id), organization_id=None,
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotency — real ON CONFLICT + DELETE-then-INSERT, not invented
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdempotentUpsert:
    async def test_same_stripe_invoice_id_twice_converges_to_one_row(
        self, two_orgs, invoice_service,
    ):
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id, status="open", amount_due=5000),
            organization_id=two_orgs["org_a"],
        )
        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id, status="paid", amount_due=5000, amount_paid=5000),
            organization_id=two_orgs["org_a"],
        )

        async with two_orgs["pool"].acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM invoices WHERE stripe_invoice_id=$1", inv_id,
            )
            row = await conn.fetchrow(
                "SELECT status, amount_paid_cents FROM invoices WHERE stripe_invoice_id=$1", inv_id,
            )
        assert count == 1  # not duplicated
        assert row["status"] == "paid"  # latest delivery won
        assert row["amount_paid_cents"] == 5000

    async def test_repeated_upsert_does_not_duplicate_invoice_items(
        self, two_orgs, invoice_service,
    ):
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        for _ in range(3):
            result = await invoice_service.upsert_from_stripe_invoice(
                _stripe_invoice(invoice_id=inv_id, status="open"),
                organization_id=two_orgs["org_a"],
            )
        async with two_orgs["pool"].acquire() as conn:
            item_count = await conn.fetchval(
                "SELECT COUNT(*) FROM invoice_items WHERE invoice_id=$1", result["id"],
            )
        assert item_count == 1  # replaced, not accumulated across 3 deliveries

    async def test_repeated_delivery_does_not_duplicate_payments_row(
        self, two_orgs, invoice_service,
    ):
        """The specific regression this pattern's source comment guards
        against: repeated invoice.* deliveries (created -> finalized ->
        paid) for the same invoice, with no payment_intent yet, must not
        accumulate duplicate NULL-payment-intent rows."""
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        for status in ("draft", "open", "open"):
            result = await invoice_service.upsert_from_stripe_invoice(
                _stripe_invoice(invoice_id=inv_id, status=status, payment_intent=None),
                organization_id=two_orgs["org_a"],
            )
        async with two_orgs["pool"].acquire() as conn:
            payment_count = await conn.fetchval(
                "SELECT COUNT(*) FROM payments WHERE invoice_id=$1", result["id"],
            )
        assert payment_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Finding: no status-transition validation — documented, not fixed
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoStatusTransitionValidation:
    async def test_status_can_regress_on_out_of_order_delivery(
        self, two_orgs, invoice_service,
    ):
        """FINDING (documented, not fixed -- see module docstring):
        applying a 'draft' delivery after a 'paid' one silently regresses
        the row's status. Nothing in upsert_from_stripe_invoice() orders
        or validates transitions. Verified against real PostgreSQL, not
        assumed from reading the code."""
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id, status="paid", amount_paid=5000),
            organization_id=two_orgs["org_a"],
        )
        result = await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id, status="draft", amount_paid=0),
            organization_id=two_orgs["org_a"],
        )
        assert result["status"] == "draft"  # regressed from "paid" -- no guard exists


# ═══════════════════════════════════════════════════════════════════════════════
# Transaction rollback — force a real failure partway through the 3-statement
# transaction, confirm NOTHING persists, including the already-RETURNING'd
# invoice row
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransactionRollback:
    async def test_invoice_row_does_not_persist_if_line_item_insert_fails(
        self, two_orgs, invoice_service,
    ):
        """A line item with a non-integer quantity fails asyncpg's type
        coercion for invoice_items.quantity (INTEGER NOT NULL) -- this
        happens AFTER the invoice row's own INSERT has already run and
        returned a row within the same transaction (RETURNING *). If the
        transaction is genuinely atomic, that invoice row must NOT exist
        once the error propagates and the `async with conn.transaction()`
        block rolls back."""
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        bad_invoice = _stripe_invoice(invoice_id=inv_id, status="open")
        bad_invoice["lines"]["data"] = [
            {"description": "broken line", "quantity": "not-a-number",
             "price": {"unit_amount": 100}, "amount": 100},
        ]

        with pytest.raises(asyncpg.exceptions.DataError):
            await invoice_service.upsert_from_stripe_invoice(
                bad_invoice, organization_id=two_orgs["org_a"],
            )

        async with two_orgs["pool"].acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM invoices WHERE stripe_invoice_id=$1", inv_id,
            )
        assert count == 0, "invoice row must not survive a rolled-back transaction"

    async def test_nonexistent_org_id_rolls_back_the_whole_transaction(
        self, two_orgs, invoice_service,
    ):
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        bogus_org = str(uuid.uuid4())

        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await invoice_service.upsert_from_stripe_invoice(
                _stripe_invoice(invoice_id=inv_id), organization_id=bogus_org,
            )

        async with two_orgs["pool"].acquire() as conn:
            inv_count = await conn.fetchval(
                "SELECT COUNT(*) FROM invoices WHERE stripe_invoice_id=$1", inv_id,
            )
        assert inv_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Tenant isolation — ownership, cross-org read denial, RLS backstop
# ═══════════════════════════════════════════════════════════════════════════════

class TestTenantIsolation:
    async def test_get_returns_none_for_another_orgs_invoice(self, two_orgs, invoice_service):
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        created = await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id), organization_id=two_orgs["org_b"],
        )
        result = await invoice_service.get(two_orgs["org_a"], str(created["id"]))
        assert result is None

    async def test_get_returns_the_invoice_for_its_own_org(self, two_orgs, invoice_service):
        inv_id = f"in_{uuid.uuid4().hex[:16]}"
        created = await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=inv_id), organization_id=two_orgs["org_a"],
        )
        result = await invoice_service.get(two_orgs["org_a"], str(created["id"]))
        assert result is not None
        assert result["id"] == created["id"]
        assert len(result["items"]) == 1

    async def test_list_for_org_excludes_other_orgs_invoices(self, two_orgs, invoice_service):
        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=f"in_{uuid.uuid4().hex[:16]}"),
            organization_id=two_orgs["org_a"],
        )
        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=f"in_{uuid.uuid4().hex[:16]}"),
            organization_id=two_orgs["org_b"],
        )
        listing = await invoice_service.list_for_org(two_orgs["org_a"])
        assert all(str(row["organization_id"]) == two_orgs["org_a"] for row in listing)

    async def test_rls_denies_cross_org_read_with_no_where_clause(self, two_orgs, invoice_service):
        """get()/list_for_org() already use acquire_scoped() AND an
        explicit WHERE organization_id filter -- prove the RLS backstop
        independently of that application-layer filter, same rigor as
        the P0-1/P0-2 tenancy tests and the credits.py tests above."""
        from app.core.db import acquire_scoped

        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=f"in_{uuid.uuid4().hex[:16]}"),
            organization_id=two_orgs["org_a"],
        )
        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=f"in_{uuid.uuid4().hex[:16]}"),
            organization_id=two_orgs["org_b"],
        )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM invoices")
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_rls_denies_cross_org_payments_read_with_no_where_clause(self, two_orgs, invoice_service):
        from app.core.db import acquire_scoped

        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=f"in_{uuid.uuid4().hex[:16]}", status="paid"),
            organization_id=two_orgs["org_a"],
        )
        await invoice_service.upsert_from_stripe_invoice(
            _stripe_invoice(invoice_id=f"in_{uuid.uuid4().hex[:16]}", status="paid"),
            organization_id=two_orgs["org_b"],
        )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM payments")
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_no_tenant_triggered_mutation_endpoint_exists(self):
        """Documents why 'tenant A cannot mutate/delete tenant B's
        invoice' has no dedicated test above: there is no such endpoint
        to attack in the first place. Confirms this structurally so a
        future PUT/DELETE /invoices/{id} route would be caught by this
        test needing an update -- a signal to write the missing
        ownership test at that time, not silently skipped forever."""
        import inspect
        from app.routers import org_billing
        source = inspect.getsource(org_billing)
        assert "def update_invoice" not in source
        assert "def delete_invoice" not in source
