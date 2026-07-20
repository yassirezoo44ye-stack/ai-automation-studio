"""
FeatureGateService — the single source of truth for "is organization X
entitled to feature Y right now." Every caller that needs a plan-gated
feature check (Marketplace today; SSO/audit-logs/advanced-analytics/etc.
tomorrow) goes through check_feature()/has_feature() instead of hand-rolling
its own `"x" not in plan.features` check.

What it does NOT own:
  - Plan definitions (name/price/limits/features) — that's
    app/billing/plans.py's `_SEED_PLANS` / the `subscription_plans` table
    via PlanService. This module only reads them.
  - Usage/quota enforcement (tokens, workflow_executions, ...) — that's
    UsageService.check_quota(), a different axis (how much) from feature
    gating (whether at all). See app/core/org_quota.py for the pattern of
    the two being checked side by side.
  - Org/subscription persistence — TenancyService and
    OrgSubscriptionService (app/billing/subscriptions.py) already own that;
    this module only reads through them.

What it does own: turning "org row + subscription row + plan catalog" into
one allow/deny decision with a specific, actionable reason, plus the one
dev-only bypass switch for the whole platform.

── Effective-plan resolution ──────────────────────────────────────────────
organizations.plan is kept in sync with the org's real subscription by the
Stripe webhook (OrgSubscriptionService.apply_webhook_update — an inactive/
cancelled subscription writes plan='free' back onto the org). In the
common case that means organizations.plan can be trusted directly. This
module does not assume that always held true — it cross-checks a claimed
paid plan against the actual org_subscriptions row (status + period end)
before granting anything, so a webhook that never fired, a stale row, or
a directly-edited plan column can't silently grant paid-tier access. Any
ambiguity (unknown plan id, missing subscription, expired subscription)
collapses to the Free plan's entitlements — never to the claimed plan's.

── Dev bypass ──────────────────────────────────────────────────────────────
See dev_bypass_active() below. Gated on TWO independent conditions
(ENVIRONMENT=development AND FEATURE_GATE_DEV_BYPASS=true) so a single
misconfigured flag can never relax a production deployment.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.billing.plans import FEATURES, Plan

log = logging.getLogger(__name__)


# ── Dev bypass ───────────────────────────────────────────────────────────────

def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def dev_bypass_active() -> bool:
    """True only when ENVIRONMENT=development AND FEATURE_GATE_DEV_BYPASS is
    truthy. Both are read live (no caching), so this can never be baked into
    a stale process-start value and a lone misconfigured flag — either one
    on its own — can never activate it in production."""
    from app.core.config import is_development
    return is_development() and _bool_env("FEATURE_GATE_DEV_BYPASS")


# ── Exceptions ───────────────────────────────────────────────────────────────

class FeatureGateError(Exception):
    """Base class for every typed feature-gate denial. Callers that only
    care about "was this allowed" can catch this one type; callers that want
    to render a specific status code (see app/routers/marketplace.py's
    _INSTALL_ERROR_STATUS) can catch the specific subclasses below."""


class OrganizationNotFoundError(FeatureGateError):
    def __init__(self, org_id: str):
        super().__init__(f"Organization {org_id} was not found.")
        self.org_id = org_id


class UnknownFeatureError(FeatureGateError):
    """The caller asked about a feature id that isn't in the FEATURES
    catalog — a programmer error (typo, or a feature that was never
    registered), not an entitlement denial."""

    def __init__(self, feature: str):
        known = ", ".join(sorted(FEATURES)) or "(none registered)"
        super().__init__(f"Unknown feature {feature!r}. Known features: {known}.")
        self.feature = feature


class UnknownPlanError(FeatureGateError):
    def __init__(self, org_id: str, plan_id: str):
        super().__init__(
            f"Organization {org_id} is assigned an unrecognized plan {plan_id!r}. "
            f"Treating it as the Free plan until this is corrected."
        )
        self.org_id, self.plan_id = org_id, plan_id


class MissingSubscriptionError(FeatureGateError):
    def __init__(self, org_id: str, plan_id: str):
        super().__init__(
            f"Organization {org_id} is assigned the {plan_id!r} plan but has no "
            f"subscription on record. Treating it as the Free plan until a "
            f"subscription is attached."
        )
        self.org_id, self.plan_id = org_id, plan_id


class SubscriptionExpiredError(FeatureGateError):
    def __init__(self, org_id: str, plan_id: str, status: str):
        super().__init__(
            f"Organization {org_id}'s subscription to the {plan_id!r} plan is "
            f"no longer active (status: {status!r}). Treating it as the Free "
            f"plan until the subscription is renewed."
        )
        self.org_id, self.plan_id, self.status = org_id, plan_id, status


class FeatureNotEntitledError(FeatureGateError):
    """The real, common-case denial: the org's plan was resolved cleanly,
    it just doesn't include this feature."""

    def __init__(self, org_id: str, feature: str, current_plan: Plan, all_plans: list[Plan]):
        label = FEATURES.get(feature, feature)
        qualifying = [p.name for p in all_plans if feature in p.features and p.id != current_plan.id]
        if qualifying:
            message = (
                f"{label} requires a {_join_or(qualifying)} subscription. "
                f"Current plan: {current_plan.name}."
            )
        else:
            message = f"{label} is not available on any currently active plan."
        super().__init__(message)
        self.org_id, self.feature, self.current_plan_id = org_id, feature, current_plan.id


