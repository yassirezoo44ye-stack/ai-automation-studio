"""
Plan catalog — commercial subscription tiers and their quota limits.

Limits use -1 for "unlimited". Metrics are the canonical usage dimensions
tracked by UsageService; adding a metric here automatically makes it
enforceable everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Canonical usage metrics (one row per metric per org per period).
METRICS = (
    "tokens",                # LLM tokens consumed
    "workflow_executions",   # workflow engine runs
    "api_requests",          # authenticated API calls
    "storage_mb",            # workspace + asset storage
    "embeddings",            # vector embeddings generated
    "marketplace_purchases", # paid marketplace transactions
    "seats",                 # active members
)


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_monthly_usd: float
    limits: dict[str, int] = field(default_factory=dict)
    features: tuple[str, ...] = ()
    trial_days: int = 0


PLANS: dict[str, Plan] = {
    "free": Plan(
        id="free", name="Free", price_monthly_usd=0.0,
        limits={
            "tokens": 100_000, "workflow_executions": 50, "api_requests": 5_000,
            "storage_mb": 200, "embeddings": 1_000, "marketplace_purchases": 0, "seats": 1,
        },
        features=("community_support",),
    ),
    "starter": Plan(
        id="starter", name="Starter", price_monthly_usd=19.0,
        limits={
            "tokens": 2_000_000, "workflow_executions": 1_000, "api_requests": 100_000,
            "storage_mb": 5_000, "embeddings": 50_000, "marketplace_purchases": -1, "seats": 3,
        },
        features=("email_support", "marketplace"),
        trial_days=14,
    ),
    "pro": Plan(
        id="pro", name="Pro", price_monthly_usd=49.0,
        limits={
            "tokens": 10_000_000, "workflow_executions": 10_000, "api_requests": 1_000_000,
            "storage_mb": 50_000, "embeddings": 500_000, "marketplace_purchases": -1, "seats": 10,
        },
        features=("priority_support", "marketplace", "advanced_analytics", "sso"),
        trial_days=14,
    ),
    "team": Plan(
        id="team", name="Team", price_monthly_usd=99.0,
        limits={
            "tokens": 50_000_000, "workflow_executions": 100_000, "api_requests": 10_000_000,
            "storage_mb": 250_000, "embeddings": 5_000_000, "marketplace_purchases": -1, "seats": 25,
        },
        features=("priority_support", "marketplace", "advanced_analytics", "sso",
                  "audit_logs", "custom_roles"),
        trial_days=14,
    ),
    "enterprise": Plan(
        id="enterprise", name="Enterprise", price_monthly_usd=0.0,  # custom pricing
        limits={m: -1 for m in METRICS},
        features=("dedicated_support", "marketplace", "advanced_analytics", "sso",
                  "audit_logs", "custom_roles", "sla", "private_cloud", "custom_models"),
    ),
}


def get_plan(plan_id: str) -> Plan:
    return PLANS.get(plan_id, PLANS["free"])
