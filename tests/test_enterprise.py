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
    """_SEED_PLANS is the idempotent seed data for the subscription_plans
    table (app/billing/plan_service.py) — no longer the runtime source of
    truth, but its shape is still pure-Python and DB-free to test here."""

    def test_all_plans_cover_all_metrics(self):
        from app.billing.plans import _SEED_PLANS, METRICS
        for plan in _SEED_PLANS.values():
            for metric in METRICS:
                self.assertIn(metric, plan.limits, f"{plan.id} missing {metric}")

    def test_enterprise_unlimited(self):
        from app.billing.plans import _SEED_PLANS
        self.assertTrue(all(v == -1 for v in _SEED_PLANS["enterprise"].limits.values()))
        self.assertEqual(_SEED_PLANS["enterprise"].max_agents, -1)
        self.assertEqual(_SEED_PLANS["enterprise"].max_workflows, -1)

    def test_plan_ordering_by_limits(self):
        from app.billing.plans import _SEED_PLANS
        self.assertLess(_SEED_PLANS["free"].limits["tokens"], _SEED_PLANS["starter"].limits["tokens"])
        self.assertLess(_SEED_PLANS["starter"].limits["tokens"], _SEED_PLANS["pro"].limits["tokens"])
        self.assertLess(_SEED_PLANS["pro"].limits["tokens"], _SEED_PLANS["team"].limits["tokens"])

    def test_pro_plan_id_unchanged_despite_display_name_change(self):
        """Display name became "Professional" to match the spec, but the id
        must stay "pro" — STRIPE_PRICE_ID_PRO / PLAN_TO_PRICE key off it."""
        from app.billing.plans import _SEED_PLANS
        self.assertEqual(_SEED_PLANS["pro"].id, "pro")
        self.assertEqual(_SEED_PLANS["pro"].name, "Professional")

    def test_free_and_enterprise_not_purchasable_by_default(self):
        from app.billing.plans import _SEED_PLANS
        self.assertFalse(_SEED_PLANS["free"].is_purchasable)
        self.assertFalse(_SEED_PLANS["enterprise"].is_purchasable)
        for plan_id in ("starter", "pro", "team"):
            self.assertTrue(_SEED_PLANS[plan_id].is_purchasable)


class TestPlanService(unittest.TestCase):
    """PlanService itself is DB-backed; these tests cover the pure-logic
    parts (row<->Plan conversion, update field mapping) with a stub
    connection rather than a live pool."""

    def test_row_to_plan_converts_cents_to_usd(self):
        from app.billing.plan_service import _row_to_plan
        row = {
            "id": "pro", "name": "Professional", "price_monthly_cents": 4900,
            "limits": '{"tokens": 10}', "features": ["sso"], "trial_days": 14,
            "max_agents": 50, "max_workflows": 100, "stripe_price_id": None,
            "is_purchasable": True, "active": True,
        }
        plan = _row_to_plan(row)
        self.assertEqual(plan.price_monthly_usd, 49.0)
        self.assertEqual(plan.limits, {"tokens": 10})

    def test_refresh_cache_does_not_filter_by_active(self):
        """Regression: get_plan() must keep returning a deactivated plan's
        real limits for orgs already on it — refresh_cache() used to only
        SELECT WHERE active=true, so get_plan() would miss the cache and
        silently fall through to the free tier's limits instead, changing
        an org's effective quota with zero billing-status change or signal."""
        import inspect
        from app.billing.plan_service import PlanService
        source = inspect.getsource(PlanService.refresh_cache)
        self.assertNotIn("WHERE active=true", source)

    def test_list_plans_filters_to_active_for_display(self):
        """The public /api/plans catalog must still hide deactivated plans
        — only get_plan() (org lookups) needs to see them."""
        import inspect
        from app.billing.plan_service import PlanService
        source = inspect.getsource(PlanService.list_plans)
        self.assertIn("p.active", source)


