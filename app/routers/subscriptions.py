import json
import logging
from datetime import datetime

import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import make_token, verify_token
from app.core.config import STRIPE_PRICE_ID, APP_URL
from app.core.db import get_pool
from app.core.security import check_rate_limit

log = logging.getLogger(__name__)

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

    from app.billing import get_webhook_event_service
    wh_svc = get_webhook_event_service()
    is_new = await wh_svc.record(
        stripe_event_id=event["id"], event_type=event["type"], payload=event,
    )
    if not is_new:
        return {"received": True, "duplicate": True}

    try:
        await _dispatch_webhook_event(event)
    except Exception as exc:
        await wh_svc.mark_failed(event["id"], str(exc))
        log.exception("webhook dispatch failed for event=%s type=%s", event["id"], event["type"])
        # Non-2xx so Stripe retries this event — safe to re-run because
        # every write inside _dispatch_webhook_event is an idempotent
        # upsert, and record() above will treat this same event id as
        # unfinished work (not a duplicate) on the retry.
        raise HTTPException(500, "Webhook processing failed — will be retried")

    await wh_svc.mark_processed(event["id"])
    return {"received": True}


async def _dispatch_webhook_event(event: dict) -> None:
    event_type = event["type"]

    async with get_pool().acquire() as conn:
        if event_type == "checkout.session.completed":
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

        elif event_type in (
            "customer.subscription.created", "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            sub = event["data"]["object"]
            sub_id = sub["id"]
            # Legacy flat-rate table keeps its existing binary active/inactive
            # contract unchanged (it predates trials and its own status read
            # at /api/subscription/status does a strict "active" check) — only
            # the org-tiered system (below) gets the real Stripe status, since
            # that's the system trials actually apply to.
            legacy_status = "active" if sub["status"] == "active" else "inactive"
            period_end = datetime.utcfromtimestamp(sub.get("current_period_end", 0))
            await conn.execute('''
                UPDATE subscriptions SET status=$1, current_period_end=$2, updated_at=NOW()
                WHERE stripe_subscription_id=$3
            ''', legacy_status, period_end, sub_id)

            org_id = (sub.get("metadata") or {}).get("organization_id")
            plan_id = (sub.get("metadata") or {}).get("plan_id")
            if org_id and plan_id:
                await _sync_org_subscription(
                    organization_id=org_id, plan_id=plan_id, status=sub["status"],
                    stripe_customer_id=sub.get("customer"), stripe_subscription_id=sub_id,
                    current_period_end=period_end,
                )

        elif event_type in (
            "invoice.created", "invoice.finalized", "invoice.paid",
            "invoice.payment_failed", "invoice.voided",
        ):
            await _sync_invoice(event["data"]["object"], event_type=event_type)

        elif event_type in ("payment_method.attached", "payment_method.detached", "payment_method.updated"):
            await _sync_payment_methods_for_customer(event["data"]["object"].get("customer"))

        elif event_type == "customer.updated":
            await _sync_payment_methods_for_customer(event["data"]["object"].get("id"))


async def _sync_invoice(invoice_obj: dict, *, event_type: str) -> None:
    """Critical path: the invoice/payment DB write must propagate on
    failure so the webhook response is non-2xx and Stripe redelivers the
    event — silently swallowing this would permanently lose the invoice
    or payment record (record() treats a redelivery of a failed event as
    unfinished work, so retrying here is safe). Only the event-bus
    notification below is best-effort and isolated from that guarantee."""
    from app.billing import get_invoice_service
    from app.billing.subscriptions import get_org_subscription_service
    org_id = await get_org_subscription_service().find_org_by_customer_id(
        invoice_obj.get("customer") or ""
    )
    if not org_id:
        return  # not one of our tracked customers — nothing to do, not an error
    failure_message = None
    if event_type == "invoice.payment_failed":
        failure_message = (invoice_obj.get("last_finalization_error") or {}).get("message")
    row = await get_invoice_service().upsert_from_stripe_invoice(
        invoice_obj, organization_id=org_id, failure_message=failure_message,
    )
    if row is None:
        return
    if event_type in ("invoice.paid", "invoice.payment_failed"):
        try:
            from app.core.events import get_event_bus
            topic = "billing.payment_failed" if event_type == "invoice.payment_failed" else "billing.invoice_paid"
            await get_event_bus().publish(
                topic, {"invoice_id": str(row["id"]), "status": row["status"]},
                organization_id=org_id,
            )
        except Exception:
            log.warning("event publish failed for %s org=%s", event_type, org_id, exc_info=True)


async def _sync_payment_methods_for_customer(stripe_customer_id: str | None) -> None:
    """Best-effort — never breaks the webhook response."""
    if not stripe_customer_id:
        return
    try:
        from app.billing import get_payment_method_service
        from app.billing.subscriptions import get_org_subscription_service
        org_id = await get_org_subscription_service().find_org_by_customer_id(stripe_customer_id)
        if org_id:
            await get_payment_method_service().sync_for_org(org_id)
    except Exception:
        log.warning("payment method sync failed for customer=%s", stripe_customer_id, exc_info=True)


async def _sync_org_subscription(
    *, organization_id: str, plan_id: str, status: str,
    stripe_customer_id: str | None, stripe_subscription_id: str | None,
    current_period_end,
) -> None:
    """Critical path: the plan/access write must propagate on failure so
    the webhook response is non-2xx and Stripe redelivers the event —
    apply_webhook_update is an idempotent upsert, so re-running it on
    retry is safe. Only the event-bus notification below is best-effort
    and isolated from that guarantee."""
    from app.billing.subscriptions import get_org_subscription_service
    await get_org_subscription_service().apply_webhook_update(
        organization_id=organization_id, plan_id=plan_id, status=status,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        current_period_end=current_period_end,
    )
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish(
            "billing.updated", {"plan": plan_id, "status": status},
            organization_id=organization_id,
        )
    except Exception:
        log.warning("event publish failed for billing.updated org=%s", organization_id, exc_info=True)
