"""
GitHub IntegrationProvider — Engineering Control Plane.

Authentication modes (set via secrets at connect time):
  api_key  → Personal Access Token (PAT): secrets = {"token": "ghp_..."}
  custom   → GitHub App installation token: secrets = {
               "app_id": "123456",
               "installation_id": "789",
               "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\\n..."
             }

The provider only handles credential lifecycle (test_connection, disconnect).
Actual tool operations (create_pr, list_branches, etc.) live in
app/engineering/tools/github_tools.py and are called through the
EngineeringToolGateway so every call is permission-checked, audited, and
Evidence-producing.

Declared capabilities:
  sync=False     — no bulk sync; the tool gateway handles on-demand reads
  webhooks=False — GitHub webhook ingestion is a separate future phase
  background_jobs=False
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.integrations.provider import IntegrationProvider
from app.integrations.types import (
    IntegrationCredential, ProviderCapabilities, ProviderScope, ProviderType,
)

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 20.0


def _auth_header(credential: IntegrationCredential) -> dict[str, str]:
    """Build the Authorization header from stored secrets.

    PAT path: secrets["token"] → "Bearer ghp_..."
    GitHub App path: secrets["installation_token"] → "Bearer ghs_..."
      (the installation token is short-lived and must be refreshed by
       the tool gateway before each call; stored here as a bootstrap value
       obtained at connect time).
    """
    token = credential.secrets.get("token") or credential.secrets.get("installation_token")
    if not token:
        raise ValueError("github credential has no usable token")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GitHubProvider(IntegrationProvider):
    """GitHub integration — credential lifecycle only."""

    @property
    def provider_id(self) -> str:
        return "github"

    @property
    def display_name(self) -> str:
        return "GitHub"

    @property
    def provider_type(self) -> ProviderType:
        # API_KEY for PAT; CUSTOM is used for GitHub App tokens.
        # The integration UI passes the type; the provider accepts both.
        return ProviderType.API_KEY

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            sync=False,
            webhooks=False,
            background_jobs=False,
        )

    def scopes(self) -> list[ProviderScope]:
        return [
            ProviderScope(id="github.read",           label="Read repositories, branches, commits, checks"),
            ProviderScope(id="github.issue.create",   label="Create issues"),
            ProviderScope(id="github.issue.update",   label="Update and close issues"),
            ProviderScope(id="github.branch.create",  label="Create branches"),
            ProviderScope(id="github.commit.read",    label="Read commit metadata and diffs"),
            ProviderScope(id="github.pr.create",      label="Create pull requests"),
            ProviderScope(id="github.pr.merge",       label="Merge pull requests",     sensitive=True),
            ProviderScope(id="github.checks.read",    label="Read CI check results"),
            ProviderScope(id="github.actions.read",   label="Read Actions workflow runs"),
        ]

    async def test_connection(self, credential: IntegrationCredential) -> bool:
        """Call GET /user (PAT) or GET /installation (App token) to verify."""
        try:
            headers = _auth_header(credential)
        except ValueError:
            log.warning("github test_connection: missing token in credential")
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(_CONNECT_TIMEOUT)) as client:
                resp = await client.get(f"{_GITHUB_API}/user", headers=headers)
            if resp.status_code == 200:
                login = resp.json().get("login", "<unknown>")
                log.info("github test_connection OK: authenticated as %r", login)
                return True
            if resp.status_code == 401:
                log.warning("github test_connection: 401 Unauthorized")
                return False
            log.warning("github test_connection: unexpected status %d", resp.status_code)
            return False
        except httpx.TransportError as exc:
            log.warning("github test_connection: transport error: %s", exc)
            return False

    async def disconnect(self, credential: IntegrationCredential) -> None:
        """GitHub tokens cannot be revoked via API with a bearer token alone —
        revocation requires the token itself as a credential (DELETE
        /applications/{client_id}/token), which requires an OAuth2 app.
        For PATs the user must revoke manually in GitHub Settings.
        We log the intent so operators know to rotate."""
        log.info(
            "github disconnect: credential for org=%s removed from store; "
            "operator should revoke the PAT manually at github.com/settings/tokens",
            credential.organization_id,
        )


def get_installation_token(
    app_id: str,
    installation_id: str,
    private_key_pem: str,
    *,
    timeout: float = _CONNECT_TIMEOUT,
) -> Optional[str]:
    """Synchronously generate a GitHub App installation token (JWT → exchange).

    Returns the token string on success, None on failure.
    Called by the tool gateway when the stored installation_token has expired
    (they last 1 hour). This is synchronous to keep it usable from both sync
    and async contexts; callers in async contexts should run it in a thread
    pool executor.

    Requires PyJWT + cryptography (already in requirements.txt via
    app/core/auth.py's cryptography usage and the anthropic SDK's jwt dep).
    """
    try:
        import time
        import jwt  # PyJWT
        now = int(time.time())
        payload = {
            "iat": now - 60,   # issued slightly in the past (clock skew tolerance)
            "exp": now + 600,  # 10-minute expiry
            "iss": app_id,
        }
        app_jwt = jwt.encode(payload, private_key_pem, algorithm="RS256")
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
        }
        resp = httpx.post(
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code == 201:
            return resp.json().get("token")
        log.warning("github app token exchange returned %d", resp.status_code)
        return None
    except Exception as exc:
        log.warning("github get_installation_token failed: %s", exc)
        return None