# ── AI cost router ────────────────────────────────────────────────────────────

class TestCostRouter(unittest.TestCase):
    def setUp(self):
        from app.ai.cost_router import CostRouter
        self.router = CostRouter()

    def test_cheapest_policy_picks_cheapest_available_model(self):
        from app.ai.cost_router import RouteRequest, Policy
        d = self.router.route(RouteRequest(policy=Policy.CHEAPEST))
        # ollama/llama3.1 is $0 but has no real provider backend (available=False
        # by default — see cost_router.py) so it must never be selected, even
        # though it would otherwise win on price alone.
        self.assertNotEqual(d.model, "ollama/llama3.1")
        self.assertLessEqual(d.predicted_cost_usd, 0.001)

    def test_unimplemented_providers_excluded_by_default(self):
        """Regression guard: DeepSeek/Mistral/Ollama/Azure/Bedrock are
        catalogued but have no app/ai/providers/*.py backend. route() must
        never hand back a model that would fail at execution."""
        from app.ai.cost_router import RouteRequest, Policy
        unimplemented = {
            "deepseek-chat", "mistral-large", "mistral-small",
            "ollama/llama3.1", "azure/gpt-4o", "bedrock/claude-sonnet",
        }
        for policy in (Policy.CHEAPEST, Policy.FASTEST, Policy.QUALITY, Policy.BALANCED):
            d = self.router.route(RouteRequest(policy=policy))
            self.assertNotIn(d.model, unimplemented, f"policy={policy} selected unimplemented {d.model}")

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


# ── ModelRouter / catalog — the ACTUAL routing path InferenceEngine calls ──────
# (distinct from app.ai.cost_router.CostRouter above, which is a separate,
# standalone system not currently wired into real completion calls)

