# Plugin SDK

Build, package, publish, and maintain extensions to AI Automation Studio
without modifying the core platform.

## Quick start

```bash
python -m app.plugins.cli generate my_tool --type tool --author "Your Name"
```

This scaffolds `dev_plugins/my_tool/` with `manifest.json`, `plugin.py`, and
a `README.md`. See `dev_plugins/example_tool/` for a complete, working
reference implementation (a "reverse string" tool).

Five `AUTH_PROVIDER`-type reference implementations demonstrate a real
OAuth2 identity-provider integration end to end (authorize URL -> code
exchange -> normalized profile), built entirely on this SDK's existing
Sandbox + OAuth mechanics, with no real credentials shipped:
`dev_plugins/google_workspace/`, `dev_plugins/microsoft_365/`,
`dev_plugins/slack/`, `dev_plugins/github/`, `dev_plugins/discord/` — each
works once an org admin supplies a real client_id/client_secret/
redirect_uri via `PUT /plugins/installed/{id}/config` (see each plugin's
own README.md for exact provider-registration steps).

## Architecture

```
                         ┌─────────────────────────────┐
                         │   marketplace_items (+      │
                         │   marketplace_publishers)    │
                         │   — the plugin's catalog     │
                         │   listing + signature/       │
                         │   publisher trust metadata    │
                         └───────────────┬──────────────┘
                                         │ install
                                         ▼
┌────────────────────────────────────────────────────────────────────┐
│ PluginLoader (app/plugins/loader.py)                                │
│  parse manifest → verify signature → resolve trust →                │
│  check platform version → validate permissions →                    │
│  resolve marketplace deps → resolve plugin-to-plugin deps →         │
│  upsert plugin_installations → spawn Sandbox worker →               │
│  (if upgrade) migrate() → on_install → on_enable → register()       │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ spawn_worker()
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ SandboxManager (app/sandbox/manager.py)                             │
│  derives SandboxLimits from granted plugin_permissions →             │
│  DockerBackend (primary) or ProcessBackend (fallback) spawns an      │
│  isolated worker running app/sandbox/runner_entrypoint.py →          │
│  crash recovery (one respawn attempt) via call_worker()              │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ IPC (stdin/stdout JSON protocol)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ Sandbox worker (Docker container or subprocess)                     │
│  runner_entrypoint.py loads plugin_base.py + plugin_code.py in a     │
│  bare, isolated process — no `app` package, stdlib (+ what the       │
│  plugin's own code brings) only. Your PluginBase subclass runs here. │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ registrations (JSON-safe records)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ app/plugins/adapters.py                                             │
│  wires each registration into the REAL, existing platform registry   │
│  (app.ai.tools, AgentKernel, WorkflowNodeRegistry, EventBus,         │
│  provider registries) via a proxy that RPCs back into the worker      │
│  by installation_id on every call — never a fixed Worker reference,  │
│  so crash-recovery respawns are transparent to already-built proxies │
└────────────────────────────────────────────────────────────────────┘
```

## Plugin types

