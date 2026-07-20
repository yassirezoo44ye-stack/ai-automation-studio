"""
FeatureGateService tests — the single source of truth for plan/subscription
entitlement checks (app/billing/feature_gate.py). Covers: allow/deny per
plan, missing organization, missing subscription, unknown plan, expired
subscription, invalid feature, the dev-only bypass (and its two independent
gates), the dynamic error-message generator, and the marketplace installer's
wiring into check_feature().

No live Postgres — every collaborator (TenancyService, PlanService,
OrgSubscriptionService) is mocked at its lazy-import call site, same
approach as tests/test_integrations.py.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def _org_id() -> str:
    return str(uuid.uuid4())


def _plan(id_: str, name: str, features: tuple = ()):
    from app.billing.plans import Plan
    return Plan(id=id_, name=name, price_monthly_usd=0.0, features=features)


FREE = _plan("free", "Free", features=("community_support",))
STARTER = _plan("starter", "Starter", features=("email_support", "marketplace"))
PRO = _plan("pro", "Professional", features=("priority_support", "marketplace", "sso"))
ENTERPRISE = _plan("enterprise", "Enterprise", features=("dedicated_support", "marketplace", "sso"))
ALL_PLANS = [FREE, STARTER, PRO, ENTERPRISE]


def _plan_service(plans: dict[str, "object"] = None):
    """Reproduces PlanService.get_plan()'s real contract: unknown ids
    silently fall back to the free plan's Plan object."""
    plans = plans or {p.id: p for p in ALL_PLANS}

    async def get_plan(plan_id):
        return plans.get(plan_id, plans["free"])

    async def list_plans():
        return list(plans.values())

    svc = MagicMock()
    svc.get_plan = AsyncMock(side_effect=get_plan)
    svc.list_plans = AsyncMock(side_effect=list_plans)
    return svc


def _org(plan="free"):
    return {"id": _org_id(), "plan": plan}


def _active_subscription(plan_id="pro", *, status="active", current_period_end=None):
    return {
        "organization_id": _org_id(), "plan_id": plan_id, "status": status,
        "current_period_end": current_period_end,
    }


def _patched(*, org, subscription=None, plans=None, env=None):
    """Context-manager bundle patching every FeatureGateService collaborator
    at its lazy-import source. `env` is a dict merged into os.environ for
    the duration (used for dev-bypass tests)."""
    tenancy = MagicMock()
    tenancy.get_organization = AsyncMock(return_value=org)
    sub_svc = MagicMock()
    sub_svc.get = AsyncMock(return_value=subscription)

    ctx = [
        patch("app.tenancy.service.get_tenancy_service", return_value=tenancy),
        patch("app.billing.plan_service.get_plan_service", return_value=_plan_service(plans)),
        patch("app.billing.subscriptions.get_org_subscription_service", return_value=sub_svc),
    ]
    if env is not None:
        ctx.append(patch.dict(os.environ, env))
    return ctx


class _MultiPatch:
    def __init__(self, patchers):
        self._patchers = patchers

    def __enter__(self):
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()


def patched(**kwargs):
    return _MultiPatch(_patched(**kwargs))


# ── Allow / deny per plan ─────────────────────────────────────────────────────

class TestPlanEntitlement:
    def test_free_denied(self):
        from app.billing.feature_gate import FeatureGateService, FeatureNotEntitledError
        with patched(org=_org("free"), env={"ENVIRONMENT": "production"}):
            with pytest.raises(FeatureNotEntitledError) as exc_info:
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))
        msg = str(exc_info.value)
        assert "Current plan: Free" in msg
        assert "Marketplace" in msg

    def test_pro_allowed(self):
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("pro"), subscription=_active_subscription("pro"),
                     env={"ENVIRONMENT": "production"}):
            run(FeatureGateService().check_feature(_org_id(), "marketplace"))  # must not raise

    def test_enterprise_allowed(self):
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("enterprise"), subscription=_active_subscription("enterprise"),
                     env={"ENVIRONMENT": "production"}):
            run(FeatureGateService().check_feature(_org_id(), "marketplace"))  # must not raise

    def test_starter_allowed_trialing_status_counts_as_active(self):
        """ACTIVE_STATUSES includes 'trialing' — a subscription still in its
        trial period must not be treated as expired."""
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("starter"), subscription=_active_subscription("starter", status="trialing"),
                     env={"ENVIRONMENT": "production"}):
            run(FeatureGateService().check_feature(_org_id(), "marketplace"))  # must not raise

    def test_denied_message_lists_every_qualifying_plan(self):
        from app.billing.feature_gate import FeatureGateService, FeatureNotEntitledError
        with patched(org=_org("free"), env={"ENVIRONMENT": "production"}):
            with pytest.raises(FeatureNotEntitledError) as exc_info:
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))
        msg = str(exc_info.value)
        for name in ("Starter", "Professional", "Enterprise"):
            assert name in msg, msg