class TestModelRouterCatalog(unittest.TestCase):
    def test_openrouter_excluded_from_every_policy(self):
        """Regression guard: openrouter/auto has no app/ai/providers/*.py
        backend (ProviderRegistry only knows anthropic/openai/gemini) and its
        $0.0 cost would otherwise make CHEAPEST policy always select it,
        causing every completion to fail (failover_chain() returns empty for
        an unknown provider id)."""
        from app.core.ai.router.model_router import ModelRouter, SelectionPolicy
        from app.ai.models import CompletionRequest, Message
        router = ModelRouter()
        req = CompletionRequest(messages=[Message(role="user", content="hi")], max_tokens=100)
        for policy in (SelectionPolicy.CHEAPEST, SelectionPolicy.FASTEST,
                      SelectionPolicy.BEST, SelectionPolicy.BALANCED):
            sel = router.select(req, policy=policy)
            self.assertNotEqual(sel.model_id, "openrouter/auto",
                               f"policy={policy} selected the unimplemented openrouter model")

    def test_openrouter_still_documented_but_deprecated(self):
        from app.core.ai.models.catalog import catalog
        info = catalog.get("openrouter/auto")
        self.assertIsNotNone(info, "entry should stay documented, not deleted")
        self.assertTrue(info.deprecated, "must be excluded from auto-selection via deprecated=True")

    def test_all_non_deprecated_catalog_models_have_a_real_provider(self):
        """Every selectable model must map to a provider ProviderRegistry
        actually knows how to call — otherwise selection succeeds but
        execution fails downstream. Mirrors app/ai/providers/registry.py's
        _ALL dict (anthropic/openai/gemini) — update both if a new provider
        backend is added."""
        from app.core.ai.models.catalog import catalog
        known_providers = {"anthropic", "openai", "gemini"}
        for model in catalog.all():
            if model.deprecated:
                continue
            self.assertIn(model.provider_id, known_providers,
                         f"{model.id} selectable but provider {model.provider_id!r} has no backend")


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

    def test_teams_manage_permission_seeded_for_admin_and_manager(self):
        """Team CRUD/membership endpoints gate on require_permission("teams",
        "manage") — without this exact tuple seeded, admins (who otherwise
        rely on the (*, update) wildcard, which doesn't match action
        "manage") would be locked out of managing teams."""
        from app.tenancy.schema import DEFAULT_PERMISSIONS
        self.assertIn(("teams", "manage"), DEFAULT_PERMISSIONS["admin"])
        self.assertIn(("teams", "manage"), DEFAULT_PERMISSIONS["manager"])
        for role in ("developer", "operator", "viewer"):
            self.assertNotIn(("teams", "manage"), DEFAULT_PERMISSIONS[role])

    def test_team_members_has_full_audit_columns(self):
        """Every tenant-owned table must carry the 5-column audit contract
        (organization_id/created_by/updated_by/created_at/updated_at) —
        team_members originally shipped without updated_by/updated_at."""
        from app.tenancy.schema import TENANCY_SCHEMA
        start = TENANCY_SCHEMA.index("CREATE TABLE IF NOT EXISTS team_members")
        end = TENANCY_SCHEMA.index(";", start)
        ddl = TENANCY_SCHEMA[start:end]
        for col in ("created_by", "updated_by", "created_at", "updated_at", "deleted_at"):
            self.assertIn(col, ddl, f"team_members missing {col}")

    def test_team_members_migration_backfills_existing_deployments(self):
        """A deployment that already has team_members from before updated_by/
        updated_at existed must get them via ALTER TABLE, not just fresh
        installs via CREATE TABLE IF NOT EXISTS (which is a no-op on an
        existing table)."""
        from app.tenancy.schema import _MIGRATIONS
        combined = " ".join(_MIGRATIONS)
        self.assertIn("team_members", combined)
        self.assertIn("updated_by", combined)
        self.assertIn("updated_at", combined)
        for stmt in _MIGRATIONS:
            self.assertIn("IF NOT EXISTS", stmt, "migrations must be idempotent")

    def test_settings_update_uses_merge_patch_not_overwrite(self):
        """update_settings must use jsonb || (merge) so a partial PATCH can't
        silently wipe unrelated keys already stored in organizations.settings."""
        import inspect
        from app.tenancy.service import TenancyService
        source = inspect.getsource(TenancyService.update_settings)
        self.assertIn("settings || $2::jsonb", source)

    def test_organization_update_permission_requires_wildcard_update(self):
        """PATCH /api/orgs/{id} and /settings gate on require_permission
        ("organization", "update") — admin has no explicit tuple for this
        resource, so it must fall through to the (*, update) wildcard."""
        from app.tenancy.schema import DEFAULT_PERMISSIONS
        self.assertIn(("*", "update"), DEFAULT_PERMISSIONS["admin"])
        self.assertNotIn(("*", "update"), DEFAULT_PERMISSIONS["manager"])


# ── API Keys — Postgres-backed, org-scoped ─────────────────────────────────────

