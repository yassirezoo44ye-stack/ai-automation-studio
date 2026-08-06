import logging
from datetime import datetime

import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import verify_token
from app.core.config import STRIPE_PRICE_ID, APP_URL
from app.core.db import get_pool
from app.core.rate_limit import _real_ip, check_rate_limit

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
    """Read-only status check — no side effects, no token issuance.

    SECURITY FIX: this endpoint previously auto-enrolled ANY caller-supplied,
    unverified email into a fresh 7-day trial and handed back a fully
    authenticated `token` scoped to that email — anyone who knew or guessed
    a victim's email address could obtain a working session as that user
    with zero proof of ownership (no password, no verification link).
    Confirmed unused by the current frontend and referenced nowhere else in
    this repo before this fix (only this router's own definition and a
    README listing). It now only reports whether `email` already has an
    active PAID subscription on file — it never creates a trial record and
    never mints a token. Real account/trial creation goes through
    POST /api/auth/register (password-protected) or the Stripe checkout
    flow, both of which already require proof of identity this anonymous
    GET had no way to check.
    """
    if not check_rate_limit(f"sub:{_real_ip(request)}", max_calls=10, window=60):
        raise HTTPException(429, "Too many requests. Try again later.")

    async with get_pool().acquire() as conn:
        sub = await conn.fetchrow(
            "SELECT status, current_period_end FROM subscriptions WHERE email=$1", email
        )
    active = bool(sub and sub["status"] == "active" and (
        sub["current_period_end"] is None or sub["current_period_end"] > datetime.utcnow()
    ))
    return {"active": active}


@router.post("/api/subscription/verify")
async def verify_session(request: Request):
    """Kept read-only for backward compatibility with any still-existing
    holder of a token minted before the fix above — reports validity only,
    no longer re-signs/extends it. Silently renewing a token forever with
    no password re-check (the previous behavior) is a real, separate
    weakness — deliberately not fixed here to keep this security patch
    scoped; flagged as follow-up tech debt. This endpoint mints nothing
    itself either way, so it does not reopen the vulnerability fixed above."""
    body = await request.json()
    token = body.get("token", "")
    payload = verify_token(token)
    if not payload:
        return {"valid": False}
    return {
        "valid": True,
        "trial": payload.get("trial", False),
        "days_remaining": payload.get("dr", 0),
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
