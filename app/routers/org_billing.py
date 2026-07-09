"""
Org-scoped billing API — Layer 12 (commercial SaaS).

POST /api/orgs/{org_id}/billing/checkout             start a Stripe Checkout
                                                       session for a paid tier
GET  /api/orgs/{org_id}/billing                       current plan + subscription
                                                       + usage summary
POST /api/orgs/{org_id}/billing/portal                Stripe Customer Portal
                                                       session (manage/cancel/
                                                       payment method)
GET  /api/orgs/{org_id}/billing/invoices              billing history: invoices
GET  /api/orgs/{org_id}/billing/invoices/{invoice_id} one invoice + line items
GET  /api/orgs/{org_id}/billing/payments              billing history: payments
GET  /api/orgs/{org_id}/billing/payment-methods       cached payment methods
POST /api/orgs/{org_id}/billing/payment-methods/sync  refresh from Stripe
GET  /api/orgs/{org_id}/billing/credits               credit balance + ledger
POST /api/orgs/{org_id}/billing/credits                grant credit (owner only)

Distinct from /api/subscription/* (app/routers/subscriptions.py), which is
the legacy email-scoped flat trial gate and is left untouched. This router
is the org-scoped tiered-plan system; its webhook handling lives inside the
existing /api/stripe/webhook endpoint (extended, not duplicated).

Read endpoints below use plain `org_context` (any member sees their own
org's billing history) — there's no explicit ("billing","read") permission
row seeded for any role, so this resolves via the ("*","read") wildcard
every role already has, matching how GET /billing already works.
"""
from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.billing import (
    NoStripeCustomer, create_portal_session, get_credit_service,
    get_invoice_service, get_payment_method_service, get_plan_service, get_usage_service,
)
from app.billing.stripe_plans import PURCHASABLE_PLANS, price_id_for
from app.billing.subscriptions import ACTIVE_STATUSES, get_org_subscription_service
from app.core.config import APP_URL
from app.core.rate_limit import check_rate_limit
from app.tenancy import OrgContext, get_tenancy_service, org_context, require_permission

router = APIRouter(prefix="/api/orgs/{org_id}/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: str = Field(pattern="^(starter|pro|team)$")


class GrantCreditRequest(BaseModel):
    amount_usd: float = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


@router.post("/checkout", status_code=201)
async def create_org_checkout(
    body: CheckoutRequest,
    ctx: OrgContext = Depends(require_permission("billing", "manage")),
):
    if not check_rate_limit(f"billing_checkout:{ctx.org_id}", max_calls=5, window=60):
        raise HTTPException(429, "Too many checkout attempts — try again shortly.")
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

    # Trial only on an org's first real Stripe subscription — re-granting a
    # trial on every upgrade/downgrade cycle would be an abuse vector.
    plan = await get_plan_service().get_plan(body.plan)
    subscription_data = {"metadata": {"organization_id": ctx.org_id, "plan_id": body.plan}}
    if plan.trial_days and not await sub_svc.has_ever_had_active_subscription(ctx.org_id):
        subscription_data["trial_period_days"] = plan.trial_days

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=existing_customer_id or None,
            customer_email=ctx.user_email if not existing_customer_id else None,
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=ctx.org_id,
            metadata={"organization_id": ctx.org_id, "plan_id": body.plan},
            subscription_data=subscription_data,
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
    status = sub["status"] if sub else "inactive"
    return {
        "organization_id": ctx.org_id,
        "plan": sub["plan_id"] if sub else "free",
        "status": status,
        "has_access": status in ACTIVE_STATUSES,
        "current_period_end": sub["current_period_end"].isoformat() if sub and sub["current_period_end"] else None,
        "purchasable_plans": list(PURCHASABLE_PLANS),
        "usage": usage,
    }


@router.post("/portal")
async def create_billing_portal_session(
    ctx: OrgContext = Depends(require_permission("billing", "manage")),
):
    if not check_rate_limit(f"billing_portal:{ctx.org_id}", max_calls=5, window=60):
        raise HTTPException(429, "Too many requests — try again shortly.")
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    try:
        url = await create_portal_session(ctx.org_id, return_url=f"{APP_URL}/?org_billing=1")
    except NoStripeCustomer:
        raise HTTPException(404, "This organization has no billing account yet — subscribe first.")
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"url": url}


def _iso(dt):
    return dt.isoformat() if dt else None


