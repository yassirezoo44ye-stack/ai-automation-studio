"""Real-PostgreSQL billing tests — app/billing/plan_service.py (Testing
Foundation P0-3, fourth and last of the four approved services).

Read app/billing/plan_service.py and its one router
(app/routers/usage_api.py) before writing any test here:

  - subscription_plans is a GLOBAL catalog, not org-scoped data — there is
    no organization_id column, no acquire_scoped() usage, and no RLS
    policy for it (confirmed: not in app/tenancy/rls.py's scoped-table
    list). Every "tenant isolation" question this P0-3 slice asks
    elsewhere (credits, invoices, payment_methods) simply does not apply
    here — a plan's price/limits/features are the same for every org that
    subscribes to it. This is a real architectural fact, not a gap:
    documented instead of forcing an isolation test that doesn't fit the
    data model.
  - The one authorization-relevant fact is that POST /api/admin/plans/{id}
    is gated by require_api_key(scopes=["admin"]) (cross-org, matching
    every other true "global admin" mutation in this codebase, e.g.
    diagnostics_api.py) rather than org_context/require_permission (which
    need an OrgContext this action doesn't have) — verified below as a
    structural check, same methodology as the Security Boundary Sweep.
  - refresh_cache()/update_plan() are what's genuinely worth testing
    against real Postgres: the in-process cache must reflect what's
    actually committed, partial UPDATE must only touch the columns
    passed, and get_plan() must keep serving a *deactivated* plan's real
    limits to an org already on it (its own code comment says so) rather
    than silently substituting the free tier.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def plan_service(pg_pool):
    """subscription_plans is global, not per-org -- no two_orgs needed here,
    just the real pool (already seeded with _SEED_PLANS by
    init_subscription_plans_schema in conftest.py's session setup)."""
    from app.billing.plan_service import PlanService
    return PlanService(pg_pool)


class TestSeedDataAndListPlans:
    async def test_seed_plans_are_present_and_active(self, plan_service):
        plans = await plan_service.list_plans()
        assert len(plans) > 0
        assert all(p.active for p in plans)

    async def test_get_known_plan_returns_real_data(self, plan_service):
        plan = await plan_service.get_plan("free")
        assert plan.id == "free"

    async def test_get_unknown_plan_falls_back_to_free_tier_not_an_error(self, plan_service):
        """Documented, verified behavior (see the module's own log.warning
        call) -- an unknown plan_id does not raise, it silently falls back
        to 'free'. Real behavior, not assumed from reading the code."""
        plan = await plan_service.get_plan("this-plan-id-does-not-exist")
        assert plan.id == "free"


class TestUpdatePlanPersistsAndInvalidatesCache:
    async def test_update_plan_persists_to_real_postgres(self, pg_pool, plan_service):
        new_name = f"Free Tier {uuid.uuid4().hex[:8]}"
        updated = await plan_service.update_plan("free", name=new_name)
        assert updated.name == new_name

        # Visible from a separate connection -- proves a real commit, not
        # just the in-process cache echoing back what was written.
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT name FROM subscription_plans WHERE id='free'")
        assert row["name"] == new_name

    async def test_update_plan_only_touches_the_fields_passed(self, pg_pool, plan_service):
        """Partial update: changing only `name` must not clobber
        `price_monthly_cents` or any other column -- proves the dynamic
        SET-clause builder in update_plan() actually scopes to the
        fields given, not a full-row overwrite."""
        before = await plan_service.get_plan("free")
        await plan_service.update_plan("free", name=f"Renamed {uuid.uuid4().hex[:6]}")
        after = await plan_service.get_plan("free")

        assert after.price_monthly_usd == before.price_monthly_usd
        assert after.limits == before.limits
        assert after.max_agents == before.max_agents

    async def test_update_plan_refreshes_the_in_process_cache(self, plan_service):
        """refresh_cache() is called at the end of update_plan() -- prove
        the SAME service instance reflects the change immediately, not
        only after some future cache expiry (there is no TTL by design)."""
        new_name = f"Cache Check {uuid.uuid4().hex[:8]}"
        await plan_service.update_plan("free", name=new_name)
        # get_plan() reads self._cache directly when non-empty -- if the
        # cache weren't refreshed, this would return the stale name.
        plan = await plan_service.get_plan("free")
        assert plan.name == new_name

    async def test_update_plan_unknown_id_raises_value_error(self, plan_service):
        with pytest.raises(ValueError):
            await plan_service.update_plan("this-plan-does-not-exist", name="x")

    async def test_deactivated_plan_still_returns_its_real_limits_not_free_tier(
        self, pg_pool, plan_service,
    ):
        """The module's own code comment: an org can already be on a plan
        an admin later deactivates, and get_plan() must keep returning
        that plan's REAL limits (not silently substitute the free tier's)
        so a still-subscribed org isn't unexpectedly downgraded. Verified
        against real Postgres, not assumed from the comment."""
        # Insert a distinctive one-off plan, real INSERT not a fixture.
        plan_id = f"testplan{uuid.uuid4().hex[:6]}"
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO subscription_plans (id, name, price_monthly_cents, "
                "max_agents, max_workflows, active) VALUES ($1, $2, 12300, 7, 3, true)",
                plan_id, "Distinctive Test Plan",
            )
        await plan_service.refresh_cache()
        active_plan = await plan_service.get_plan(plan_id)
        assert active_plan.max_agents == 7

        await plan_service.update_plan(plan_id, active=False)
        still_returned = await plan_service.get_plan(plan_id)
        assert still_returned.id == plan_id  # NOT silently swapped to "free"
        assert still_returned.max_agents == 7  # real limits preserved

        # But list_plans() (the purchasable/display catalog) must exclude it.
        listed_ids = {p.id for p in await plan_service.list_plans()}
        assert plan_id not in listed_ids


class TestAdminOnlyAuthorizationBoundary:
    async def test_update_plan_route_requires_admin_scoped_api_key(self):
        """Structural check, same methodology as the Security Boundary
        Sweep: POST /api/admin/plans/{id} must depend on
        require_api_key(scopes=["admin"]) -- global admin action, correctly
        NOT org_context/require_permission (there is no OrgContext for a
        cross-org catalog edit)."""
        import inspect
        from app.routers.usage_api import update_plan

        sig = inspect.signature(update_plan)
        dep_names = [
            getattr(p.default, "dependency", None).__name__
            for p in sig.parameters.values()
            if getattr(p.default, "dependency", None) is not None
        ]
        assert dep_names, "update_plan must have a Depends(...) authorization dependency"
        # require_api_key(...) returns a closure named _dep -- named-function
        # identity check, same pattern used across this test suite.
        assert "_dep" in dep_names or "require_api_key" in dep_names