| Type | Registers into |
|---|---|
| `agent` | `AgentKernel` (the platform's existing agent registry) |
| `tool` | the AI tool-calling registry (`app.ai.tools`) |
| `workflow_node` | a new named-step registry for the workflow engine |
| `ai_provider` | the AI provider/model routing registry |
| `event_listener` | the platform event bus |
| `memory_provider`, `storage_provider`, `auth_provider` | new SDK-only registries (declared, not yet consumed by core code — see Scope below) |
| `ui_extension` | a declared UI slot the frontend can read |
| `marketplace_extension` | reserved for a future phase |

## The plugin interface (lifecycle)

Every plugin subclasses `PluginBase` (`app/plugins/base.py`). This class runs
**inside the Sandbox worker**, not in the main process.

```python
from app.plugins.base import PluginBase, PluginContext, PluginType

class MyPlugin(PluginBase):
    plugin_type = PluginType.TOOL

    def register(self, ctx: PluginContext) -> None:
        ...  # wire into the platform via app.plugins.adapters (required, sync)

    def unregister(self, ctx: PluginContext) -> None:
        ...  # reverse of register() (optional, sync)
```

Lifecycle hooks, called in this order over the life of an installation:

| Hook | When | Notes |
|---|---|---|
| `migrate(ctx, from_version, to_version)` | Once, only on an upgrade where the installed version actually changes; before everything below | Return a new `dict` to have the loader persist it as the installation's new config; return `None` (default) to leave it untouched. Raising aborts the upgrade the same way a `register()` failure does. |
| `on_install(ctx)` | Right after the code is loaded | |
| `on_enable(ctx)` | Every disabled → enabled transition (including first enable) | `register()` is called right after this |
| `register(ctx)` | Every enable | **Required, synchronous** — no I/O, just adapter calls |
| `on_config_change(ctx, new_config)` | After a `PUT /config` validates | Admin-initiated only — `migrate()`'s own config write does NOT re-trigger this |
| `on_disable(ctx)` | Before registrations are torn down | |
| `on_uninstall(ctx)` | Right before the code is unloaded for good | |
| `health_check()` | On demand, sync, no `ctx` | Default: reports `ENABLED` |

All hooks except `register()`/`health_check()` are `async def` with safe
no-op defaults — a minimal plugin only needs to implement `register()`.

`PluginContext` is the SDK's full surface — logging, metrics (see
Telemetry below), events, secrets, and namespaced storage — a plugin never
imports `app.core.*` directly. Every `PluginContext` method that needs I/O
(secrets, storage, events, metrics) is transparently RPC'd back to the main
process; a crashed worker respawns once automatically and the RPC retries
on the fresh worker (see Crash Recovery below).

## The manifest

Every plugin ships a `manifest.json` (validated by `app/plugins/manifest.py`
before it is ever loaded):

| Field | Notes |
|---|---|
| `id`, `name`, `version`, `author`, `description`, `category` | `category` must match a `PluginType` value |
| `dependencies` | `[{plugin_id, version_constraint, optional}]` — other **plugins** (by manifest id) this one requires, enforced at load time against what's installed+enabled for the org |
| `required_permissions` | Must be drawn from `app/marketplace/security.py`'s `ALL_KNOWN_CAPABILITIES`. Declaring `network`, `filesystem`, `shell_exec`, `credentials_read`, or `third_party_api` requires manual admin approval (`POST /plugins/installed/{id}/approve`) before it can be enabled. |
| `network_domains` | Only meaningful alongside `network`/`third_party_api` — the sandbox worker's outbound DNS allowlist is restricted to exactly these hostnames. Declaring the capability with no domains still gets no outbound access (least privilege by default). |
| `min_platform_version` / `max_platform_version` | Checked against the running `PLATFORM_VERSION` (`app/plugins/loader.py`) via the same `version_satisfies()` comparator dependencies use — supports `*`, exact `1.2.3`, `^1.2.0`, `>=`/`>`/`<=`/`<`, and comma-separated compound ranges (`>=1.0.0,<2.0.0`). |
| `entry_point` | `"module:ClassName"` — `module` is always rewritten to `plugin_code` by the sandbox worker |
| `configuration_schema` | Optional JSON-Schema-subset (`type`/`properties`/`required`/`enum`) validated against a submitted config on `PUT /config` |

## Extension guide

1. `python -m app.plugins.cli generate <name> --type <type> --author "..."`.
2. Implement `register()` (and `unregister()` if it registered anything).
3. Declare only the `required_permissions` your code actually uses — the
   sandbox derives real resource/network limits from what's *granted*
   (admin-approved), not merely declared.
4. If your plugin type needs a dependency on another plugin, add it to
   `dependencies` with a `version_constraint`.
5. If your plugin's config shape will ever change across versions,
   implement `migrate()` up front — it costs nothing when there's nothing
   to migrate (default returns `None`).