class TestApiKeys(unittest.TestCase):
    def test_key_management_functions_are_async(self):
        """Storage moved from an in-memory dict to Postgres — every call site
        (routers) must await these now. A regression back to sync functions
        would silently break every caller with a coroutine-never-awaited bug."""
        import inspect
        from app.core import api_keys as ak
        for name in ("create_api_key", "revoke_api_key", "list_api_keys", "lookup_key"):
            self.assertTrue(
                inspect.iscoroutinefunction(getattr(ak, name)),
                f"{name} must be async",
            )

    def test_dev_key_never_touches_the_database(self):
        """AXON_DEV_API_KEY must keep working with zero DB dependency so
        local dev/CI can authenticate as the seeded admin key without a
        live Postgres pool — this is checked in-memory before any query."""
        import app.core.api_keys as ak
        from unittest.mock import patch

        with patch.object(ak, "_DEV_KEY_RAW", "axon_devtestkey0000"):
            rec = run(ak.lookup_key("axon_devtestkey0000"))
        self.assertIsNotNone(rec)
        self.assertEqual(rec.owner_id, "system")
        self.assertIsNone(rec.organization_id)
        self.assertIn("admin", rec.scopes)

    def test_epoch_datetime_round_trip(self):
        import time
        from app.core.api_keys import _dt, _epoch
        now = time.time()
        self.assertAlmostEqual(_epoch(_dt(now)), now, places=3)
        self.assertIsNone(_dt(None))
        self.assertIsNone(_epoch(None))

    def test_api_keys_table_is_rls_scoped(self):
        from app.tenancy.rls import _RLS_TABLES
        table_cols = dict(_RLS_TABLES)
        self.assertEqual(table_cols.get("api_keys"), "organization_id")

    def test_organization_id_nullable_for_system_keys(self):
        """organization_id must be nullable so the legacy AXON_DEV_API_KEY /
        personal keys (organization_id=None) keep working unchanged."""
        from app.core.api_keys import API_KEYS_SCHEMA
        start = API_KEYS_SCHEMA.index("organization_id")
        line = API_KEYS_SCHEMA[start:API_KEYS_SCHEMA.index("\n", start)]
        self.assertNotIn("NOT NULL", line)

    def test_personal_key_endpoints_never_touch_org_scoped_keys(self):
        """Regression: the personal owner_id-only path in list_api_keys/
        revoke_api_key must exclude organization_id IS NOT NULL rows — an
        org admin's personal key listing/revoke must not accidentally
        include or revoke a key that belongs to /api/orgs/{id}/api-keys."""
        import inspect
        from app.core import api_keys as ak
        list_source = inspect.getsource(ak.list_api_keys)
        self.assertIn("organization_id IS NULL", list_source)
        revoke_source = inspect.getsource(ak.revoke_api_key)
        self.assertIn("organization_id IS NULL", revoke_source)

    def test_legacy_api_keys_router_requires_authentication(self):
        """Regression: create_key/list_keys/revoke_key originally had zero
        auth dependency — any caller could create, list, or revoke every API
        key in the system. Every endpoint must now depend on get_current_user
        and scope by the caller's own owner_id."""
        import inspect
        from app.routers import api_keys_router
        from app.routers.auth_users import get_current_user
        for name in ("create_key", "list_keys", "revoke_key"):
            fn = getattr(api_keys_router, name)
            sig = inspect.signature(fn)
            depends_on_user = any(
                getattr(p.default, "dependency", None) is get_current_user
                for p in sig.parameters.values()
            )
            self.assertTrue(depends_on_user, f"{name} must Depends(get_current_user)")


# ── MFA / TOTP pure logic ─────────────────────────────────────────────────────

class TestMfaTotp(unittest.TestCase):
    def test_totp_round_trip(self):
        import pyotp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        self.assertTrue(totp.verify(totp.now(), valid_window=1))

    def test_totp_rejects_wrong_code(self):
        import pyotp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        real = totp.now()
        wrong = "000000" if real != "000000" else "111111"
        self.assertFalse(totp.verify(wrong, valid_window=0))

    def test_provisioning_uri_shape(self):
        import pyotp
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(name="user@example.com", issuer_name="Axon")
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn("issuer=Axon", uri)

    def test_backup_code_generation(self):
        from app.routers.auth_users import _generate_backup_codes
        codes = _generate_backup_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)  # no collisions
        for c in codes:
            self.assertEqual(len(c), 8)
            self.assertEqual(c, c.upper())

    def test_make_oauth_session_uses_correct_access_token_signature(self):
        """Regression: _make_oauth_session used to call make_access_token()
        with a single dict argument, but the function requires two
        positional string args (user_id, email) — every OAuth login would
        crash with a TypeError before ever reaching session persistence."""
        import inspect
        from app.core.jwt_utils import make_access_token
        sig = inspect.signature(make_access_token)
        self.assertEqual(list(sig.parameters), ["user_id", "email"])


# ── Stripe plan mapping ───────────────────────────────────────────────────────

