"""
Real IntegrationProvider implementations for the Engineering Control Plane.

Providers:
  github  — GitHub (API key = PAT, or custom = GitHub App installation token)
  render  — Render cloud deployment platform
  vercel  — Vercel deployment platform
  sentry  — Sentry error tracking

None of these providers require third-party app registrations in this codebase.
All credentials are supplied by operators via the /api/orgs/{org_id}/integrations
connect endpoint and stored encrypted-at-rest in the CredentialStore.

Registered in app/factory.py lifespan block alongside the existing
WebhookRelayProvider example.
"""
from app.integrations.providers.github import GitHubProvider
from app.integrations.providers.render import RenderProvider
from app.integrations.providers.vercel import VercelProvider
from app.integrations.providers.sentry import SentryProvider

__all__ = [
    "GitHubProvider",
    "RenderProvider",
    "VercelProvider",
    "SentryProvider",
]
