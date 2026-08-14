"""
Render IntegrationProvider — Engineering Control Plane.

Authentication: API Key  →  secrets = {"api_key": "rnd_..."}

The provider handles credential lifecycle only. Actual deployment operations
(trigger_deploy, get_deploy_status, get_logs) live in
app/engineering/tools/render_tools.py, called through EngineeringToolGateway.

CRITICAL: render.trigger_deploy returning HTTP 200 is NOT deployment success.
Real success requires:
  1. Deploy status = "live"
  2. health endpoint returns 200
  3. observed production SHA == requested SHA

All three are captured as Evidence by the VerifyEngine.
"""
from __future__ import annotations

import logging

import httpx

from app.integrations.provider import IntegrationProvider
from app.integrations.types import (
    IntegrationCredential, ProviderCapabilities, ProviderScope, ProviderType,
)

log = logging.getLogger(__name__)

_RENDER_API = "https://api.render.com/v1"
_CONNECT_TIMEOUT = 10.0


def _auth_header(credential: IntegrationCredential) -> dict[str, str]:
    api_key = credential.secrets.get("api_key", "")
    if not api_key:
        raise ValueError("render credential missing api_key")
    return {"Authorization": f"Bearer {api_key}"}


class RenderProvider(IntegrationProvider):
    """Render cloud platform integration — credential lifecycle only."""

    @property
    def provider_id(self) -> str:
        return "render"

    @property
    def display_name(self) -> str:
        return "Render"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.API_KEY

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(sync=False, webhooks=False, background_jobs=False)

    def scopes(self) -> list[ProviderScope]:
        return [
            ProviderScope(id="render.services.read",  label="Read services and their state"),
            ProviderScope(id="render.deploy.trigger", label="Trigger deployments",     sensitive=True),
            ProviderScope(id="render.deploy.status",  label="Read deployment status and SHA"),
            ProviderScope(id="render.logs.read",      label="Read service logs"),
            ProviderScope(id="render.env.read",       label="Read environment variable names (not values)"),
        ]

    async def test_connection(self, credential: IntegrationCredential) -> bool:
        """Call GET /services?limit=1 to verify the API key is valid."""
        try:
            headers = _auth_header(credential)
        except ValueError:
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(_CONNECT_TIMEOUT)) as client:
                resp = await client.get(
                    f"{_RENDER_API}/services",
                    headers=headers,
                    params={"limit": 1},
                )
            if resp.status_code == 200:
                log.info("render test_connection OK for org=%s", credential.organization_id)
                return True
            if resp.status_code == 401:
                log.warning("render test_connection: 401 — invalid API key")
                return False
            log.warning("render test_connection: unexpected status %d", resp.status_code)
            return False
        except httpx.TransportError as exc:
            log.warning("render test_connection: transport error: %s", exc)
            return False

    async def disconnect(self, credential: IntegrationCredential) -> None:
        """Render API keys must be revoked manually in the Render dashboard."""
        log.info(
            "render disconnect: credential for org=%s removed; "
            "operator should revoke the API key at dashboard.render.com/account/api-keys",
            credential.organization_id,
        )