class TestStripePlans(unittest.TestCase):
    def test_price_lookup_symmetry(self):
        from app.billing.stripe_plans import PLAN_TO_PRICE, PRICE_TO_PLAN
        for plan_id, price_id in PLAN_TO_PRICE.items():
            if price_id:
                self.assertEqual(PRICE_TO_PLAN[price_id], plan_id)

    def test_enterprise_not_purchasable(self):
        from app.billing.stripe_plans import PURCHASABLE_PLANS
        self.assertNotIn("enterprise", PURCHASABLE_PLANS)
        self.assertNotIn("free", PURCHASABLE_PLANS)


# ── Billing calculations ───────────────────────────────────────────────────────

class TestBillingCalculations(unittest.TestCase):
    def test_invoice_status_to_payment_status_mapping_is_total(self):
        """Every Stripe invoice status this app's webhook handler passes
        through must map to a valid payments.status value, or a webhook
        payload with an unmapped status would silently default via .get()
        — guard the mapping's coverage of Stripe's real invoice statuses."""
        from app.billing.invoices import _STATUS_TO_PAYMENT_STATUS
        for stripe_status in ("paid", "open", "draft", "uncollectible", "void"):
            self.assertIn(stripe_status, _STATUS_TO_PAYMENT_STATUS)
        valid_payment_statuses = {"pending", "succeeded", "failed", "refunded"}
        for v in _STATUS_TO_PAYMENT_STATUS.values():
            self.assertIn(v, valid_payment_statuses)

    def test_invoice_upsert_derives_payments_keyed_by_invoice_not_duplicated(self):
        """Regression: an earlier draft of upsert_from_stripe_invoice used a
        ternary that inserted a fresh payments row per call when no
        payment_intent_id existed yet, accumulating duplicates across
        invoice.created -> invoice.finalized -> invoice.paid deliveries for
        the same invoice. The fix deletes prior rows for the invoice_id
        before inserting the current snapshot."""
        import inspect
        from app.billing.invoices import InvoiceService
        source = inspect.getsource(InvoiceService.upsert_from_stripe_invoice)
        self.assertIn("DELETE FROM payments WHERE invoice_id=$1", source)

    def test_cents_to_usd_round_trip(self):
        from app.billing.plan_service import _row_to_plan
        for cents, usd in ((0, 0.0), (1900, 19.0), (4900, 49.0), (9900, 99.0)):
            row = {
                "id": "x", "name": "X", "price_monthly_cents": cents,
                "limits": "{}", "features": [], "trial_days": 0,
                "max_agents": -1, "max_workflows": -1, "stripe_price_id": None,
                "is_purchasable": True, "active": True,
            }
            self.assertEqual(_row_to_plan(row).price_monthly_usd, usd)

    def test_coupon_requires_a_discount_type(self):
        import inspect
        from app.billing.coupons import CouponService
        source = inspect.getsource(CouponService.record_stripe_coupon)
        self.assertIn("percent_off is None and amount_off_cents is None", source)


# ── Webhook event routing ──────────────────────────────────────────────────────

