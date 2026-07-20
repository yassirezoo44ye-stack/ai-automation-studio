"""
GitHub — AUTH_PROVIDER example plugin. Demonstrates the Plugin SDK's OAuth2
identity-provider extension point end to end, using GitHub's real, publicly
documented OAuth endpoints and the exact authorization-code-flow mechanics
already implemented in app/integrations/oauth.py (build authorize URL ->
exchange code for token -> fetch profile).

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
exactly GitHub's OAuth + API hosts. configuration_schema requires
client_id/client_secret/redirect_uri, supplied by an org admin via
PUT /plugins/installed/{id}/config after installing (a GitHub OAuth App
must be registered first to obtain these). client_secret lives in
plaintext plugin config, same as client_id/redirect_uri — this platform
does not yet expose an admin-facing endpoint to write into a plugin's
encrypted secret vault (PluginContext.set_secret is only callable from
the plugin's own code); documented limitation, not something this
example plugin can work around.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.plugins.base import PluginBase, PluginContext, PluginHealth, PluginState, PluginType

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USERINFO_URL = "https://api.github.com/user"
EMAILS_URL = "https://api.github.com/user/emails"
DEFAULT_SCOPES = ["read:user", "user:email"]
# GitHub's API rejects requests with no User-Agent header — required, not optional.
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "axon-plugin-sdk/github"}


def _http_post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("ascii")
    req = urllib.request.Request(url, data=body, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed allowlisted host, not user input
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str, *, bearer_token: str):
    headers = {**_HEADERS, "Authorization": f"Bearer {bearer_token}"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed allowlisted host, not user input
        return json.loads(resp.read().decode("utf-8"))


class GitHubAuthProvider:
    """Duck-typed to match app.plugins.provider_types.AuthProviderBase's
    shape (get_authorization_url/exchange_code) WITHOUT importing that ABC
    — app/plugins/provider_types.py is a host-side-only contract, never
    copied into the sandbox worker's workspace (only base.py is — see
    SandboxManager.spawn_worker), and the WorkerProxyProvider that later
    calls this object's methods never checks isinstance, only that the
    method names exist."""
    provider_id = "github"

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
        if "error" in token:
            raise RuntimeError(token.get("error_description", token["error"]))
        access_token = token["access_token"]
        profile = _http_get_json(USERINFO_URL, bearer_token=access_token)
        email = profile.get("email")
        if not email:
            # A user with a private email address has profile["email"] == None
            # — fall back to their verified primary address, the same
            # two-call pattern any real GitHub OAuth integration needs.
            emails = _http_get_json(EMAILS_URL, bearer_token=access_token)
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            email = primary["email"] if primary else None
        return {
            "email": email,
            "name": profile.get("name") or profile.get("login"),
            "provider": self.provider_id,
            "raw": profile,
        }


class GitHubPlugin(PluginBase):
    plugin_type = PluginType.AUTH_PROVIDER

    def register(self, ctx: PluginContext) -> None:
        from app.plugins.adapters import adapt_auth_provider
        adapt_auth_provider("github", GitHubAuthProvider(ctx.config))

    def unregister(self, ctx: PluginContext) -> None:
        from app.plugins.adapters import unadapt_auth_provider
        unadapt_auth_provider("github")

    def health_check(self) -> PluginHealth:
        return PluginHealth(plugin_id="github", state=PluginState.ENABLED)
