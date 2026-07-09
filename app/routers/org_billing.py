"""
Org-scoped billing API — Layer 12 (commercial SaaS).

POST /api/orgs/{org_id}/billing/checkout   start a Stripe Checkout session
                                            for a paid tier (starter/pro/team)
GET  /api/orgs/{org_id}/billing            current plan + subscription +
                                            usage summary, for the Billing page

Distinct from /api/subscription/* (app/routers/subscriptions.py), which is
the legacy email-scoped flat trial gate and is left untouched. This router
is the org-scoped tiered-plan system; its webhook handling lives inside the
existing /api/stripe/webhook endpoint (extended, not duplicated).
"""
from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.billing import get_usage_service
from app.billing.stripe_plans import PURCHASABLE_PLANS, price_id_for
from app.billing.subscriptions import get_org_subscription_service
from app.core.config import APP_URL
from app.tenancy import OrgContext, get_tenancy_service, org_context, require_permission

router = APIRouter(prefix="/api/orgs/{org_id}/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: str = Field(pattern="^(starter|pro|team)$")


@router.post("/checkout", status_code=201)
async def create_org_checkout(
    body: CheckoutRequest,
    ctx: OrgContext = Depends(require_permission("billing", "manage")),
):
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    price_id = price_id_for(body.plan)
    if not price_id:
        raise HTTPException(
            503,
            f"Plan {body.plan!r} has no Stripe price configured. "
            f"Set STRIPE_PRICE_ID_{body.plan.upper()}. Purchasable plans: {list(PURCHASABLE_PLANS)}",
        )

    org = await get_tenancy_service().get_organization(ctx.org_id)
    if org is None:
        raise HTTPException(404, "Organization not found")

    sub_svc = get_org_subscription_service()
    existing_customer_id = await sub_svc.get_stripe_customer_id(ctx.org_id)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=existing_customer_id or None,
            customer_email=ctx.user_email if not existing_customer_id else None,
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=ctx.org_id,
            metadata={"organization_id": ctx.org_id, "plan_id": body.plan},
            subscription_data={"metadata": {"organization_id": ctx.org_id, "plan_id": body.plan}},
            success_url=f"{APP_URL}/?org_upgraded=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{APP_URL}/?org_upgrade_canceled=1",
        )
    except Exception as e:
        raise HTTPException(400, str(e))

    if session.customer:
        await sub_svc.upsert_customer(ctx.org_id, session.customer)

    return {"url": session.url}


@router.get("")
async def get_org_billing(ctx: OrgContext = Depends(org_context)):
    sub = await get_org_subscription_service().get(ctx.org_id)
    usage = await get_usage_service().summary(ctx.org_id)
    return {
        "organization_id": ctx.org_id,
        "plan": sub["plan_id"] if sub else "free",
        "status": sub["status"] if sub else "inactive",
        "current_period_end": sub["current_period_end"].isoformat() if sub and sub["current_period_end"] else None,
        "purchasable_plans": list(PURCHASABLE_PLANS),
        "usage": usage,
    }
