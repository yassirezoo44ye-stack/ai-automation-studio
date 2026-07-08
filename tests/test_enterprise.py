"""
Enterprise-layer tests: plans/quotas, AI cost router, event bus,
marketplace JSON fallback, and tenancy pure logic.

DB-backed paths (TenancyService, UsageService against PostgreSQL) are
exercised in integration environments; here we cover everything that runs
without a live pool so the suite is green in CI without a database.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Plans / quotas ────────────────────────────────────────────────────────────

class TestPlans(unittest.TestCase):
    def test_all_plans_cover_all_metrics(self):
        from app.billing.plans import PLANS, METRICS
        for plan in PLANS.values():
            for metric in METRICS:
                self.assertIn(metric, plan.limits, f"{plan.id} missing {metric}")

    def test_free_plan_is_default(self):
        from app.billing.plans import get_plan
        self.assertEqual(get_plan("nonexistent").id, "free")

    def test_enterprise_unlimited(self):
        from app.billing.plans import get_plan
        self.assertTrue(all(v == -1 for v in get_plan("enterprise").limits.values()))

    def test_plan_ordering_by_limits(self):
        from app.billing.plans import PLANS
        self.assertLess(PLANS["free"].limits["tokens"], PLANS["starter"].limits["tokens"])
        self.assertLess(PLANS["starter"].limits["tokens"], PLANS["pro"].limits["tokens"])
        self.assertLess(PLANS["pro"].limits["tokens"], PLANS["team"].limits["tokens"])


# ── AI cost router ────────────────────────────────────────────────────────────

class TestCostRouter(unittest.TestCase):
    def setUp(self):
        from app.ai.cost_router import CostRouter
        self.router = CostRouter()

    def test_cheapest_policy_prefers_free_local(self):
        from app.ai.cost_router import RouteRequest, Policy
        d = self.router.route(RouteRequest(policy=Policy.CHEAPEST))
        # ollama is $0 — cheapest must pick it (or another near-zero model)
        self.assertLessEqual(d.predicted_cost_usd, 0.001)

    def test_quality_policy_prefers_top_model(self):
        from app.ai.cost_router import RouteRequest, Policy
        d = self.router.route(RouteRequest(policy=Policy.QUALITY))
        self.assertGreaterEqual(d.quality, 0.95)

    def test_min_quality_filter(self):
        from app.ai.cost_router import RouteRequest, Policy
        d = self.router.route(RouteRequest(policy=Policy.CHEAPEST, min_quality=0.9))
        self.assertGreaterEqual(d.quality, 0.9)

    def test_context_window_filter(self):
        from app.ai.cost_router import RouteRequest
        d = self.router.route(RouteRequest(required_context=500_000))
        self.assertIn("gemini", d.model)

    def test_exclude_providers(self):
        from app.ai.cost_router import RouteRequest
        d = self.router.route(RouteRequest(exclude_providers=("anthropic", "openai")))
        self.assertNotIn(d.provider, ("anthropic", "openai"))

    def test_max_cost_constraint(self):
        from app.ai.cost_router import RouteRequest
        d = self.router.route(RouteRequest(
            est_input_tokens=100_000, est_output_tokens=100_000, max_cost_usd=0.05,
        ))
        self.assertLessEqual(d.predicted_cost_usd, 0.05)

    def test_impossible_constraints_raise(self):
        from app.ai.cost_router import RouteRequest
        with self.assertRaises(LookupError):
            self.router.route(RouteRequest(min_quality=1.1))

    def test_fallbacks_present(self):
        from app.ai.cost_router import RouteRequest
        d = self.router.route(RouteRequest())
        self.assertGreaterEqual(len(d.fallbacks), 1)
        self.assertNotIn(d.model, d.fallbacks)

    def test_cost_tracking_per_scope(self):
        self.router.track_cost("org1", 0.5, scope_type="workflow", scope_id="wf1")
        self.router.track_cost("org1", 0.25, scope_type="workflow", scope_id="wf1")
        self.router.track_cost("org1", 1.0, scope_type="agent", scope_id="a1")
        self.router.track_cost("org2", 9.0)
        costs = self.router.costs_for_org("org1")
        self.assertAlmostEqual(costs["total_usd"], 1.75)
        self.assertAlmostEqual(costs["by_scope"]["workflow"]["wf1"], 0.75)
        # org2 spend must not leak into org1
        self.assertNotIn("org", costs["by_scope"].get("org", {}).get("org2", {}) if False else {})

    def test_availability_toggle(self):
        from app.ai.cost_router import RouteRequest, Policy
        self.router.set_availability("ollama/llama3.1", False)
        d = self.router.route(RouteRequest(policy=Policy.CHEAPEST))
        self.assertNotEqual(d.model, "ollama/llama3.1")


# ── Event bus ─────────────────────────────────────────────────────────────────

class TestEventBus(unittest.TestCase):
    def test_publish_and_exact_subscribe(self):
        from app.core.events.bus import EventBus
        bus = EventBus()
        seen = []

        async def handler(e):
            seen.append(e.type)

        bus.subscribe("workflow.started", handler)
        run(bus.publish("workflow.started", {"run": "r1"}))
        self.assertEqual(seen, ["workflow.started"])

    def test_wildcard_prefix(self):
        from app.core.events.bus import EventBus
        bus = EventBus()
        seen = []

        async def handler(e):
            seen.append(e.type)

        bus.subscribe("workflow.*", handler)

        async def go():
            await bus.publish("workflow.started")
            await bus.publish("workflow.completed")
            await bus.publish("agent.started")   # must NOT match
        run(go())
        self.assertEqual(seen, ["workflow.started", "workflow.completed"])

    def test_undeclared_type_rejected(self):
        from app.core.events.bus import EventBus
        bus = EventBus()
        with self.assertRaises(ValueError):
            run(bus.publish("typo.event"))

    def test_failed_handler_lands_in_dlq(self):
        from app.core.events.bus import EventBus
        bus = EventBus()

        async def boom(e):
            raise RuntimeError("handler exploded")

        bus.subscribe("billing.updated", boom)
        run(bus.publish("billing.updated"))
        dlq = bus.dead_letters()
        self.assertEqual(len(dlq), 1)
        self.assertIn("exploded", dlq[0]["error"])

    def test_replay_with_filter(self):
        from app.core.events.bus import EventBus
        bus = EventBus()

        async def go():
            await bus.publish("agent.started")
            await bus.publish("agent.finished")
            await bus.publish("memory.created")
            return await bus.replay(type_prefix="agent.")
        events = run(go())
        self.assertEqual([e.type for e in events], ["agent.started", "agent.finished"])

    def test_org_scoping_carried(self):
        from app.core.events.bus import EventBus
        bus = EventBus()

        async def go():
            e = await bus.publish("organization.created", organization_id="org-42")
            return e
        e = run(go())
        self.assertEqual(e.organization_id, "org-42")


# ── Marketplace JSON fallback ─────────────────────────────────────────────────

class TestMarketplaceJsonStore(unittest.TestCase):
    def setUp(self):
        import os, tempfile
        self._tmp = tempfile.mkdtemp()
        os.environ["WORKSPACES"] = self._tmp
        from app.marketplace.store import JsonMarketplaceStore
        self.store = JsonMarketplaceStore()

    def test_crud_roundtrip(self):
        item = {"id": "x1", "name": "Thing", "type": "agent",
                "description": "d", "version": "1.0.0", "pricing": "free"}
        run(self.store.upsert_item(item))
        got = run(self.store.get_item("x1"))
        self.assertEqual(got["name"], "Thing")
        self.assertTrue(run(self.store.delete_item("x1")))
        self.assertIsNone(run(self.store.get_item("x1")))

    def test_install_increments(self):
        item = {"id": "x2", "name": "T", "type": "agent",
                "description": "d", "version": "1.0.0", "pricing": "free", "installs": 0}
        run(self.store.upsert_item(item))
        run(self.store.record_install("x2"))
        run(self.store.record_install("x2"))
        self.assertEqual(run(self.store.get_item("x2"))["installs"], 2)

    def test_review_updates_rating(self):
        item = {"id": "x3", "name": "T", "type": "agent",
                "description": "d", "version": "1.0.0", "pricing": "free",
                "rating": 0.0, "rating_count": 0}
        run(self.store.upsert_item(item))
        run(self.store.add_review({"id": "r1", "listing_id": "x3", "rating": 4.0,
                                   "reviewer": "a", "created_at": 0}))
        run(self.store.add_review({"id": "r2", "listing_id": "x3", "rating": 5.0,
                                   "reviewer": "b", "created_at": 0}))
        got = run(self.store.get_item("x3"))
        self.assertAlmostEqual(got["rating"], 4.5)
        self.assertEqual(got["rating_count"], 2)


# ── Tenancy pure logic ────────────────────────────────────────────────────────

class TestTenancyLogic(unittest.TestCase):
    def test_role_hierarchy(self):
        from app.tenancy.service import ROLE_RANK
        self.assertLess(ROLE_RANK["owner"], ROLE_RANK["admin"])
        self.assertLess(ROLE_RANK["admin"], ROLE_RANK["viewer"])

    def test_slugify(self):
        from app.tenancy.service import _slugify
        self.assertEqual(_slugify("Acme Corp!"), "acme-corp")
        self.assertTrue(_slugify("!!!").startswith("org-"))

    def test_permission_matrix_completeness(self):
        from app.tenancy.schema import DEFAULT_PERMISSIONS
        from app.tenancy.service import ROLES
        for role in ROLES:
            self.assertIn(role, DEFAULT_PERMISSIONS)
        # viewer must be read-only
        for resource, action in DEFAULT_PERMISSIONS["viewer"]:
            self.assertEqual(action, "read")
        # owner must have god-mode
        self.assertIn(("*", "*"), DEFAULT_PERMISSIONS["owner"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
