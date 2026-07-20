"""
Generic webhook receiver logic — signature verification, dedup, and
dispatch to the owning provider. The HTTP endpoint itself lives in
app/routers/integrations.py; this module is the reusable core so the
router stays a thin adapter.
"""
from __future__ import annotations

import hashlib
import logging
import uuid

from app.integrations.provider import IntegrationProvider
from app.integrations.types import IntegrationCredential, WebhookEvent, new_id

log = logging.getLogger(__name__)


class WebhookVerificationError(Exception):
    pass


class WebhookDuplicateError(Exception):
    """Raised when this exact webhook delivery was already processed —
    callers should still return 200 to the sender (webhooks are commonly
    retried on any non-2xx), just skip re-processing."""


def _dedup_key(provider_id: str, organization_id: str, body: bytes) -> str:
    return hashlib.sha256(f"{provider_id}:{organization_id}:".encode() + body).hexdigest()


async def receive_webhook(
    *, provider: IntegrationProvider, credential: IntegrationCredential,
    headers: dict[str, str], body: bytes, pool,
) -> WebhookEvent:
    """Verify, dedup, persist, and dispatch one inbound webhook delivery.
    Raises WebhookVerificationError (caller should respond 401) or
    WebhookDuplicateError (caller should respond 200 without re-processing)."""
    secret = credential.secrets.get("webhook_secret", "")
    event = WebhookEvent(
        id=new_id(), provider_id=provider.provider_id, organization_id=credential.organization_id,
        headers=headers, body=body,
    )

    if not provider.verify_webhook_signature(event, secret):
        raise WebhookVerificationError(f"signature verification failed for {provider.provider_id}")

    dedup_key = _dedup_key(provider.provider_id, credential.organization_id, body)
    async with pool.acquire() as conn:
        inserted = await conn.fetchval(
            """INSERT INTO integration_webhook_events (id, provider_id, organization_id, dedup_key, received_at)
               VALUES ($1,$2,$3,$4,to_timestamp($5))
               ON CONFLICT (dedup_key) DO NOTHING RETURNING id""",
            uuid.UUID(event.id), provider.provider_id, uuid.UUID(credential.organization_id),
            dedup_key, event.received_at,
        )
    if inserted is None:
        raise WebhookDuplicateError(dedup_key)

    await provider.handle_webhook(credential, event)
    return event