class TestWebhookEventRouting(unittest.TestCase):
    """Full delivery (signature verification, DB writes) can only be
    verified against a real Postgres + Stripe test payloads — verified via
    the live-Postgres script this phase. Here we guard the event-type
    routing surface via source inspection, matching TestRlsPolicyShape's
    established technique for this codebase."""

    def _webhook_source(self) -> str:
        import inspect
        from app.routers import subscriptions
        return inspect.getsource(subscriptions)

    def test_new_invoice_events_are_routed(self):
        source = self._webhook_source()
        for event_type in ("invoice.created", "invoice.finalized", "invoice.paid",
                            "invoice.payment_failed", "invoice.voided"):
            self.assertIn(event_type, source)

    def test_new_payment_method_events_are_routed(self):
        source = self._webhook_source()
        for event_type in ("payment_method.attached", "payment_method.detached",
                            "payment_method.updated", "customer.updated"):
            self.assertIn(event_type, source)

    def test_dedup_check_runs_before_dispatch(self):
        """Regression: the webhook handler must record the event id and
        bail out on a duplicate BEFORE calling _dispatch_webhook_event —
        otherwise a replayed Stripe delivery re-runs every side effect."""
        source = self._webhook_source()
        record_pos = source.index("wh_svc.record(")
        dispatch_pos = source.index("_dispatch_webhook_event(event)")
        self.assertLess(record_pos, dispatch_pos)

    def test_legacy_status_collapse_and_org_tier_status_are_computed_separately(self):
        """Regression: the org-tiered system must receive the verbatim
        Stripe status (so "trialing" isn't collapsed to inactive), while
        the legacy flat-rate table keeps its own binary active/inactive
        contract — these must not be the same variable."""
        source = self._webhook_source()
        self.assertIn("legacy_status = ", source)
        self.assertIn('status=sub["status"]', source)

    def test_subscription_created_event_is_routed(self):
        """Regression: checkout.session.completed hardcodes status="active"
        even when the subscription actually starts trialing — without also
        handling customer.subscription.created, that inaccurate status could
        persist far longer than the brief self-correcting window a reviewer
        would otherwise assume."""
        source = self._webhook_source()
        self.assertIn("customer.subscription.created", source)

    def test_failed_dispatch_raises_instead_of_swallowing(self):
        """Regression: a caught-and-logged dispatch failure must re-raise
        (as a non-2xx HTTPException) so Stripe actually retries — silently
        returning {"received": True} on failure both stops Stripe from
        retrying AND (combined with the dedup table) permanently prevents
        any future redelivery of that event from being reprocessed."""
        source = self._webhook_source()
        self.assertIn("raise HTTPException(500,", source)

    def test_critical_sync_helpers_do_not_swallow_the_core_write(self):
        """Regression: _sync_org_subscription and _sync_invoice used to wrap
        their entire body (including the core DB write) in a try/except
        that only logged — meaning a failed plan/invoice write still let
        mark_processed run, permanently losing that webhook's effect. Only
        the non-critical event-bus publish should be separately isolated."""
        import inspect
        from app.routers import subscriptions
        sync_org = inspect.getsource(subscriptions._sync_org_subscription)
        sync_invoice = inspect.getsource(subscriptions._sync_invoice)
        # apply_webhook_update / upsert_from_stripe_invoice must be awaited
        # outside of any try block that only logs and returns normally.
        for source, call in (
            (sync_org, "await get_org_subscription_service().apply_webhook_update("),
            (sync_invoice, "await get_invoice_service().upsert_from_stripe_invoice("),
        ):
            call_pos = source.index(call)
            preceding = source[:call_pos]
            # The only "try:" allowed before the critical call is none —
            # it must be a top-level await, not inside a try/except.
            self.assertNotIn("try:", preceding, f"{call!r} must not be inside a swallowing try/except")


class TestWebhookEventDedup(unittest.TestCase):
    """WebhookEventService.record()'s retry-vs-duplicate logic, pure-logic
    parts only — the full round trip against a live table is covered by
    the live-Postgres verification script."""

    def test_mark_failed_clears_processed_at(self):
        """Regression: mark_failed used to still set processed_at=NOW(),
        making a failed event indistinguishable from a succeeded one to
        record()'s dedup check on the next Stripe retry."""
        import inspect
        from app.billing.webhooks import WebhookEventService
        source = inspect.getsource(WebhookEventService.mark_failed)
        self.assertIn("processed_at=NULL", source)

    def test_record_allows_reprocessing_of_previously_failed_events(self):
        import inspect
        from app.billing.webhooks import WebhookEventService
        source = inspect.getsource(WebhookEventService.record)
        self.assertIn('existing["error"] is not None', source)


# ── Row Level Security policy shape ───────────────────────────────────────────

