"""
WebhookRelayProvider — the reference implementation every future provider
should model itself on. It is deliberately NOT a placeholder: it's fully
functional end-to-end (connect, verify+receive a real signed webhook,
run a sync) without needing any third-party developer account, because
its "credential" is a locally-generated shared secret rather than an
OAuth app someone would have to register.

Real use case this models: forwarding inbound webhooks from any HTTP
sender that can compute an HMAC-SHA256 signature (most SaaS webhook
senders — Stripe, GitHub, etc. — use exactly this scheme, just with
their own header name).
"""
from __future__ import annotations

import hashlib
import hmac
import logging

from app.integrations.provider import IntegrationProvider
from app.integrations.types import (
    IntegrationCredential, ProviderCapabilities, ProviderScope, ProviderType,
    SyncResult, SyncStatus, WebhookEvent,
)

log = logging.getLogger(__name__)

SIGNATURE_HEADER = "x-relay-signature"


class WebhookRelayProvider(IntegrationProvider):
    @property
    def provider_id(self) -> str:
        return "webhook-relay"

    @property
    def display_name(self) -> str:
        return "Webhook Relay (example)"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CUSTOM

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(sync=True, webhooks=True, background_jobs=True)

    def scopes(self) -> list[ProviderScope]:
        return [ProviderScope(id="receive", label="Receive relayed webhook events")]

    async def test_connection(self, credential: IntegrationCredential) -> bool:
        return bool(credential.secrets.get("webhook_secret"))

    def verify_webhook_signature(self, event: WebhookEvent, secret: str) -> bool:
        if not secret:
            return False
        provided = event.headers.get(SIGNATURE_HEADER, "")
        expected = hmac.new(secret.encode("utf-8"), event.body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(provided, expected)

    async def handle_webhook(self, credential: IntegrationCredential, event: WebhookEvent) -> None:
        # A real relay would forward `event.body` to a configured downstream
        # URL here. The example just logs — the point is the verify/dedup/
        # dispatch pipeline around it, which is identical for every provider.
        log.info("webhook-relay: received %d bytes for org=%s", len(event.body), credential.organization_id)

    async def sync(self, credential: IntegrationCredential, *, cursor: str | None = None) -> SyncResult:
        # No real backend to pull from — proves the sync pipeline (job
        # scheduling, retry, history recording, event publishing) works
        # end-to-end without needing one.
        return SyncResult(status=SyncStatus.SUCCEEDED, items_synced=0, cursor=cursor,
                           message="webhook-relay has no remote data source; sync is a no-op by design")
