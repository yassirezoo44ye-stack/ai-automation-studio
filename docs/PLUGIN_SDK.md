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

## The plugin interface

Every plugin subclasses `PluginBase` (`app/plugins/base.py`):

```python
from app.plugins.base import PluginBase, PluginContext, PluginType

class MyPlugin(PluginBase):
    plugin_type = PluginType.TOOL

    def register(self, ctx: PluginContext) -> None:
        ...  # wire into the platform via app.plugins.adapters

    def unregister(self, ctx: PluginContext) -> None:
        ...  # reverse of register()
```

Lifecycle hooks (`on_install`, `on_enable`, `on_disable`, `on_uninstall`,
`on_config_change`) and `health_check()` all have safe no-op defaults.

`PluginContext` is the SDK's full surface — logging, metrics, events,
secrets, and namespaced storage — a plugin never imports `app.core.*`
directly.

## The manifest

Every plugin ships a `manifest.json` (validated by `app/plugins/manifest.py`
before it is ever loaded): `id`, `name`, `version`, `author`, `description`,
`category`, `dependencies`, `required_permissions`, `min_platform_version`/
`max_platform_version`, `entry_point` (`"module:ClassName"`), and an optional
`configuration_schema`.

`required_permissions` must be drawn from the platform's known-capability
list (`app/marketplace/security.py`'s `ALL_KNOWN_CAPABILITIES`). A plugin
declaring `network`, `filesystem`, `shell_exec`, `credentials_read`, or
`third_party_api` requires manual admin approval (`POST
/plugins/installed/{id}/approve`) before it can be enabled.

## Publishing

Package `manifest.json` and `plugin.py`'s contents into a single JSON object
— `{"manifest": {...}, "code": "<plugin.py contents>"}` — and publish it as
a marketplace listing's inline asset via `POST /marketplace/listings` with
`type: "plugin"`. Installing that listing (the existing `POST
/marketplace/listings/{id}/install` endpoint) is what actually loads and
activates your code for an organization.

## Managing installed plugins

`GET /plugins/installed`, and per-installation `enable`/`disable`/
`approve`/`upgrade`/`reload`/`config`/`health`/`logs` under
`/plugins/installed/{id}/*`. `reload` (hot reload) only works when
`PLUGIN_HOT_RELOAD_ENABLED=true` is set — never enable this in production.

## Version migration

Bump `manifest.json`'s `version`, publish a new marketplace listing version
(same `POST /marketplace/listings` endpoint, matching id, new version +
changelog), and existing installations can `POST
/plugins/installed/{id}/upgrade` to move to it.

## Scope of this phase

This SDK provides the manifest, loader, permission-declaration, API, and
frontend scaffolding. It does **not** include:

- **Agent Sandbox** — no subprocess isolation, no resource limits, no real
  execution sandboxing. Plugin code runs in-process with full interpreter
  access (the same trust model `app/commands/loader.py` already uses for
  CLI command plugins). Declared permissions are validated and stored, not
  runtime-enforced.
- **Real zip/multi-file plugin bundles** — only single-file inline plugins
  load this phase.
- **UI Extension rendering** — slots are stored; the frontend doesn't yet
  dynamically load and render plugin-provided components.
- **`memory_provider`/`storage_provider`/`auth_provider` platform wiring** —
  a plugin can register one of these, but no core code (conversation
  loading, file storage, OAuth) routes through a registered provider yet.