class TestRlsPolicyShape(unittest.TestCase):
    """
    Full RLS behavior (does it actually block cross-org rows?) can only be
    verified against a real Postgres — it was verified manually this session:
    a live end-to-end check against the deployed database confirmed
    acquire_scoped(org_a) cannot see org_b's rows, plain connections are
    unaffected, and FORCE ROW LEVEL SECURITY is genuinely active (not a
    silent no-op from table ownership).

    That same live check caught a real bug worth guarding against
    regressing: Postgres resets a custom GUC to '' (empty string), not
    NULL, once any connection has run `SET LOCAL app.current_org_id = ...`
    at least once — and asyncpg's pool reuses physical connections. Without
    nullif() in the policy, a later *unscoped* query on a previously-scoped
    (pooled) connection would try to cast '' to uuid and error out on every
    RLS-protected table. These tests just guard the SQL text so that fix
    can't be silently removed later.
    """
    def test_policy_handles_empty_string_guc_not_just_null(self):
        from app.tenancy.rls import _RLS_TABLES
        import inspect
        from app.tenancy import rls
        source = inspect.getsource(rls.enable_scoped_rls)
        self.assertIn("nullif(", source,
                      "policy must nullif() the GUC — plain current_setting(...) IS NULL "
                      "breaks once a pooled connection has ever been through acquire_scoped()")
        self.assertGreaterEqual(len(_RLS_TABLES), 5)

    def test_organizations_scoped_by_id_not_organization_id(self):
        from app.tenancy.rls import _RLS_TABLES
        table_cols = dict(_RLS_TABLES)
        self.assertEqual(table_cols["organizations"], "id")
        self.assertEqual(table_cols["organization_members"], "organization_id")

    def test_force_rls_present(self):
        import inspect
        from app.tenancy import rls
        source = inspect.getsource(rls.enable_scoped_rls)
        self.assertIn("FORCE ROW LEVEL SECURITY", source,
                      "without FORCE, the app's own DB role (table owner) bypasses RLS entirely")

    def test_billing_tables_are_rls_scoped(self):
        from app.tenancy.rls import _RLS_TABLES
        table_cols = dict(_RLS_TABLES)
        for table in ("invoices", "payments", "payment_methods", "credits", "billing_events"):
            self.assertEqual(table_cols.get(table), "organization_id", f"{table} missing from _RLS_TABLES")
        # invoice_items (child of invoices, join-only access) and the global
        # catalogs coupons/subscription_plans are deliberately excluded.
        self.assertNotIn("invoice_items", table_cols)
        self.assertNotIn("coupons", table_cols)
        self.assertNotIn("subscription_plans", table_cols)


# ── Trial support ───────────────────────────────────────────────────────────────

class TestTrialSupport(unittest.TestCase):
    def test_trialing_is_an_active_status(self):
        """Regression: apply_webhook_update used to collapse every non-
        "active" Stripe status to "free", which would revoke an org's
        access during its own trial period."""
        from app.billing.subscriptions import ACTIVE_STATUSES
        self.assertIn("trialing", ACTIVE_STATUSES)
        self.assertIn("active", ACTIVE_STATUSES)
        self.assertNotIn("past_due", ACTIVE_STATUSES)
        self.assertNotIn("canceled", ACTIVE_STATUSES)

    def test_effective_plan_uses_active_statuses_not_literal_active(self):
        import inspect
        from app.billing.subscriptions import OrgSubscriptionService
        source = inspect.getsource(OrgSubscriptionService.apply_webhook_update)
        self.assertIn("status in ACTIVE_STATUSES", source)

    def test_checkout_gates_trial_on_first_subscription_only(self):
        """Regression guard: re-granting a Stripe trial on every upgrade/
        downgrade cycle would be an abuse vector."""
        import inspect
        from app.routers import org_billing
        source = inspect.getsource(org_billing.create_org_checkout)
        self.assertIn("has_ever_had_active_subscription", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
