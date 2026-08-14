"""
Vercel IntegrationProvider — Engineering Control Plane.

Authentication: API Token  →  secrets = {"token": "..."}
  Optionally: secrets = {"token": "...", "team_id": "team_..."}  (for team scope)

Credential lifecycle only. Tool operations in
app/engineering/tools/vercel_tools.py.
"""
from __future__ import annotations

import logging

import httpx

from app.integrations.provider import IntegrationProvider
from app.integrations.types import (
    IntegrationCredential, ProviderCapabilities, ProviderScope, ProviderType,
)

log = logging.getLogger(__name__)

_VERCEL_API = "https://api.vercel.com"
_CONNECT_TIMEOUT = 10.0


def _auth_header(credential: IntegrationCredential) -> dict[str, str]:
    token = credential.secrets.get("token", "")
    if not token:
        raise ValueError("vercel credential missing token")
    return {"Authorization": f"Bearer {token}"}


class VercelProvider(IntegrationProvider):
    """Vercel deployment platform integration — credential lifecycle only."""

    @property
    def provider_id(self) -> str:
        return "vercel"

    @property
    def display_name(self) -> str:
        return "Vercel"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.API_KEY

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(sync=False, webhooks=False, background_jobs=False)

    def scopes(self) -> list[ProviderScope]:
        return [
            ProviderScope(id="vercel.deployments.read",    label="Read deployment list and status"),
            ProviderScope(id="vercel.deployments.create",  label="Trigger new deployments", sensitive=True),
            ProviderScope(id="vercel.projects.read",       label="Read project configuration"),
            ProviderScope(id="vercel.logs.read",           label="Read deployment build logs"),
        ]

    async def test_connection(self, credential: IntegrationCredential) -> bool:
        try:
            headers = _auth_header(credential)
        except ValueError:
            return False
        try:
            params = {}
            team_id = credential.secrets.get("team_id")
            if team_id:
                params["teamId"] = team_id
            async with httpx.AsyncClient(timeout=httpx.Timeout(_CONNECT_TIMEOUT)) as client:
                resp = await client.get(
                    f"{_VERCEL_API}/v2/user",
                    headers=headers,
                    params=params,
                )
            if resp.status_code == 200:
                username = resp.json().get("user", {}).get("username", "<unknown>")
                log.info("vercel test_connection OK: authenticated as %r", username)
                return True
            if resp.status_code == 401:
                log.warning("vercel test_connection: 401 — invalid token")
                return False
            log.warning("vercel test_connection: unexpected status %d", resp.status_code)
            return False
        except httpx.TransportError as exc:
            log.warning("vercel test_connection: transport error: %s", exc)
            return False

    async def disconnect(self, credential: IntegrationCredential) -> None:
        log.info(
            "vercel disconnect: credential for org=%s removed; "
            "operator should revoke token at vercel.com/account/tokens",
            credential.organization_id,
        )