# ── Missing organization ──────────────────────────────────────────────────────

class TestMissingOrganization:
    def test_missing_organization_raises_distinctly(self):
        from app.billing.feature_gate import FeatureGateService, OrganizationNotFoundError
        with patched(org=None, env={"ENVIRONMENT": "production"}):
            with pytest.raises(OrganizationNotFoundError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_missing_organization_not_bypassed_in_dev(self):
        """The dev bypass skips plan/entitlement checks, not basic
        referential integrity — a nonexistent org is a caller bug, not
        something a developer wants silently waved through."""
        from app.billing.feature_gate import FeatureGateService, OrganizationNotFoundError
        with patched(org=None, env={"ENVIRONMENT": "development", "FEATURE_GATE_DEV_BYPASS": "true"}):
            with pytest.raises(OrganizationNotFoundError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))


# ── Missing subscription ──────────────────────────────────────────────────────

class TestMissingSubscription:
    def test_missing_subscription_for_paid_plan(self):
        from app.billing.feature_gate import FeatureGateService, MissingSubscriptionError
        with patched(org=_org("pro"), subscription=None, env={"ENVIRONMENT": "production"}):
            with pytest.raises(MissingSubscriptionError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_missing_subscription_still_grants_free_tier_features(self):
        """A missing subscription collapses the org to Free's entitlements
        — it must not deny a feature Free itself already grants."""
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("pro"), subscription=None, env={"ENVIRONMENT": "production"}):
            run(FeatureGateService().check_feature(_org_id(), "community_support"))  # must not raise


# ── Unknown plan ───────────────────────────────────────────────────────────────

class TestUnknownPlan:
    def test_unknown_plan_id_raises_distinctly(self):
        from app.billing.feature_gate import FeatureGateService, UnknownPlanError
        with patched(org=_org("not-a-real-plan"), env={"ENVIRONMENT": "production"}):
            with pytest.raises(UnknownPlanError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_unknown_plan_still_grants_free_tier_features(self):
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("not-a-real-plan"), env={"ENVIRONMENT": "production"}):
            run(FeatureGateService().check_feature(_org_id(), "community_support"))  # must not raise


# ── Expired subscription ──────────────────────────────────────────────────────

