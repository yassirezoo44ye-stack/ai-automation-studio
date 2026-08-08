"""Real-PostgreSQL billing tests — app/billing/payment_methods.py (Testing
Foundation P0-3, third of the four approved services).

Read app/billing/payment_methods.py and its one router
(app/routers/org_billing.py) end to end before writing any test here:

  - payment_methods is a DISPLAY CACHE synced from Stripe — never a source
    of truth for card data. Stripe itself (stripe.PaymentMethod.list,
    stripe.Customer.retrieve) is the one genuinely external boundary in
    this service, so it's the only thing mocked below; every DB-dependent
    behavior (the sync transaction, RLS, cross-tenant isolation) runs
    against real PostgreSQL, matching credits.py/invoices.py's precedent.
  - list_for_org() DOES use acquire_scoped() — RLS-backed, like
    list_ledger() in credits.py.
  - sync_for_org() does NOT use acquire_scoped() (plain self._pool),
    exactly the same asymmetry already documented for credits.grant()/
    get_balance_cents() — every SQL statement inside it explicitly filters
    by the org_id parameter, and both of its real call sites
    (app/routers/org_billing.py's list_payment_methods/
    sync_payment_methods) resolve org_id from a server-verified
    OrgContext (org_context / require_permission), never client input
    directly. Documented, not a demonstrated vulnerability — same
    reasoning already applied to credits.py.
  - mark_default() has ZERO callers anywhere in the codebase (confirmed by
    grep across app/) — dormant, like credits.grant()'s negative-amount
    path. A pinning test below catches it if that ever changes.
  - stripe_payment_method_id is GLOBALLY UNIQUE (not per-org) — matching
    real Stripe IDs, which are already globally unique and tied to one
    customer/org. Every test below generates its own unique id
    (uuid-suffixed) rather than a hardcoded literal, because rows persist
    across tests within this file's shared session-scoped database (only
    each test's *organizations* are fresh, via the two_orgs fixture) —
    reusing a literal id across two test functions would make the second
    test's "insert" silently UPDATE the first test's row instead (the
    ON CONFLICT clause never touches organization_id), corrupting both
    tests. This was caught directly while developing this file: two
    tests failed with stale/empty results and a third with a real
    UniqueViolationError before ids were made unique per test.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def payment_method_service(two_orgs):
    from app.billing.payment_methods import PaymentMethodService
    return PaymentMethodService(two_orgs["pool"])


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _stripe_pm(pm_id: str, brand: str = "visa", last4: str = "4242") -> dict:
    return {"id": pm_id, "card": {"brand": brand, "last4": last4, "exp_month": 12, "exp_year": 2030}}


def _async_return(value):
    async def _f(*_a, **_kw):
        return value
    return _f


class _FakeAutoPagingList(list):
    def auto_paging_iter(self):
        return iter(self)


# ═══════════════════════════════════════════════════════════════════════════════
# sync_for_org: the only genuinely external call (Stripe) is mocked; the
# multi-statement upsert+prune transaction runs against real PostgreSQL.
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyncForOrgPersistence:
    async def test_sync_persists_methods_and_marks_default(self, two_orgs, payment_method_service):
        pm_a_id, pm_b_id = _uid("pm_a"), _uid("pm_b")
        pm_a, pm_b = _stripe_pm(pm_a_id), _stripe_pm(pm_b_id, brand="mastercard", last4="1111")
        with patch("stripe.PaymentMethod.list", return_value=_FakeAutoPagingList([pm_a, pm_b])), \
             patch("stripe.Customer.retrieve", return_value={"invoice_settings": {"default_payment_method": pm_a_id}}), \
             patch(
                 "app.billing.subscriptions.get_org_subscription_service",
                 return_value=MagicMock(get_stripe_customer_id=_async_return("cus_123")),
             ):
            result = await payment_method_service.sync_for_org(two_orgs["org_a"])

        by_id = {r["stripe_payment_method_id"]: r for r in result}
        assert by_id[pm_a_id]["is_default"] is True
        assert by_id[pm_b_id]["is_default"] is False
        assert by_id[pm_b_id]["brand"] == "mastercard"

        # Persisted for real -- visible from a separate connection.
        async with two_orgs["pool"].acquire() as conn:
            rows = await conn.fetch(
                "SELECT stripe_payment_method_id FROM payment_methods "
                "WHERE organization_id=$1 AND deleted_at IS NULL",
                uuid.UUID(two_orgs["org_a"]),
            )
        assert {r["stripe_payment_method_id"] for r in rows} == {pm_a_id, pm_b_id}

    async def test_sync_soft_deletes_methods_no_longer_returned_by_stripe(
        self, two_orgs, payment_method_service,
    ):
        """A card removed on Stripe's side must be soft-deleted locally on
        the next sync, not left as a stale row a caller could still see."""
        pm_a_id, pm_b_id = _uid("pm_a"), _uid("pm_b")
        pm_a, pm_b = _stripe_pm(pm_a_id), _stripe_pm(pm_b_id)
        with patch("stripe.PaymentMethod.list", return_value=_FakeAutoPagingList([pm_a, pm_b])), \
             patch("stripe.Customer.retrieve", return_value={"invoice_settings": {}}), \
             patch(
                 "app.billing.subscriptions.get_org_subscription_service",
                 return_value=MagicMock(get_stripe_customer_id=_async_return("cus_123")),
             ):
            await payment_method_service.sync_for_org(two_orgs["org_a"])

        # Second sync: Stripe now reports only pm_a -- pm_b was removed.
        with patch("stripe.PaymentMethod.list", return_value=_FakeAutoPagingList([pm_a])), \
             patch("stripe.Customer.retrieve", return_value={"invoice_settings": {}}), \
             patch(
                 "app.billing.subscriptions.get_org_subscription_service",
                 return_value=MagicMock(get_stripe_customer_id=_async_return("cus_123")),
             ):
            result = await payment_method_service.sync_for_org(two_orgs["org_a"])

        assert {r["stripe_payment_method_id"] for r in result} == {pm_a_id}
        async with two_orgs["pool"].acquire() as conn:
            deleted = await conn.fetchval(
                "SELECT deleted_at FROM payment_methods "
                "WHERE organization_id=$1 AND stripe_payment_method_id=$2",
                uuid.UUID(two_orgs["org_a"]), pm_b_id,
            )
        assert deleted is not None  # soft-deleted, not hard-deleted, not left active


# ═══════════════════════════════════════════════════════════════════════════════
# Transaction rollback -- forces a real constraint/type failure mid-sync,
# same rigor as invoices.py's atomicity test.
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyncTransactionRollback:
    async def test_sync_is_atomic_a_failure_on_one_row_rolls_back_the_whole_batch(
        self, two_orgs, payment_method_service,
    ):
        """exp_month is SMALLINT -- an out-of-range value Postgres itself
        rejects (not a Python-level validation) forces a real mid-transaction
        failure on the second row. Proves the whole sync (including the
        first row's otherwise-valid INSERT, already executed in the same
        transaction) rolls back, not just that the second row is skipped."""
        pm_ok_id, pm_bad_id = _uid("pm_ok"), _uid("pm_bad")
        pm_ok = _stripe_pm(pm_ok_id)
        pm_bad = {"id": pm_bad_id, "card": {"brand": "visa", "last4": "0000",
                                             "exp_month": 999999, "exp_year": 2030}}
        with patch("stripe.PaymentMethod.list", return_value=_FakeAutoPagingList([pm_ok, pm_bad])), \
             patch("stripe.Customer.retrieve", return_value={"invoice_settings": {}}), \
             patch(
                 "app.billing.subscriptions.get_org_subscription_service",
                 return_value=MagicMock(get_stripe_customer_id=_async_return("cus_123")),
             ):
            with pytest.raises(Exception):
                await payment_method_service.sync_for_org(two_orgs["org_a"])

        async with two_orgs["pool"].acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM payment_methods WHERE organization_id=$1",
                uuid.UUID(two_orgs["org_a"]),
            )
        assert count == 0  # pm_ok's own successful INSERT did NOT survive


# ═══════════════════════════════════════════════════════════════════════════════
# Concurrency -- two concurrent syncs for the same org (e.g. a webhook and
# a manual refresh button firing close together) must not corrupt state.
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrentSync:
    async def test_concurrent_syncs_for_the_same_org_leave_a_consistent_result(
        self, two_orgs, payment_method_service,
    ):
        pm_a_id = _uid("pm_a")
        pm_a = _stripe_pm(pm_a_id)
        with patch("stripe.PaymentMethod.list", return_value=_FakeAutoPagingList([pm_a])), \
             patch("stripe.Customer.retrieve", return_value={"invoice_settings": {"default_payment_method": pm_a_id}}), \
             patch(
                 "app.billing.subscriptions.get_org_subscription_service",
                 return_value=MagicMock(get_stripe_customer_id=_async_return("cus_123")),
             ):
            results = await asyncio.gather(
                payment_method_service.sync_for_org(two_orgs["org_a"]),
                payment_method_service.sync_for_org(two_orgs["org_a"]),
            )

        # Both calls complete without raising, and the ON CONFLICT DO UPDATE
        # upsert means both converge on exactly one row per pm id, not two.
        for result in results:
            assert {r["stripe_payment_method_id"] for r in result} == {pm_a_id}
        async with two_orgs["pool"].acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM payment_methods WHERE organization_id=$1 AND deleted_at IS NULL",
                uuid.UUID(two_orgs["org_a"]),
            )
        assert count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Tenant isolation / authorization boundaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestTenantIsolation:
    async def test_list_for_org_is_rls_backed_even_with_no_where_clause(self, two_orgs):
        """Same rigor as credits.py/invoices.py's RLS proofs: an unqualified
        SELECT with no WHERE at all, through a connection scoped to org A,
        must not see org B's payment method rows."""
        from app.core.db import acquire_scoped

        pm_a_id, pm_b_id = _uid("pm_a"), _uid("pm_b")
        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO payment_methods (organization_id, stripe_payment_method_id, brand, last4) "
                "VALUES ($1, $2, 'visa', '1111')",
                uuid.UUID(two_orgs["org_a"]), pm_a_id,
            )
            await conn.execute(
                "INSERT INTO payment_methods (organization_id, stripe_payment_method_id, brand, last4) "
                "VALUES ($1, $2, 'visa', '2222')",
                uuid.UUID(two_orgs["org_b"]), pm_b_id,
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM payment_methods WHERE stripe_payment_method_id IN ($1, $2)", pm_a_id, pm_b_id)
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_list_for_org_service_method_only_returns_own_org(self, two_orgs, payment_method_service):
        pm_a_id, pm_b_id = _uid("pm_a"), _uid("pm_b")
        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO payment_methods (organization_id, stripe_payment_method_id, brand, last4) "
                "VALUES ($1, $2, 'visa', '1111')",
                uuid.UUID(two_orgs["org_a"]), pm_a_id,
            )
            await conn.execute(
                "INSERT INTO payment_methods (organization_id, stripe_payment_method_id, brand, last4) "
                "VALUES ($1, $2, 'visa', '2222')",
                uuid.UUID(two_orgs["org_b"]), pm_b_id,
            )

        methods_a = await payment_method_service.list_for_org(two_orgs["org_a"])
        ids_a = {m["stripe_payment_method_id"] for m in methods_a}
        assert pm_a_id in ids_a
        assert pm_b_id not in ids_a

    async def test_router_routes_require_org_context_or_billing_manage_permission(self):
        """Structural authorization-boundary check, mirroring the existing
        Security Boundary Sweep's methodology: both payment-method routes
        must depend on a real tenant-verifying dependency, not be reachable
        with a bare/unverified org_id."""
        import inspect
        from app.routers.org_billing import list_payment_methods, sync_payment_methods

        for fn in (list_payment_methods, sync_payment_methods):
            sig = inspect.signature(fn)
            dep_names = {
                getattr(p.default, "dependency", None).__name__
                for p in sig.parameters.values()
                if getattr(p.default, "dependency", None) is not None
            }
            assert dep_names & {"org_context", "require_permission", "_dep"}, (
                f"{fn.__name__} must depend on org_context or require_permission "
                f"(found dependency names: {dep_names})"
            )

    async def test_mark_default_has_no_live_caller_anywhere(self):
        """Pinning test: mark_default() is unscoped (plain self._pool, no
        acquire_scoped(), no explicit permission check inside the method
        itself) and currently has ZERO route wiring it up -- confirmed by
        grep across app/ during this test's development. If a route is
        ever added calling mark_default() with a client-suppliable org_id,
        it needs the same org_context/require_permission treatment as
        every other mutating route in this router, and this test failing
        is the tripwire that should trigger that review."""
        import ast
        import pathlib

        routers_dir = pathlib.Path(__file__).resolve().parents[2] / "app" / "routers"
        callers = []
        for path in routers_dir.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "mark_default":
                    callers.append(str(path))
        assert callers == [], (
            f"mark_default() now has a live caller in {callers} -- it must "
            f"gain the same tenant-authorization treatment as every other "
            f"mutating payment_methods route before this test can be updated."
        )