6. Bundle and publish (see Publishing below).

## Security model

- **Sandbox isolation** (`app/sandbox/`) — every plugin's code runs in an
  isolated Docker container (`--memory`/`--cpus`/`--pids-limit`/
  `--read-only` + a writable `/tmp` tmpfs) or, as a fallback when Docker is
  unavailable, a subprocess with `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC`.
  Never in-process. `SandboxLimits` (`app/sandbox/permissions.py`) derives
  concrete limits from the installation's *granted* `plugin_permissions`
  rows, not from what the manifest merely declares.
- **Network** — `none` by default. `network`/`third_party_api` widen this
  to `allowlist`, DNS-restricted (`--add-host` + a blackhole `--dns`) to
  exactly `manifest.network_domains`; this blocks resolution of
  non-allowlisted hostnames, not direct-IP connections (documented
  limitation). `internal` uses a real, non-externally-routable Docker
  bridge network.
- **Filesystem** — the plugin's own code is mounted read-only unless
  `filesystem_write` is granted; `/tmp` is always a writable scratch space
  regardless.
- **Secrets isolation** — `PluginContext.get_secret`/`set_secret` are
  Fernet-encrypted (keyed from `SESSION_SECRET`), scoped per
  `installation_id`, in `plugin_secrets`. No endpoint returns a decrypted
  value in bulk.
- **Digital signature verification** (`app/plugins/signing.py`) —
  Ed25519. Advisory unless the bundle itself declares a `signature` +
  `publisher_public_key`, in which case it must verify or the load is
  rejected outright.
- **Plugin trust model** — `signature_verified` (the bundle's signature
  checks out against *some* key) is a strictly weaker claim than
  `trusted_publisher` (that key additionally matches a **registered,
  admin-verified** `marketplace_publishers.public_key_pem`). Register a
  publisher's key via `POST /api/admin/marketplace/publishers/{id}/public-key`
  (admin API key only) after verifying them via the existing
  `.../verify` endpoint.
- **Runtime crash recovery** — a worker that crashes mid-call is
  respawned exactly once (`SandboxManager.call_worker`); a second
  consecutive crash propagates rather than looping forever.
- **Audit logging** — every load/unload/enable/disable/reload/error
  event is written to `plugin_health_log`; sandbox-level lifecycle,
  network, security, and resource events go to `sandbox_events`.
- **No privilege escalation path** — approval is required before a
  sensitive-capability plugin can be *enabled* (not just installed);
  capabilities are checked against `plugin_permissions.granted`
  (admin-controlled), never against the manifest's raw declaration.

## Versioning strategy

Bump `manifest.json`'s `version`, publish a new marketplace listing version
(same `POST /marketplace/listings` endpoint, matching id, new version +
changelog), and existing installations can `POST
/plugins/installed/{id}/upgrade` to move to it. If the installed version is
actually changing, `PluginLoader.load()` calls your plugin's `migrate()`
hook (see Lifecycle above) before `on_install`/`on_enable`/`register()` run
for the new version — this is where you transform an old config shape into
the new one.

Check compatibility *before* upgrading anything (platform or a specific
plugin) via `GET /plugins/compatibility-matrix` — for every plugin
installed in your org it reports platform-version compatibility
(`min_platform_version`/`max_platform_version` vs the running
`PLATFORM_VERSION`) and cross-plugin dependency satisfaction, using the
exact same `version_satisfies()` checks `load()` enforces one at a time.

## Public APIs

`GET /plugins/installed`, and per-installation `enable`/`disable`/
`approve`/`upgrade`/`reload`/`config`/`health`/`logs`/`capabilities` under
`/plugins/installed/{id}/*`. `reload` (hot reload) only works when
`PLUGIN_HOT_RELOAD_ENABLED=true` is set — never enable this in production.

Discovery and compatibility (no installation required to call):
- `GET /plugins/capabilities` — the platform-wide catalog of every
  declarable capability and `PluginType`.