class TestExpiredSubscription:
    def test_canceled_status_denied(self):
        from app.billing.feature_gate import FeatureGateService, SubscriptionExpiredError
        with patched(org=_org("pro"), subscription=_active_subscription("pro", status="canceled"),
                     env={"ENVIRONMENT": "production"}):
            with pytest.raises(SubscriptionExpiredError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_past_period_end_denied_even_if_status_still_active(self):
        """A stale 'active' status with a period_end in the past (webhook
        lag) must still be treated as expired — never trust status alone."""
        from app.billing.feature_gate import FeatureGateService, SubscriptionExpiredError
        past = datetime.now(timezone.utc) - timedelta(days=1)
        with patched(org=_org("pro"), subscription=_active_subscription("pro", status="active", current_period_end=past),
                     env={"ENVIRONMENT": "production"}):
            with pytest.raises(SubscriptionExpiredError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_future_period_end_allowed(self):
        from app.billing.feature_gate import FeatureGateService
        future = datetime.now(timezone.utc) + timedelta(days=10)
        with patched(org=_org("pro"), subscription=_active_subscription("pro", status="active", current_period_end=future),
                     env={"ENVIRONMENT": "production"}):
            run(FeatureGateService().check_feature(_org_id(), "marketplace"))  # must not raise

    def test_naive_datetime_period_end_handled(self):
        """Defensive: some drivers/mocks may hand back a naive datetime
        instead of asyncpg's normal tz-aware one — must not crash."""
        from app.billing.feature_gate import FeatureGateService, SubscriptionExpiredError
        past_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        with patched(org=_org("pro"), subscription=_active_subscription("pro", status="active", current_period_end=past_naive),
                     env={"ENVIRONMENT": "production"}):
            with pytest.raises(SubscriptionExpiredError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_expired_subscription_still_grants_free_tier_features(self):
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("pro"), subscription=_active_subscription("pro", status="canceled"),
                     env={"ENVIRONMENT": "production"}):
            run(FeatureGateService().check_feature(_org_id(), "community_support"))  # must not raise


# ── Invalid feature ────────────────────────────────────────────────────────────

class TestInvalidFeature:
    def test_unknown_feature_id_always_raises(self):
        from app.billing.feature_gate import FeatureGateService, UnknownFeatureError
        with patched(org=_org("enterprise"), subscription=_active_subscription("enterprise"),
                     env={"ENVIRONMENT": "production"}):
            with pytest.raises(UnknownFeatureError):
                run(FeatureGateService().check_feature(_org_id(), "not-a-real-feature"))

    def test_unknown_feature_id_not_bypassed_in_dev(self):
        """A typo'd feature id is a caller bug, not an entitlement question
        — the dev bypass must not paper over it."""
        from app.billing.feature_gate import FeatureGateService, UnknownFeatureError
        with patched(org=_org("free"), env={"ENVIRONMENT": "development", "FEATURE_GATE_DEV_BYPASS": "true"}):
            with pytest.raises(UnknownFeatureError):
                run(FeatureGateService().check_feature(_org_id(), "not-a-real-feature"))


# ── Development bypass ─────────────────────────────────────────────────────────

class TestDevBypass:
    def test_bypass_enabled_in_dev_allows_free_org(self):
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("free"), env={"ENVIRONMENT": "development", "FEATURE_GATE_DEV_BYPASS": "true"}):
            run(FeatureGateService().check_feature(_org_id(), "marketplace"))  # must not raise

    def test_bypass_disabled_in_dev_still_denies(self):
        from app.billing.feature_gate import FeatureGateService, FeatureNotEntitledError
        with patched(org=_org("free"), env={"ENVIRONMENT": "development", "FEATURE_GATE_DEV_BYPASS": "false"}):
            with pytest.raises(FeatureNotEntitledError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_bypass_unset_in_dev_still_denies(self):
        from app.billing.feature_gate import FeatureGateService, FeatureNotEntitledError
        with patched(org=_org("free"), env={"ENVIRONMENT": "development"}):
            with pytest.raises(FeatureNotEntitledError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_production_ignores_bypass_flag(self):
        """The core safety property: FEATURE_GATE_DEV_BYPASS=true alone,
        with no ENVIRONMENT=development, must never grant access."""
        from app.billing.feature_gate import FeatureGateService, FeatureNotEntitledError
        with patched(org=_org("free"), env={"ENVIRONMENT": "production", "FEATURE_GATE_DEV_BYPASS": "true"}):
            with pytest.raises(FeatureNotEntitledError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_unset_environment_defaults_to_production_and_ignores_bypass(self, monkeypatch):
        """Fail-safe default: no ENVIRONMENT var set at all must behave
        exactly like ENVIRONMENT=production."""
        from app.billing.feature_gate import FeatureGateService, FeatureNotEntitledError
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("FEATURE_GATE_DEV_BYPASS", "true")
        with patched(org=_org("free")):
            with pytest.raises(FeatureNotEntitledError):
                run(FeatureGateService().check_feature(_org_id(), "marketplace"))

    def test_dev_bypass_active_truth_table(self):
        from app.billing.feature_gate import dev_bypass_active
        cases = [
            ({"ENVIRONMENT": "development", "FEATURE_GATE_DEV_BYPASS": "true"}, True),
            ({"ENVIRONMENT": "development", "FEATURE_GATE_DEV_BYPASS": "false"}, False),
            ({"ENVIRONMENT": "production", "FEATURE_GATE_DEV_BYPASS": "true"}, False),
            ({"ENVIRONMENT": "production", "FEATURE_GATE_DEV_BYPASS": "false"}, False),
        ]
        for env, expected in cases:
            with patch.dict(os.environ, env):
                assert dev_bypass_active() is expected, env


# ── has_feature() non-raising wrapper ────────────────────────────────────────

class TestHasFeature:
    def test_has_feature_returns_allowed_true(self):
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("enterprise"), subscription=_active_subscription("enterprise"),
                     env={"ENVIRONMENT": "production"}):
            result = run(FeatureGateService().has_feature(_org_id(), "marketplace"))
        assert result.allowed is True
        assert result.reason is None

    def test_has_feature_returns_allowed_false_with_reason(self):
        from app.billing.feature_gate import FeatureGateService
        with patched(org=_org("free"), env={"ENVIRONMENT": "production"}):
            result = run(FeatureGateService().has_feature(_org_id(), "marketplace"))
        assert result.allowed is False
        assert result.reason and "Marketplace" in result.reason


# ── Catalog integrity ──────────────────────────────────────────────────────────

class TestFeatureCatalog:
    def test_every_plan_feature_is_in_the_catalog(self):
        """Regression guard: a feature id referenced by any seed plan but
        missing from FEATURES would silently produce an unlabeled/ugly
        error message (or, worse, be un-checkable via check_feature at all
        since it would raise UnknownFeatureError for a feature that IS
        actually granted to some plan)."""
        from app.billing.plans import _SEED_PLANS, FEATURES
        for plan in _SEED_PLANS.values():
            for feature in plan.features:
                assert feature in FEATURES, f"{plan.id} grants undeclared feature {feature!r}"

    def test_marketplace_is_not_on_free(self):
        """Documents the actual root cause of the reported bug: Free
        legitimately does not include Marketplace by plan design — this
        is not itself the defect the bypass/messaging work fixes."""
        from app.billing.plans import _SEED_PLANS
        assert "marketplace" not in _SEED_PLANS["free"].features
        for plan_id in ("starter", "pro", "team", "enterprise"):
            assert "marketplace" in _SEED_PLANS[plan_id].features


# ── Message helper ──────────────────────────────────────────────────────────────

class TestJoinOr:
    def test_single(self):
        from app.billing.feature_gate import _join_or
        assert _join_or(["Pro"]) == "Pro"

    def test_pair(self):
        from app.billing.feature_gate import _join_or
        assert _join_or(["Pro", "Enterprise"]) == "Pro or Enterprise"

    def test_three_or_more(self):
        from app.billing.feature_gate import _join_or
        assert _join_or(["Starter", "Pro", "Enterprise"]) == "Starter, Pro, or Enterprise"


# ── Marketplace installer wiring ─────────────────────────────────────────────

class TestInstallerWiring:
    def test_stage_2_delegates_to_feature_gate_service(self):
        """The installer must not hand-roll its own plan.features check —
        it delegates to the single centralized service."""
        import inspect
        from app.marketplace import installer
        source = inspect.getsource(installer.InstallationPipeline._install_inner)
        assert "check_feature" in source
        assert "plan.features" not in source
        assert '"marketplace" not in' not in source

    def test_plan_feature_not_enabled_error_wraps_feature_gate_message(self):
        from app.marketplace.installer import PlanFeatureNotEnabledError
        err = PlanFeatureNotEnabledError("org-1", "Marketplace requires a Pro subscription. Current plan: Free.")
        assert "Marketplace requires a Pro subscription" in str(err)
        assert err.org_id == "org-1"

    def test_router_maps_plan_feature_not_enabled_to_402(self):
        from app.routers.marketplace import _INSTALL_ERROR_STATUS
        from app.marketplace.installer import PlanFeatureNotEnabledError
        assert _INSTALL_ERROR_STATUS[PlanFeatureNotEnabledError] == 402