def _invoice_out(inv: dict) -> dict:
    out = {
        "id": str(inv["id"]), "stripe_invoice_id": inv["stripe_invoice_id"],
        "status": inv["status"], "amount_due_cents": inv["amount_due_cents"],
        "amount_paid_cents": inv["amount_paid_cents"], "currency": inv["currency"],
        "hosted_invoice_url": inv["hosted_invoice_url"], "invoice_pdf_url": inv["invoice_pdf_url"],
        "period_start": _iso(inv["period_start"]), "period_end": _iso(inv["period_end"]),
        "paid_at": _iso(inv["paid_at"]), "created_at": _iso(inv["created_at"]),
    }
    if "items" in inv:
        out["items"] = [
            {"description": i["description"], "quantity": i["quantity"],
             "unit_amount_cents": i["unit_amount_cents"], "amount_cents": i["amount_cents"]}
            for i in inv["items"]
        ]
    return out


@router.get("/invoices")
async def list_invoices(ctx: OrgContext = Depends(org_context)):
    svc = get_invoice_service()
    invoices = await svc.list_for_org(ctx.org_id)
    if not invoices:
        customer_id = await get_org_subscription_service().get_stripe_customer_id(ctx.org_id)
        if customer_id and stripe.api_key:
            await svc.backfill_from_stripe(ctx.org_id, customer_id)
            invoices = await svc.list_for_org(ctx.org_id)
    return {"invoices": [_invoice_out(i) for i in invoices]}


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, ctx: OrgContext = Depends(org_context)):
    invoice = await get_invoice_service().get(ctx.org_id, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found")
    return _invoice_out(invoice)


@router.get("/payments")
async def list_payments(ctx: OrgContext = Depends(org_context)):
    payments = await get_invoice_service().list_payments_for_org(ctx.org_id)
    return {"payments": [
        {"id": str(p["id"]), "status": p["status"], "amount_cents": p["amount_cents"],
         "currency": p["currency"], "failure_message": p["failure_message"],
         "created_at": _iso(p["created_at"])}
        for p in payments
    ]}


def _payment_method_out(pm: dict) -> dict:
    return {
        "id": str(pm["id"]), "brand": pm["brand"], "last4": pm["last4"],
        "exp_month": pm["exp_month"], "exp_year": pm["exp_year"],
        "is_default": pm["is_default"],
    }


@router.get("/payment-methods")
async def list_payment_methods(ctx: OrgContext = Depends(org_context)):
    svc = get_payment_method_service()
    methods = await svc.list_for_org(ctx.org_id)
    if not methods:
        customer_id = await get_org_subscription_service().get_stripe_customer_id(ctx.org_id)
        if customer_id and stripe.api_key:
            methods = await svc.sync_for_org(ctx.org_id)
    return {"payment_methods": [_payment_method_out(m) for m in methods]}


@router.post("/payment-methods/sync")
async def sync_payment_methods(ctx: OrgContext = Depends(require_permission("billing", "manage"))):
    methods = await get_payment_method_service().sync_for_org(ctx.org_id)
    return {"payment_methods": [_payment_method_out(m) for m in methods]}


@router.get("/credits")
async def get_credits(ctx: OrgContext = Depends(org_context)):
    svc = get_credit_service()
    balance_cents = await svc.get_balance_cents(ctx.org_id)
    ledger = await svc.list_ledger(ctx.org_id)
    return {
        "balance_usd": balance_cents / 100,
        "ledger": [
            {"id": str(c["id"]), "amount_usd": c["amount_cents"] / 100, "reason": c["reason"],
             "created_at": _iso(c["created_at"])}
            for c in ledger
        ],
    }


@router.post("/credits", status_code=201)
async def grant_credit(
    body: GrantCreditRequest,
    ctx: OrgContext = Depends(require_permission("billing", "manage")),
):
    # Credit-granting is financially sensitive enough to warrant a stricter
    # check than the generic billing:manage permission any admin holds.
    if ctx.role != "owner":
        raise HTTPException(403, "Only the organization owner can grant credit")
    row = await get_credit_service().grant(
        ctx.org_id, round(body.amount_usd * 100), body.reason, actor_id=ctx.user_id,
    )
    try:
        await get_tenancy_service().log_activity(
            ctx.org_id, ctx.user_id, "billing.credit_granted",
            resource="credit", resource_id=str(row["id"]),
            details={"amount_usd": body.amount_usd, "reason": body.reason},
        )
    except Exception:
        pass
    return {"id": str(row["id"]), "amount_usd": row["amount_cents"] / 100, "reason": row["reason"]}
