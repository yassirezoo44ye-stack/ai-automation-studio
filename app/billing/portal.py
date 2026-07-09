"""
Stripe Customer/Billing Portal — self-serve plan switching, cancellation,
and payment-method management, without hand-rolling Stripe Elements or
proration math.
"""
from __future__ import annotations

import stripe


class NoStripeCustomer(Exception):
    """Raised when an org has never checked out, so it has no Stripe
    customer to open a portal session for."""


async def create_portal_session(org_id: str, return_url: str) -> str:
    from app.billing.subscriptions import get_org_subscription_service

    customer_id = await get_org_subscription_service().get_stripe_customer_id(org_id)
    if not customer_id:
        raise NoStripeCustomer(org_id)
    session = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=return_url,
    )
    return session.url
