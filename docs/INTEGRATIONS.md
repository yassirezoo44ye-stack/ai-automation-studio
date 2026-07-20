# Integration SDK

A reusable framework for connecting AI Automation Studio to external
services — OAuth2, API-key, JWT, Basic Auth, or custom-auth providers —
without every integration reinventing credential storage, retries,
webhooks, sync scheduling, permissions, health, metrics, or audit logging.

**No real provider ships in this codebase.** No Microsoft/Google/Slack/
GitHub/etc. app is registered, and no OAuth client secret is configured
anywhere. The only provider registered at boot is
`WebhookRelayProvider` (`app/integrations/examples/webhook_relay_provider.py`)
— a fully functional reference implementation whose "credential" is a
locally-generated shared secret, so it needs no third-party account to
exercise the whole pipeline end-to-end.

## Architecture

```
                        ┌─────────────────────────┐
  routers/integrations  │   IntegrationService     │   app/integrations/service.py
  (REST surface) ──────▶│   (orchestration facade)  │
                        └───────────┬──────────────┘
                                    │
        ┌───────────────┬──────────┼───────────┬────────────────┐
        ▼                ▼          ▼           ▼                ▼
 IntegrationRegistry  CredentialStore  SyncEngine  webhooks.py  events.py /
 (registry.py)        (Fernet-encrypted (job-queue   (verify+     metrics.py /
        │              Postgres)       backed)      dedup+       health.py
        ▼                                            dispatch)        │
 IntegrationProvider ◀── every provider implements this ABC            │
 (provider.py)                                                         ▼
        │                                              EXISTING platform
        ▼                                              event bus / metrics
 examples/webhook_relay_provider.py                    registry / health
 (reference implementation)                            registry / job queue /
                                                        circuit breaker
```

Everything on the right column is the **existing** platform
infrastructure — the Integration SDK is a thin, consistent adapter over
it, not a parallel system:

| Concern | Reused from |
|---|---|
| Retry / circuit breaking | `app.core.reliability.CircuitBreaker` |
| Background jobs / scheduling | `app.core.jobs.JobQueue` |
| Events | `app.core.events.bus` (`EVENT_TYPES` extended additively) |
| Health | `app.core.observability.health.HealthRegistry` |
| Metrics | `app.core.observability.metrics.MetricsRegistry` |
| Audit log | `activity_logs` table (via `TenancyService`'s existing table) |
| Secret encryption | Fernet key derived from `SESSION_SECRET`, same pattern as `app.plugins.secrets` |
| Permission model | `require_permission(resource, action)` (`app.tenancy.context`), same as every other org-scoped resource |

## Data model

Four tables, initialized idempotently by `init_integrations_schema()`
(wired into `app/factory.py` right after tenancy schema init, since
`integrations` and `integration_credentials` reference `organizations`
and `users`):

- **`integrations`** — one row per org-provider connection: status,
  granted scopes, who connected it, last sync time.
- **`integration_credentials`** — encrypted secrets (`secrets_encrypted`,
  Fernet ciphertext of a JSON blob), keyed `(provider_id, organization_id)`.
- **`integration_sync_runs`** — sync job history (status, items synced,
  message, cursor) for `GET /{provider_id}/sync-history`.
- **`integration_webhook_events`** — dedup ledger keyed by a SHA-256 of
  `(provider_id, organization_id, raw body)`, so a retried webhook
  delivery is a no-op the second time.

## Extension points

Building a new integration means writing **one class** and registering
one instance — nothing else in the SDK needs to change.

### 1. `IntegrationProvider` (`app/integrations/provider.py`)

```python
from app.integrations.provider import IntegrationProvider
from app.integrations.types import ProviderType, ProviderCapabilities

class MyProvider(IntegrationProvider):
    @property
    def provider_id(self) -> str: return "my-service"       # stable, never renamed
    @property
    def display_name(self) -> str: return "My Service"
    @property
    def provider_type(self) -> ProviderType: return ProviderType.OAUTH2

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(sync=True, webhooks=True)

    async def test_connection(self, credential) -> bool: ...
    async def sync(self, credential, *, cursor=None) -> SyncResult: ...
    def verify_webhook_signature(self, event, secret) -> bool: ...
    async def handle_webhook(self, credential, event) -> None: ...
```

Every method has a safe default (see the ABC's docstrings) — a
minimal provider overrides only what it declares in `capabilities()`.
A provider never touches the database, the job queue, or the event bus
directly; `IntegrationService` wraps every call with the shared
reliability/observability plumbing.

### 2. Registration (boot time, `app/factory.py`)

```python
get_integration_registry().register(MyProvider())
```

### 3. OAuth2 providers only: `OAuthProviderConfig` (`app/integrations/oauth.py`)

The SDK implements RFC 6749 authorization-code + PKCE mechanics once
(`build_authorize_url`, `exchange_code_for_token`, `refresh_access_token`).
A real OAuth2 provider constructs its own `OAuthProviderConfig` from
environment variables it defines — this codebase sets none, so OAuth2-type
providers are registered but not connectable until an operator supplies
real client credentials out-of-band.

## Public interfaces

| Module | Exports |
|---|---|
| `app.integrations.types` | `ProviderType`, `IntegrationStatus`, `SyncStatus`, `ProviderCapabilities`, `ProviderScope`, `IntegrationCredential`, `WebhookEvent`, `SyncResult` |
| `app.integrations.provider` | `IntegrationProvider` (ABC) |
| `app.integrations.registry` | `IntegrationRegistry`, `get_integration_registry()` |
| `app.integrations.credential_store` | `CredentialStore` (interface), `PostgresCredentialStore`, `get_credential_store()` |
| `app.integrations.oauth` | `OAuthProviderConfig`, `OAuthToken`, `generate_state`, `generate_pkce_pair`, `build_authorize_url`, `exchange_code_for_token`, `refresh_access_token` |
| `app.integrations.webhooks` | `receive_webhook()`, `WebhookVerificationError`, `WebhookDuplicateError` |
| `app.integrations.sync_engine` | `SyncEngine`, `get_sync_engine()` |
| `app.integrations.retry` | `get_integration_circuit_breaker()`, `is_connection_allowed()` |
| `app.integrations.permissions` | `validate_requested_scopes()`, `sensitive_scopes()` |
| `app.integrations.events` | `publish_connected/disconnected/sync_started/sync_completed/sync_failed/webhook_received/health_changed` |
| `app.integrations.health` | `register_integration_health_probe()` |
| `app.integrations.metrics` | `record_sync()`, `record_webhook_received()`, `record_connection_change()` |
| `app.integrations.service` | `IntegrationService`, `IntegrationError`, `get_integration_service()` |
| `app.integrations.schema` | `init_integrations_schema()` |

## REST API (`app/routers/integrations.py`)

All routes are org-scoped: `/api/orgs/{org_id}/integrations/...`.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/providers` | `integrations:read` | Registered providers + capabilities/scopes |
| GET | `` | `integrations:read` | This org's connections |
| POST | `/{provider_id}/connect` | `integrations:manage` | 201; validates scopes, calls `test_connection()`, stores encrypted credential |
| DELETE | `/{provider_id}` | `integrations:manage` | 204 |
| POST | `/{provider_id}/sync` | `integrations:manage` | 202; schedules a job, returns `run_id` |
| GET | `/{provider_id}/sync-history` | `integrations:read` | |
| POST | `/{provider_id}/webhook` | **none** | Authenticated by the provider's own signature scheme instead of a bearer token — same pattern as `/api/stripe/webhook`. Returns 401 on bad signature, 200 on a duplicate delivery (so senders that retry on non-2xx don't retry forever), 404 for an unregistered provider. |

`integrations:read` is covered by the existing `("*", "read")` wildcard
every role already has. `integrations:manage` is not covered by any
wildcard — `admin` has no blanket `"manage"` action, only specific
`(resource, "manage")` grants (same shape as `billing`/`api_keys`/`teams`)
— so `("integrations", "manage")` was added explicitly to `admin`'s
entry in `DEFAULT_PERMISSIONS` (`app/tenancy/schema.py`). Without it,
only `owner` (which has the `("*", "*")` god-mode grant) could connect,
disconnect, or trigger a sync — the same gap `tests/test_enterprise.py`
already regression-tests for `("teams", "manage")`.

## Example provider walkthrough

`app/integrations/examples/webhook_relay_provider.py` is the reference
every future provider should model itself on. It is **not** a
placeholder — connect, verify + receive a real HMAC-signed webhook, and
run a sync all work end-to-end, because its credential is a
locally-generated shared secret (`webhook_secret`) rather than something
requiring a third-party developer account:

```python
provider = WebhookRelayProvider()
# capabilities: sync=True, webhooks=True, background_jobs=True
# scopes: [ProviderScope(id="receive", label="Receive relayed webhook events")]

await provider.test_connection(credential)          # True iff webhook_secret is set
provider.verify_webhook_signature(event, secret)     # real HMAC-SHA256 compare
await provider.sync(credential)                      # deterministic no-op SyncResult
```

## Testing framework

`tests/test_integrations.py` (65 tests, no live Postgres — pool/conn
mocked the same way as `tests/test_notifications.py`) covers:

- Registry register/unregister/get/require/list.
- `IntegrationProvider` ABC default behavior and abstractness.
- `CredentialStore`: a real Fernet encrypt/decrypt round trip (not
  mocked — only the Postgres I/O is mocked), plus corrupted-blob and
  not-found handling.
- OAuth mechanics against a mocked `httpx` token endpoint (state/PKCE
  generation, authorize-URL construction, code exchange, refresh-token
  carry-forward) — asserts no module-level config with a real
  `client_id` exists anywhere in `oauth.py`.
- Webhook pipeline: valid signature accepted, invalid rejected, and a
  duplicate delivery (`ON CONFLICT DO NOTHING` returning no row) raises
  `WebhookDuplicateError`.
- `SyncEngine`: job scheduling inserts a pending row and submits to the
  real job-queue interface (mocked), a completed job records success on
  the circuit breaker and updates the row, a missing credential fails
  cleanly.
- Circuit breaker scoping — one org's failures don't trip the breaker
  for a different org on the same provider.
- Scope validation (unknown scope rejected, sensitive-scope filtering).
- Every `integration.*` event type is declared on the platform
  `EVENT_TYPES` set; a broken event-bus publish is swallowed, not raised.
- Health probe HEALTHY/DEGRADED/UNHEALTHY thresholds from circuit-breaker
  snapshots.
- `IntegrationService` orchestration: scope/connection-test rejection,
  the happy-path connect flow (credential saved, event published, metric
  recorded), sync/webhook capability gating, disconnect-when-not-connected.
- The example provider itself.
- Router: permission-gating verification (same `inspect`-based
  `__qualname__` check `tests/test_enterprise.py` uses for other
  routers) for the six authenticated routes, explicit assertion the
  webhook route has **no** permission dependency, and all five response
  branches of the webhook endpoint (404/401/200-duplicate/200-received/400).

Run: `python -m pytest tests/test_integrations.py -v`

## What this phase deliberately does not include

- No real OAuth2 provider (Microsoft, Google, Slack, GitHub, ...) is
  registered or configured — building one is a future, credentialed
  phase per provider.
- No frontend UI for connecting/managing integrations — this phase is
  backend-framework only.
- No per-scope runtime enforcement beyond `validate_requested_scopes()`
  at connect time — a provider implementation is responsible for
  actually restricting what it does based on `credential.metadata`'s
  granted scopes.
