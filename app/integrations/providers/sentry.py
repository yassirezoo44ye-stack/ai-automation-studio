"""
Sentry IntegrationProvider — Engineering Control Plane.

Authentication: Auth Token  →  secrets = {
    "auth_token": "sntrys_...",
    "org_slug":   "my-sentry-org",   # required for scoped API calls
}

Credential lifecycle only. Tool operations in
app/engineering/tools/sentry_tools.py.

Sentry auth tokens are scoped at creation time. The minimum scopes
needed for the tool gateway are:
  event:read   — read issues and events
  project:read — read project list
"""
from __future__ import annotations

import logging

import httpx

from app.integrations.provider import IntegrationProvider
from app.integrations.types import (
    IntegrationCredential, ProviderCapabilities, ProviderScope, ProviderType,
)

log = logging.getLogger(__name__)

_SENTRY_API = "https://sentry.io/api/0"
_CONNECT_TIMEOUT = 10.0


def _auth_header(credential: IntegrationCredential) -> dict[str, str]:
    token = credential.secrets.get("auth_token", "")
    if not token:
        raise ValueError("sentry credential missing auth_token")
    return {"Authorization": f"Bearer {token}"}


class SentryProvider(IntegrationProvider):
    """Sentry error-tracking integration — credential lifecycle only."""

    @property
    def provider_id(self) -> str:
        return "sentry"

    @property
    def display_name(self) -> str:
        return "Sentry"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.API_KEY

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(sync=False, webhooks=False, background_jobs=False)

    def scopes(self) -> list[ProviderScope]:
        return [
            ProviderScope(id="sentry.issues.read",  label="Read issues and error events"),
            ProviderScope(id="sentry.projects.read", label="Read project list"),
            ProviderScope(id="sentry.releases.read", label="Read release health data"),
        ]

    async def test_connection(self, credential: IntegrationCredential) -> bool:
        try:
            headers = _auth_header(credential)
        except ValueError:
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(_CONNECT_TIMEOUT)) as client:
                # GET /api/0/ returns auth token info
                resp = await client.get(f"{_SENTRY_API}/", headers=headers)
            if resp.status_code == 200:
                log.info("sentry test_connection OK for org=%s", credential.organization_id)
                return True
            if resp.status_code == 401:
                log.warning("sentry test_connection: 401 — invalid auth_token")
                return False
            log.warning("sentry test_connection: unexpected status %d", resp.status_code)
            return False
        except httpx.TransportError as exc:
            log.warning("sentry test_connection: transport error: %s", exc)
            return False

    async def disconnect(self, credential: IntegrationCredential) -> None:
        log.info(
            "sentry disconnect: credential for org=%s removed; "
            "operator should revoke the auth token at sentry.io/settings/account/api/auth-tokens/",
            credential.organization_id,
        )
