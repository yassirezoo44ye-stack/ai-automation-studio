"""
Generic OAuth2 authorization-code flow — provider-agnostic. This module
implements the RFC 6749 mechanics (authorize URL construction, code
exchange, token refresh) once; a real provider supplies its own
OAuthProviderConfig (client_id/secret, endpoints, scopes) via
environment variables that are NOT set anywhere in this codebase — no
Microsoft/Google/Slack/etc. app is registered. Until an operator sets
the corresponding env vars and registers a matching IntegrationProvider,
OAUTH2-type providers simply aren't connectable; nothing here fabricates
a working flow for a provider that doesn't have real credentials.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx


@dataclass
class OAuthProviderConfig:
    """Everything needed to drive one provider's OAuth2 flow. A real
    integration constructs this from its own env vars at registration
    time — see examples/webhook_relay_provider.py for how a provider
    wires this up (using placeholder env vars that are unset by default,
    so the example provider's OAuth2 methods are exercised only in tests
    with a fake token endpoint, never against a real service)."""
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    redirect_uri: str
    scopes: list[str] = field(default_factory=list)
    extra_authorize_params: dict[str, str] = field(default_factory=dict)


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: str | None
    expires_at: float | None
    token_type: str = "Bearer"
    raw: dict = field(default_factory=dict)


def generate_state() -> str:
    """CSRF-protection token for the authorize redirect — callers must
    store this (session/short-lived cache) and verify it matches on
    callback before ever calling exchange_code_for_token()."""
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for providers requiring PKCE."""
    verifier = secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    return verifier, challenge


def build_authorize_url(config: OAuthProviderConfig, *, state: str, code_challenge: str | None = None) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
        **config.extra_authorize_params,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{config.authorize_url}?{urlencode(params)}"


async def exchange_code_for_token(config: OAuthProviderConfig, *, code: str, code_verifier: str | None = None) -> OAuthToken:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(config.token_url, data=data, headers={"Accept": "application/json"})
        res.raise_for_status()
        payload = res.json()
    return _token_from_payload(payload)


async def refresh_access_token(config: OAuthProviderConfig, *, refresh_token: str) -> OAuthToken:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(config.token_url, data=data, headers={"Accept": "application/json"})
        res.raise_for_status()
        payload = res.json()
    token = _token_from_payload(payload)
    # Most providers omit refresh_token on a refresh response (it doesn't
    # rotate) — carry the old one forward so callers never lose it.
    if not token.refresh_token:
        token.refresh_token = refresh_token
    return token


def _token_from_payload(payload: dict) -> OAuthToken:
    expires_in = payload.get("expires_in")
    return OAuthToken(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=(time.time() + float(expires_in)) if expires_in is not None else None,
        token_type=payload.get("token_type", "Bearer"),
        raw=payload,
    )
