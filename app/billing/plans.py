"""
Plan catalog — commercial subscription tiers and their quota limits.

Limits use -1 for "unlimited". Metrics are the canonical usage dimensions
tracked by UsageService; adding a metric here automatically makes it
enforceable everywhere.

The Plan literals below (`_SEED_PLANS`) are no longer the runtime source of
truth — they're the idempotent seed data for the `subscription_plans`
table (see app/billing/plan_service.py), which is what `PlanService`
actually reads at runtime so plans are admin-editable without a deploy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Canonical usage metrics (one row per metric per org per period).
METRICS = (
    "tokens",                # LLM tokens consumed
    "workflow_executions",   # workflow engine runs
    "api_requests",          # authenticated API calls
    "storage_mb",            # workspace + asset storage
    "embeddings",            # vector embeddings generated
    "marketplace_purchases", # paid marketplace transactions
    "seats",                 # active members
    "active_users",          # distinct users active in the current period
    "running_agents",        # concurrent/running agent executions
)


# Canonical feature-gate catalog — the ONLY place a feature id and its
# human-readable label are defined. `app/billing/feature_gate.py` validates
# every check_feature()/has_feature() call against these keys (an id not
# listed here is a caller bug, not a plan-entitlement denial) and uses the
# labels to build error messages. Which plans grant which feature stays
# entirely inside each Plan.features tuple below (or the subscription_plans
# table at runtime) — this dict never lists plans, so there is still exactly
# one place ("does plan X include feature Y") that can answer that question.
FEATURES: dict[str, str] = {
    "community_support":  "Community support",
    "email_support":      "Email support",
    "priority_support":   "Priority support",
    "dedicated_support":  "Dedicated support",
    "marketplace":        "Marketplace",
    "advanced_analytics": "Advanced analytics",
    "sso":                "Single sign-on (SSO)",
    "audit_logs":         "Audit logs",
    "custom_roles":       "Custom roles",
    "sla":                "SLA",
    "private_cloud":      "Private cloud deployment",
    "custom_models":      "Custom AI models",
}


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_monthly_usd: float
    limits: dict[str, int] = field(default_factory=dict)
    features: tuple[str, ...] = ()
    trial_days: int = 0
    max_agents: int = -1      # resource-count cap, distinct from usage_records metrics
    max_workflows: int = -1
    stripe_price_id: Optional[str] = None
    is_purchasable: bool = True
    active: bool = True


_SEED_PLANS: dict[str, Plan] = {
    "free": Plan(
        id="free", name="Free", price_monthly_usd=0.0,
        limits={
            "tokens": 100_000, "workflow_executions": 50, "api_requests": 5_000,
            "storage_mb": 200, "embeddings": 1_000, "marketplace_purchases": 0, "seats": 1,
            "active_users": 1, "running_agents": 1,
        },
        features=("community_support",),
        max_agents=3, max_workflows=5, is_purchasable=False,
    ),
    "starter": Plan(
        id="starter", name="Starter", price_monthly_usd=19.0,
        limits={
            "tokens": 2_000_000, "workflow_executions": 1_000, "api_requests": 100_000,
            "storage_mb": 5_000, "embeddings": 50_000, "marketplace_purchases": -1, "seats": 3,
            "active_users": 3, "running_agents": 3,
        },
        features=("email_support", "marketplace"),
        trial_days=14, max_agents=10, max_workflows=20,
    ),
    "pro": Plan(
        id="pro", name="Professional", price_monthly_usd=49.0,
        limits={
            "tokens": 10_000_000, "workflow_executions": 10_000, "api_requests": 1_000_000,
            "storage_mb": 50_000, "embeddings": 500_000, "marketplace_purchases": -1, "seats": 10,
            "active_users": 10, "running_agents": 10,
        },
        features=("priority_support", "marketplace", "advanced_analytics", "sso"),
        trial_days=14, max_agents=50, max_workflows=100,
    ),
    "team": Plan(
        id="team", name="Team", price_monthly_usd=99.0,
        limits={
            "tokens": 50_000_000, "workflow_executions": 100_000, "api_requests": 10_000_000,
            "storage_mb": 250_000, "embeddings": 5_000_000, "marketplace_purchases": -1, "seats": 25,
            "active_users": 25, "running_agents": 25,
        },
        features=("priority_support", "marketplace", "advanced_analytics", "sso",
                  "audit_logs", "custom_roles"),
        trial_days=14, max_agents=200, max_workflows=500,
    ),
    "enterprise": Plan(
        id="enterprise", name="Enterprise", price_monthly_usd=0.0,  # custom pricing
        limits={m: -1 for m in METRICS},
        features=("dedicated_support", "marketplace", "advanced_analytics", "sso",
                  "audit_logs", "custom_roles", "sla", "private_cloud", "custom_models"),
        max_agents=-1, max_workflows=-1, is_purchasable=False,
    ),
}
