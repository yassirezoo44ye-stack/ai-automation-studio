"""
IntegrationProvider — the one interface every integration implements.

A provider is stateless business logic: given a credential, do the thing.
It never touches the database directly and never manages its own retry/
health/metrics/audit — that's the service layer's job (service.py), which
wraps every provider call with the shared reliability/observability
plumbing. This keeps a provider implementation small and testable in
isolation (see examples/webhook_relay_provider.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.integrations.types import (
    IntegrationCredential, ProviderCapabilities, ProviderScope, ProviderType,
    SyncResult, WebhookEvent,
)


class IntegrationProvider(ABC):
    """Subclass this once per integration. Every method below has a
    default no-op/False implementation so a minimal provider only needs
    to override what it actually supports — declare capabilities()
    accurately and the SDK will never call the methods you didn't need."""

    # ── Identity (required) ─────────────────────────────────────────────────

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable, unique slug — e.g. 'webhook-relay'. Never changes once shipped."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        ...

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def scopes(self) -> list[ProviderScope]:
        """Permission scopes a connecting org can grant. Empty by default —
        override for providers that support fine-grained access."""
        return []

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def test_connection(self, credential: IntegrationCredential) -> bool:
        """Cheap reachability/auth check — called right after connect() and
        periodically by health.py. Default: assume healthy (a provider with
        no real backend to ping, like the example, has nothing to check)."""
        return True

    async def disconnect(self, credential: IntegrationCredential) -> None:
        """Best-effort external cleanup (e.g. revoke a token). The credential
        row itself is deleted by the service layer regardless of what
        happens here."""
        return None

    # ── Sync (only called if capabilities().sync is True) ──────────────────

    async def sync(self, credential: IntegrationCredential, *, cursor: Optional[str] = None) -> SyncResult:
        raise NotImplementedError(f"{self.provider_id} declared sync capability but did not implement sync()")

    # ── Webhooks (only called if capabilities().webhooks is True) ──────────

    def verify_webhook_signature(self, event: WebhookEvent, secret: str) -> bool:
        """Override with the provider's real signature scheme (HMAC-SHA256
        of the raw body is the common case — see examples/ for a worked
        version). Default rejects everything, so a provider MUST opt in
        explicitly rather than accidentally accepting unverified webhooks."""
        return False

    async def handle_webhook(self, credential: IntegrationCredential, event: WebhookEvent) -> None:
        raise NotImplementedError(f"{self.provider_id} declared webhook capability but did not implement handle_webhook()")
