"""
Real-PostgreSQL billing tests — app/billing/credits.py (Testing Foundation
P0-3, first service).

Read app/billing/credits.py, app/routers/org_billing.py, and the whole
codebase's call graph before writing any test here — see the findings in
docs/testing-foundation-p0.md's Billing section for what's real behavior
vs. what would be inventing behavior that doesn't exist:

  - CreditService.grant() has exactly one caller anywhere in the codebase
    (app/routers/org_billing.py::grant_credit), which is owner-only and
    Pydantic-validates amount_usd > 0. There is no live "consume credits
    for usage" path — grant()'s own docstring documents a negative-amount
    "consume" capability, but nothing ever exercises it in production
    today. "Insufficient credits" as a live scenario does not exist in
    this codebase; tests below prove the actual (unprotected) behavior
    of the capability instead of asserting a rejection that isn't
    implemented anywhere.
  - grant() and get_balance_cents() do NOT use app.core.db.acquire_scoped
    — unlike list_ledger(), they run on a plain, unscoped connection, so
    Row Level Security is a no-op for them by construction (see
    app/tenancy/rls.py's own "additive defense-in-depth for scoped
    connections only" design). Tenant isolation for these two methods
    relies entirely on the caller (the router) passing a server-verified
    org_id — there is no independent database-layer backstop the way
    list_ledger() has. Documented, not fixed (no bug: no known caller
    passes attacker-controlled org_id to these two methods).
  - No idempotency key exists on `credits` or in grant()'s signature —
    every call inserts a new row unconditionally.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def credit_service(two_orgs):
    from app.billing.credits import CreditService
    return CreditService(two_orgs["pool"])


# ═══════════════════════════════════════════════════════════════════════════════
# Successful grant, persistence, exact-boundary balance
# ═══════════════════════════════════════════════════════════════════════════════

class TestGrantAndBalance:
    async def test_grant_persists_and_is_visible_from_a_separate_connection(
        self, two_orgs, credit_service,
    ):
        row = await credit_service.grant(two_orgs["org_a"], 5000, "promo credit")
        assert row["amount_cents"] == 5000

        # A fresh connection, not the one grant() used — proves real commit,
        # not just an in-transaction/in-memory echo of what was inserted.
        async with two_orgs["pool"].acquire() as conn:
            persisted = await conn.fetchrow(
                "SELECT amount_cents, reason FROM credits WHERE id=$1", row["id"],
            )
        assert persisted["amount_cents"] == 5000
        assert persisted["reason"] == "promo credit"

    async def test_balance_sums_the_ledger(self, two_orgs, credit_service):
        await credit_service.grant(two_orgs["org_a"], 1000, "a")
        await credit_service.grant(two_orgs["org_a"], 2500, "b")
        await credit_service.grant(two_orgs["org_a"], -500, "consumed")

        balance = await credit_service.get_balance_cents(two_orgs["org_a"])
        assert balance == 3000  # 1000 + 2500 - 500

    async def test_exact_boundary_balance_zero_after_full_consumption(
        self, two_orgs, credit_service,
    ):
        """Grant then consume the exact same amount — balance must land on
        precisely zero, not off-by-one from rounding/summation."""
        await credit_service.grant(two_orgs["org_a"], 10000, "grant")
        await credit_service.grant(two_orgs["org_a"], -10000, "full consumption")

        balance = await credit_service.get_balance_cents(two_orgs["org_a"])
        assert balance == 0

    async def test_get_balance_cents_never_returns_negative_even_if_ledger_sum_is(
        self, two_orgs, credit_service,
    ):
        """Documents real, verified behavior: get_balance_cents() clamps its
        return value with max(0, ...), even though nothing prevents the
        underlying ledger SUM from going negative (see
        TestNoInsufficientCreditsProtection below) — the clamp is a
        display-layer safeguard, not a ledger-integrity one."""
        await credit_service.grant(two_orgs["org_a"], 1000, "grant")
        await credit_service.grant(two_orgs["org_a"], -5000, "over-consumption")

        async with two_orgs["pool"].acquire() as conn:
            raw_sum = await conn.fetchval(
                "SELECT SUM(amount_cents) FROM credits WHERE organization_id=$1",
                uuid.UUID(two_orgs["org_a"]),
            )
        assert raw_sum == -4000  # the real, unclamped ledger total

        balance = await credit_service.get_balance_cents(two_orgs["org_a"])
        assert balance == 0  # clamped for display


# ═══════════════════════════════════════════════════════════════════════════════
# Finding: no insufficient-credits protection, no idempotency — documented
# as real, verified current behavior (not invented, not "fixed")
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoInsufficientCreditsProtection:
    async def test_grant_allows_balance_to_go_negative_at_the_service_layer(
        self, two_orgs, credit_service,
    ):
        """FINDING (documented, not fixed — see module docstring and
        docs/testing-foundation-p0.md): grant() performs zero balance
        check before accepting a negative amount. This is real, current
        behavior, not a hypothetical -- verified directly against
        PostgreSQL, not a mock."""
        await credit_service.grant(two_orgs["org_a"], 100, "small grant")
        row = await credit_service.grant(two_orgs["org_a"], -100_000, "large consumption")

        assert row["amount_cents"] == -100_000  # accepted with no rejection

        async with two_orgs["pool"].acquire() as conn:
            raw_sum = await conn.fetchval(
                "SELECT SUM(amount_cents) FROM credits WHERE organization_id=$1",
                uuid.UUID(two_orgs["org_a"]),
            )
        assert raw_sum < 0  # the real ledger total is genuinely negative

    async def test_no_router_ever_calls_grant_with_a_negative_amount(self):
        """Confirms the finding's scope precisely: the ONLY HTTP path to
        grant() (app/routers/org_billing.py::grant_credit) Pydantic-
        validates amount_usd > 0, so the unprotected negative-amount
        capability above is unreachable via any current API endpoint --
        it exists at the service layer only, for a caller that doesn't
        exist yet."""
        from app.routers.org_billing import GrantCreditRequest
        field = GrantCreditRequest.model_fields["amount_usd"]
        constraints = [m for m in field.metadata]
        assert any(getattr(c, "gt", None) == 0 for c in constraints), (
            "GrantCreditRequest.amount_usd must stay gt=0 -- if this ever "
            "changes, TestGrantAndBalance's 'no insufficient-credits "
            "protection' finding becomes reachable from a real endpoint "
            "and should be escalated, not just documented."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Duplicate operations — not deduplicated (no idempotency key exists)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoIdempotencyKey:
    async def test_identical_grant_calls_create_two_ledger_rows_not_one(
        self, two_orgs, credit_service,
    ):
        """FINDING (documented, not fixed): grant() has no idempotency key
        anywhere in its signature or the credits table schema. Two calls
        with byte-identical arguments (as a naive retry would produce)
        create two rows and double the balance -- verified, not assumed."""
        row1 = await credit_service.grant(two_orgs["org_a"], 500, "duplicate reason")
        row2 = await credit_service.grant(two_orgs["org_a"], 500, "duplicate reason")

        assert row1["id"] != row2["id"]
        balance = await credit_service.get_balance_cents(two_orgs["org_a"])
        assert balance == 1000  # both counted -- not deduplicated


# ═══════════════════════════════════════════════════════════════════════════════
# Rollback on failure — a real constraint violation, not an invented one
# ═══════════════════════════════════════════════════════════════════════════════

class TestRollbackOnFailure:
    async def test_grant_with_nonexistent_org_id_fails_atomically_no_partial_row(
        self, two_orgs, credit_service,
    ):
        """organization_id has a real FK constraint (REFERENCES
        organizations(id)) -- a grant() for an org that doesn't exist must
        raise, and must leave zero rows behind (single-statement INSERT is
        atomic in PostgreSQL either way, but this proves it against a real
        constraint rather than assuming asyncpg/PostgreSQL semantics)."""
        import asyncpg
        bogus_org = str(uuid.uuid4())

        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await credit_service.grant(bogus_org, 1000, "should not persist")

        async with two_orgs["pool"].acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM credits WHERE organization_id=$1",
                uuid.UUID(bogus_org),
            )
        assert count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Concurrency — append-only ledger: N concurrent grants must not lose writes
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrentGrants:
    async def test_concurrent_grants_all_persist_no_lost_updates(
        self, two_orgs, credit_service,
    ):
        """grant() is a single INSERT with no read-modify-write step, so
        (unlike an UPDATE-based counter) concurrent calls cannot lose an
        update to each other -- proven with real concurrent connections
        against real PostgreSQL, not asserted from reading the code."""
        n = 20
        results = await asyncio.gather(*[
            credit_service.grant(two_orgs["org_a"], 100, f"concurrent-{i}")
            for i in range(n)
        ])
        assert len({r["id"] for r in results}) == n  # every call got a distinct row

        balance = await credit_service.get_balance_cents(two_orgs["org_a"])
        assert balance == n * 100


# ═══════════════════════════════════════════════════════════════════════════════
# Tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestTenantIsolation:
    async def test_list_ledger_is_rls_backed_even_with_no_where_clause(self, two_orgs):
        """list_ledger() DOES use acquire_scoped() (unlike grant()/
        get_balance_cents() -- see module docstring). Prove the RLS
        backstop directly: an unqualified SELECT with no WHERE at all,
        run through a connection scoped to org A, must not see org B's
        credit rows -- same rigor as the P0-1/P0-2 tenancy tests."""
        from app.billing.credits import CreditService
        from app.core.db import acquire_scoped

        svc = CreditService(two_orgs["pool"])
        await svc.grant(two_orgs["org_a"], 100, "org A credit")
        await svc.grant(two_orgs["org_b"], 200, "org B credit")

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM credits")
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_list_ledger_service_method_only_returns_own_org(self, two_orgs, credit_service):
        await credit_service.grant(two_orgs["org_a"], 100, "org A credit")
        await credit_service.grant(two_orgs["org_b"], 200, "org B credit")

        ledger_a = await credit_service.list_ledger(two_orgs["org_a"])
        assert all(str(row["organization_id"]) == two_orgs["org_a"] for row in ledger_a)
        assert not any(str(row["organization_id"]) == two_orgs["org_b"] for row in ledger_a)

    async def test_grant_and_get_balance_are_not_rls_scoped_by_design(self, two_orgs):
        """FINDING, documented not fixed: grant()/get_balance_cents() use
        self._pool directly, never acquire_scoped(). Prove this precisely:
        an unscoped connection (what these two methods actually use) can
        read every org's credit rows with no filter at all -- the
        opposite of list_ledger()'s guarantee above. This is the RLS
        design's own documented "no-op for unscoped connections" behavior,
        made concrete for this specific service."""
        from app.billing.credits import CreditService

        svc = CreditService(two_orgs["pool"])
        await svc.grant(two_orgs["org_a"], 100, "org A credit")
        await svc.grant(two_orgs["org_b"], 200, "org B credit")

        async with two_orgs["pool"].acquire() as conn:  # plain, unscoped -- what grant() uses internally
            rows = await conn.fetch("SELECT organization_id FROM credits")
        seen = {str(r["organization_id"]) for r in rows}
        assert {two_orgs["org_a"], two_orgs["org_b"]} <= seen