- `GET /plugins/installed/{id}/capabilities` — what a specific
  installation was actually granted and actually registered.
- `GET /plugins/compatibility-matrix` — see Versioning strategy above.

## Telemetry & health

`PluginContext.emit_metric(name, value, **tags)` records into the
platform's real `MetricsRegistry` (`app/core/observability/metrics.py`) as
a gauge named `plugin_{plugin_id}_{name}`, in addition to a structured log
line and a `sandbox_events` row — not a dead-end log-only stub.

A dedicated `sandbox_workers` health probe (`app/sandbox/health.py`,
registered alongside but distinct from the coarser `plugin_loader`
active-instance probe) reports the actual crash ratio of sandbox workers
spawned in the last hour.

## Publishing

Package `manifest.json` and `plugin.py`'s contents into a single JSON object
— `{"manifest": {...}, "code": "<plugin.py contents>", "signature": "...",
"publisher_public_key": "..."}` (the last two optional) — and publish it as
a marketplace listing's inline asset via `POST /marketplace/listings` with
`type: "plugin"`. Installing that listing (the existing `POST
/marketplace/listings/{id}/install` endpoint) is what actually loads and
activates your code for an organization.

## Example plugins

See the Quick start section above for the 5 shipped `AUTH_PROVIDER`
examples (Google Workspace, Microsoft 365, Slack, GitHub, Discord) — each
plugin's own `README.md` documents exactly which real, publicly documented
provider endpoints it talks to and how to register a real OAuth app for it.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `PluginNotApprovedError` on enable | Manifest declares a sensitive capability (`network`, `filesystem`, `shell_exec`, `credentials_read`, `third_party_api`) | `POST /plugins/installed/{id}/approve` as an admin first |
| `PlatformVersionError` | `min_platform_version`/`max_platform_version` doesn't satisfy the running `PLATFORM_VERSION` | Check `GET /plugins/compatibility-matrix`; bump the manifest's version bounds if genuinely compatible |
| `PluginDependencyError` | A declared plugin-to-plugin dependency isn't installed+enabled for this org, or its version doesn't satisfy the constraint | Install/enable the dependency first, or loosen `version_constraint` |
| Load fails with "signature verification failed" | A bundle declared both `signature` and `publisher_public_key`, but they don't match the code | Re-sign with `app/plugins/signing.py`'s `sign_code()`, or omit both fields to ship unsigned (advisory-only) |
| Plugin worker never responds / times out | Worker crashed; if it recovers on the *next* call, that's expected (one automatic respawn) — repeated crashes on every call mean the plugin's own code is failing on start | Check `GET /plugins/installed/{id}/logs` and `sandbox_events` for the crash's actual error |
| Config looks stale right after an upgrade | `migrate()`'s returned config takes effect on the *next* load/enable, not hot-swapped into the worker that's still mid-upgrade | Expected — re-`enable` or wait for the next natural reload |
| `reload` returns 403 | `PLUGIN_HOT_RELOAD_ENABLED` isn't set to `true` | Dev-only; never set this in production |

## Scope of this phase

This SDK provides the manifest, loader, permission-declaration, sandbox
isolation, trust/signature model, compatibility/migration tooling, API, and
frontend scaffolding. It does **not** yet include:

- **Real zip/multi-file plugin bundles** — only single-file inline plugins
  load this phase.
- **UI Extension rendering** — slots are stored; the frontend doesn't yet
  dynamically load and render plugin-provided components.
- **`memory_provider`/`storage_provider`/`auth_provider` platform wiring** —
  a plugin can register one of these, but no core code (conversation
  loading, file storage, OAuth) routes through a registered provider yet.
- **Rollback** (version pinning/revert) for plugin installations — the
  marketplace's own listing rollback exists; an installed plugin's own
  version isn't yet independently revertible.
- **DNS-allowlist enforcement against direct-IP connections** — documented
  limitation, see Security model above.
