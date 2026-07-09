"""
Plan <-> Stripe Price ID mapping for org-scoped tiered billing.

Kept separate from plans.py so the plan catalog (limits/features) stays
Stripe-agnostic and testable without env vars. Enterprise has no Stripe
price — it's contact-sales, activated by an admin via usage_limits
overrides or a manual `organizations.plan` update.
"""
from __future__ import annotations

from app.core.config import (
    STRIPE_PRICE_ID_STARTER, STRIPE_PRICE_ID_PRO, STRIPE_PRICE_ID_TEAM,
)

PLAN_TO_PRICE: dict[str, str] = {
    "starter": STRIPE_PRICE_ID_STARTER,
    "pro":     STRIPE_PRICE_ID_PRO,
    "team":    STRIPE_PRICE_ID_TEAM,
}

PRICE_TO_PLAN: dict[str, str] = {v: k for k, v in PLAN_TO_PRICE.items() if v}

PURCHASABLE_PLANS = tuple(k for k, v in PLAN_TO_PRICE.items() if v)


def price_id_for(plan_id: str) -> str | None:
    return PLAN_TO_PRICE.get(plan_id) or None


def plan_for_price(price_id: str) -> str | None:
    return PRICE_TO_PLAN.get(price_id)
