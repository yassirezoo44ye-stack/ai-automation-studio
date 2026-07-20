"""
Slack — AUTH_PROVIDER example plugin. Demonstrates the Plugin SDK's OAuth2
identity-provider extension point end to end, using Slack's real, publicly
documented "Sign in with Slack" OpenID Connect endpoints and the exact
authorization-code-flow mechanics already implemented in
app/integrations/oauth.py (build authorize URL -> exchange code for token
-> fetch profile).

Not a straight `from app.integrations.oauth import ...`: plugin code runs
inside an isolated Sandbox worker (Docker backend: a bare
python:3.11-slim image, nothing pip-installed — see
app/sandbox/backends.py), which has neither the `app` package nor httpx
available, only the standard library and this one file (a plugin bundle
is a single source string — see app/plugins/loader.py's `bundle["code"]`).
This reimplements the SAME request shape (grant_type=authorization_code
body, same field names, same param set as build_authorize_url()) with
stdlib urllib instead — functionally identical to
app.integrations.oauth.exchange_code_for_token(), not a different
protocol.

No real credentials are hardcoded — ships inert. required_permissions
declares "network"/"third_party_api" (sensitive: needs admin approval, see
app/plugins/loader.py's _SENSITIVE_CAPABILITIES) and manifest.json's
network_domains restricts the sandbox worker's outbound DNS allowlist to
exactly slack.com. configuration_schema requires client_id/client_secret/
redirect_uri, supplied by an org admin via PUT /plugins/installed/{id}/
config after installing (a Slack app must be created first to obtain
these). client_secret lives in plaintext plugin config, same as
client_id/redirect_uri — this platform does not yet expose an
admin-facing endpoint to write into a plugin's encrypted secret vault
(PluginContext.set_secret is only callable from the plugin's own code);
documented limitation, not something this example plugin can work
around.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.plugins.base import PluginBase, PluginContext, PluginHealth, PluginState, PluginType

AUTHORIZE_URL = "https://slack.com/openid/connect/authorize"
TOKEN_URL = "https://slack.com/api/openid.connect.token"
USERINFO_URL = "https://slack.com/api/openid.connect.userInfo"
DEFAULT_SCOPES = ["openid", "email", "profile"]
_HEADERS = {"Accept": "application/json", "User-Agent": "axon-plugin-sdk/slack"}


class SlackAPIError(RuntimeError):
    """Slack's convention: HTTP 200 with {"ok": false, "error": "..."}
    on failure, rather than a non-2xx status — must be checked explicitly,
    urllib.request won't raise on its own for this case."""


def _http_post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("ascii")
    req = urllib.request.Request(url, data=body, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed allowlisted host, not user input
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok", True):
        raise SlackAPIError(payload.get("error", "unknown Slack API error"))
    return payload


def _http_get_json(url: str, *, bearer_token: str) -> dict:
    headers = {**_HEADERS, "Authorization": f"Bearer {bearer_token}"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed allowlisted host, not user input
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok", True):
        raise SlackAPIError(payload.get("error", "unknown Slack API error"))
    return payload


class SlackAuthProvider:
    """Duck-typed to match app.plugins.provider_types.AuthProviderBase's
    shape (get_authorization_url/exchange_code) WITHOUT importing that ABC
    — app/plugins/provider_types.py is a host-side-only contract, never
    copied into the sandbox worker's workspace (only base.py is — see
    SandboxManager.spawn_worker), and the WorkerProxyProvider that later
    calls this object's methods never checks isinstance, only that the
    method names exist."""
    provider_id = "slack"

    def __init__(self, config: dict) -> None:
        self._client_id = config["client_id"]
        self._client_secret = config["client_secret"]
        self._scopes = config.get("scopes") or DEFAULT_SCOPES

    def get_authorization_url(self, *, redirect_uri: str, state: str) -> str:
        # Same param set as app.integrations.oauth.build_authorize_url().
        params = {
            "client_id": self._client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "scope": " ".join(self._scopes),
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> dict:
        # Same body shape as app.integrations.oauth.exchange_code_for_token().
        token = _http_post_form(TOKEN_URL, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": self._client_id, "client_secret": self._client_secret,
        })
        profile = _http_get_json(USERINFO_URL, bearer_token=token["access_token"])
        return {
            "email": profile.get("email"),
            "name": profile.get("name"),
            "provider": self.provider_id,
            "raw": profile,
        }


class SlackPlugin(PluginBase):
    plugin_type = PluginType.AUTH_PROVIDER

    def register(self, ctx: PluginContext) -> None:
        from app.plugins.adapters import adapt_auth_provider
        adapt_auth_provider("slack", SlackAuthProvider(ctx.config))

    def unregister(self, ctx: PluginContext) -> None:
        from app.plugins.adapters import unadapt_auth_provider
        unadapt_auth_provider("slack")

    def health_check(self) -> PluginHealth:
        return PluginHealth(plugin_id="slack", state=PluginState.ENABLED)