def _join_or(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} or {names[1]}"
    return f"{', '.join(names[:-1])}, or {names[-1]}"


# ── Result (for has_feature()'s non-raising callers) ─────────────────────────

@dataclass(frozen=True)
class FeatureCheckResult:
    allowed: bool
    reason: Optional[str] = None


# ── Service ──────────────────────────────────────────────────────────────────

class FeatureGateService:
    """Stateless orchestration over TenancyService, PlanService, and
    OrgSubscriptionService — no pool of its own, no persistence. Collaborator
    lookups are done via lazy imports of their existing singletons so tests
    can patch each one independently (see tests/test_feature_gate.py)."""

    async def check_feature(self, org_id: str, feature: str) -> None:
        """Raises a FeatureGateError subclass on denial; returns None
        (silently) when the org is entitled to `feature` right now."""
        if feature not in FEATURES:
            raise UnknownFeatureError(feature)

        from app.tenancy.service import get_tenancy_service
        org = await get_tenancy_service().get_organization(org_id)
        if org is None:
            raise OrganizationNotFoundError(org_id)

        if dev_bypass_active():
            log.info("feature gate bypassed (dev mode): org=%s feature=%s", org_id, feature)
            return

        from app.billing.plan_service import get_plan_service
        plan_service = get_plan_service()
        free_plan = await plan_service.get_plan("free")
        claimed_plan_id = org.get("plan") or "free"

        if claimed_plan_id == "free":
            effective_plan = free_plan
        else:
            resolved = await plan_service.get_plan(claimed_plan_id)
            if resolved.id != claimed_plan_id:
                # PlanService silently fell back to "free" for an id it
                # doesn't recognize — surface that distinctly rather than
                # quietly reusing its fallback.
                if feature in free_plan.features:
                    return
                raise UnknownPlanError(org_id, claimed_plan_id)

            from app.billing.subscriptions import ACTIVE_STATUSES, get_org_subscription_service
            sub = await get_org_subscription_service().get(org_id)
            if sub is None:
                if feature in free_plan.features:
                    return
                raise MissingSubscriptionError(org_id, claimed_plan_id)

            expired_status = sub["status"] not in ACTIVE_STATUSES
            period_end = sub.get("current_period_end")
            expired_period = period_end is not None and _as_aware_utc(period_end) < datetime.now(timezone.utc)
            if expired_status or expired_period:
                if feature in free_plan.features:
                    return
                raise SubscriptionExpiredError(org_id, claimed_plan_id, sub["status"])

            effective_plan = resolved

        if feature not in effective_plan.features:
            all_plans = await plan_service.list_plans()
            raise FeatureNotEntitledError(org_id, feature, effective_plan, all_plans)

    async def has_feature(self, org_id: str, feature: str) -> FeatureCheckResult:
        """Non-raising variant for callers that want to branch on the
        result (e.g. an entitlements API for the frontend) instead of
        handling an exception."""
        try:
            await self.check_feature(org_id, feature)
        except FeatureGateError as exc:
            return FeatureCheckResult(allowed=False, reason=str(exc))
        return FeatureCheckResult(allowed=True)


def _as_aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


_service: Optional[FeatureGateService] = None


def get_feature_gate_service() -> FeatureGateService:
    global _service
    if _service is None:
        _service = FeatureGateService()
    return _service


async def check_feature(org_id: str, feature: str) -> None:
    """Module-level convenience wrapper — the call sites this module was
    written for (installer.py, future callers) don't need a service
    instance; they need one function."""
    await get_feature_gate_service().check_feature(org_id, feature)


async def has_feature(org_id: str, feature: str) -> FeatureCheckResult:
    return await get_feature_gate_service().has_feature(org_id, feature)
