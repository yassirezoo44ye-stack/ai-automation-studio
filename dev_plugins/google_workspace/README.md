# google_workspace

Production-ready AUTH_PROVIDER example plugin: OAuth2 "Sign in with Google"
using the platform's existing Plugin SDK + Sandbox + OAuth mechanics
(app/integrations/oauth.py's authorization-code-flow shape, reimplemented
with stdlib `urllib` because sandboxed plugin code has no `httpx`/`app`
package available — see plugin.py's module docstring for the full
explanation).

No real credentials are hardcoded. To make this plugin actually connect:

1. Register an OAuth 2.0 Client ID in [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
2. Install this plugin (bundle manifest.json + plugin.py via `POST /marketplace/listings` as `type=plugin`, then `POST /marketplace/listings/{id}/install`).
3. Because it declares the `network`/`third_party_api` capabilities, an org admin must approve it: `POST /plugins/installed/{id}/approve`, then `POST /plugins/installed/{id}/enable`.
4. Supply your credentials: `PUT /plugins/installed/{id}/config` with `{"client_id": "...", "client_secret": "...", "redirect_uri": "..."}`.
5. The registered `google_workspace` AUTH_PROVIDER is now callable via `app.plugins.adapters.WorkerProxyProvider` — `get_authorization_url(redirect_uri, state)` builds the consent-screen URL, `exchange_code(code, redirect_uri)` completes the flow and returns a normalized `{email, name}` profile.

See `GET /plugins/installed/{id}/capabilities` to confirm what this
installation was granted and what it registered.
