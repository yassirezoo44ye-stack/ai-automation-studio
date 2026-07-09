import json
from datetime import datetime

import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import make_token, verify_token
from app.core.config import STRIPE_PRICE_ID, APP_URL
from app.core.db import get_pool
from app.core.security import check_rate_limit

router = APIRouter(tags=["subscriptions"])


class CheckoutRequest(BaseModel):
    email: str


@router.post("/api/subscription/checkout")
async def create_checkout(req: CheckoutRequest):
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer_email=req.email,
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            success_url=f"{APP_URL}/?subscribed=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{APP_URL}/?canceled=1",
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/api/subscription/status")
async def subscription_status(email: str, request: Request):
    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not check_rate_limit(f"sub:{client_ip}", max_calls=10, window=60):
        raise HTTPException(429, "Too many requests. Try again later.")

    async with get_pool().acquire() as conn:
        sub = await conn.fetchrow(
            "SELECT status, current_period_end FROM subscriptions WHERE email=$1", email
        )
        if sub and sub["status"] == "active" and (
            sub["current_period_end"] is None or sub["current_period_end"] > datetime.utcnow()
        ):
            return {"active": True, "trial": False, "token": make_token(email, False, 0)}

        trial = await conn.fetchrow("SELECT started_at FROM trials WHERE email=$1", email)
        if not trial:
            await conn.execute(
                "INSERT INTO trials (email) VALUES ($1) ON CONFLICT DO NOTHING", email
            )
            trial = await conn.fetchrow("SELECT started_at FROM trials WHERE email=$1", email)

        elapsed = (datetime.utcnow() - trial["started_at"].replace(tzinfo=None)).days
        days_remaining = max(0, 7 - elapsed)
        if days_remaining > 0:
            return {
                "active": True,
                "trial": True,
                "days_remaining": days_remaining,
                "token": make_token(email, True, days_remaining),
            }

    return {"active": False, "trial_expired": True}


@router.post("/api/subscription/verify")
async def verify_session(request: Request):
    body = await request.json()
    token = body.get("token", "")
    payload = verify_token(token)
    if not payload:
        return {"valid": False}
    refreshed = make_token(payload["e"], payload.get("trial", False), payload.get("dr", 0))
    return {
        "valid": True,
        "trial": payload.get("trial", False),
        "days_remaining": payload.get("dr", 0),
        "token": refreshed,
    }


@router.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    from app.core.config import STRIPE_WEBHOOK_SECRET
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    except Exception:
        raise HTTPException(400, "Malformed webhook")

    async with get_pool().acquire() as conn:
        if event["type"] == "checkout.session.completed":
            s = event["data"]["object"]
            email = s.get("customer_email") or ""
            cust_id = s.get("customer", "")
            sub_id = s.get("subscription", "")
            if email:
                await conn.execute('''
                    INSERT INTO subscriptions (email, stripe_customer_id, stripe_subscription_id, status)
                    VALUES ($1, $2, $3, 'active')
                    ON CONFLICT (email) DO UPDATE
                    SET stripe_customer_id=$2, stripe_subscription_id=$3, status='active', updated_at=NOW()
                ''', email, cust_id, sub_id)

            # Org-scoped tiered plan (only present when checkout was started
            # via POST /api/orgs/{org_id}/billing/checkout).
            org_id = (s.get("metadata") or {}).get("organization_id")
            plan_id = (s.get("metadata") or {}).get("plan_id")
            if org_id and plan_id:
                await _sync_org_subscription(
                    organization_id=org_id, plan_id=plan_id, status="active",
                    stripe_customer_id=cust_id, stripe_subscription_id=sub_id,
                    current_period_end=None,
                )

        elif event["type"] in ("customer.subscription.updated", "customer.subscription.deleted"):
            sub = event["data"]["object"]
            sub_id = sub["id"]
            status = "active" if sub["status"] == "active" else "inactive"
            period_end = datetime.utcfromtimestamp(sub.get("current_period_end", 0))
            await conn.execute('''
                UPDATE subscriptions SET status=$1, current_period_end=$2, updated_at=NOW()
                WHERE stripe_subscription_id=$3
            ''', status, period_end, sub_id)

            org_id = (sub.get("metadata") or {}).get("organization_id")
            plan_id = (sub.get("metadata") or {}).get("plan_id")
            if org_id and plan_id:
                await _sync_org_subscription(
                    organization_id=org_id, plan_id=plan_id, status=status,
                    stripe_customer_id=sub.get("customer"), stripe_subscription_id=sub_id,
                    current_period_end=period_end,
                )

    return {"received": True}


async def _sync_org_subscription(
    *, organization_id: str, plan_id: str, status: str,
    stripe_customer_id: str | None, stripe_subscription_id: str | None,
    current_period_end,
) -> None:
    """Best-effort: a Stripe webhook must never 500 because of the newer
    org-billing system, so failures here are logged, not raised."""
    try:
        from app.billing.subscriptions import get_org_subscription_service
        await get_org_subscription_service().apply_webhook_update(
            organization_id=organization_id, plan_id=plan_id, status=status,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            current_period_end=current_period_end,
        )
        from app.core.events import get_event_bus
        await get_event_bus().publish(
            "billing.updated", {"plan": plan_id, "status": status},
            organization_id=organization_id,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "org subscription sync failed for org=%s", organization_id
        )
