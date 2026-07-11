"""
Plugin SDK — core interface every plugin implements.

Ten plugin types share one lifecycle (PluginBase) and one runtime context
(PluginContext, the Logging/Metrics/Event/Secret/Storage/Config API surface
handed to every hook). A plugin's `register()` method is where it wires
itself into the platform's EXISTING registries (app.ai.tools, AgentKernel,
the AI provider registry, the event bus) via the thin adapters in
app/plugins/adapters.py — this module intentionally does not duplicate any
of those registries itself.

Mirrors app/services/registry.py's BaseService/ServiceHealth shape (tick/
on_start/on_stop, a state machine, health()) generalized for installable,
per-organization plugins instead of singleton background services.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PluginType(str, Enum):
    AGENT                  = "agent"
    TOOL                   = "tool"
    WORKFLOW_NODE          = "workflow_node"
    AI_PROVIDER            = "ai_provider"
    MEMORY_PROVIDER        = "memory_provider"
    AUTH_PROVIDER          = "auth_provider"
    STORAGE_PROVIDER       = "storage_provider"
    UI_EXTENSION           = "ui_extension"
    MARKETPLACE_EXTENSION  = "marketplace_extension"
    EVENT_LISTENER         = "event_listener"


class PluginState(str, Enum):
    INSTALLED   = "installed"
    ENABLED     = "enabled"
    DISABLED    = "disabled"
    FAILED      = "failed"
    UNINSTALLED = "uninstalled"


@dataclass
class PluginHealth:
    plugin_id : str
    state     : PluginState
    message   : Optional[str] = None
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id" : self.plugin_id,
            "state"     : self.state.value,
            "message"   : self.message,
            "checked_at": self.checked_at,
        }


@dataclass
class PluginContext:
    """Runtime handle passed to every lifecycle hook and to register().

    This is the SDK's Context/Logging/Metrics/Event/Secret/Storage/
    Configuration API surface — a plugin never imports app.core.* directly,
    it only ever talks to the platform through this object, so the platform
    stays free to change its own internals without breaking plugins.
    """
    plugin_id      : str
    installation_id: str
    organization_id: Optional[str]
    config          : dict[str, Any]
    logger          : logging.Logger

    # ── Metrics API ───────────────────────────────────────────────────────
    def emit_metric(self, name: str, value: float, **tags: Any) -> None:
        """Best-effort — this platform has no dedicated metrics backend yet
        (confirmed: no existing metrics sink beyond structured logging), so
        this logs a structured line a log pipeline can aggregate on. Kept as
        a stable API so plugins don't need to change when a real backend
        lands."""
        self.logger.info("metric plugin=%s name=%s value=%s tags=%s",
                          self.plugin_id, name, value, tags)

    # ── Event API ─────────────────────────────────────────────────────────
    async def emit_event(self, type_: str, data: dict[str, Any]) -> None:
        """Publishes onto the platform's existing EventBus. `type_` must
        already be declared in app.core.events.bus.EVENT_TYPES — plugins
        cannot register new event types this phase (no escape hatch), they
        reuse the existing allowlisted topics (e.g. "marketplace.installed"-
        style namespacing is reserved for core; plugin-relevant topics are
        the "job.*"/"agent.*" ones already declared)."""
        from app.core.events import get_event_bus
        await get_event_bus().publish(type_, data, organization_id=self.organization_id)

    # ── Secret API ────────────────────────────────────────────────────────
    async def get_secret(self, key: str) -> Optional[str]:
        from app.plugins.secrets import get_plugin_secret
        return await get_plugin_secret(self.installation_id, key)

    async def set_secret(self, key: str, value: str) -> None:
        from app.plugins.secrets import set_plugin_secret
        await set_plugin_secret(self.installation_id, key, value)

    # ── Storage API ───────────────────────────────────────────────────────
    async def storage_get(self, key: str) -> Any:
        from app.plugins.storage import get_plugin_value
        return await get_plugin_value(self.installation_id, key)

    async def storage_put(self, key: str, value: Any) -> None:
        from app.plugins.storage import put_plugin_value
        await put_plugin_value(self.installation_id, key, value)

    async def storage_delete(self, key: str) -> None:
        from app.plugins.storage import delete_plugin_value
        await delete_plugin_value(self.installation_id, key)


class PluginBase(ABC):
    """Every plugin subclasses this. `plugin_type` and `register()` are
    required; the lifecycle hooks have safe no-op defaults so a minimal
    plugin only needs to implement register()."""

    plugin_type: PluginType

    async def on_install(self, ctx: PluginContext) -> None:
        """Called once, right after the code is loaded for the first time."""

    async def on_enable(self, ctx: PluginContext) -> None:
        """Called every time the plugin transitions disabled → enabled
        (including the first enable after install). This is where
        register() is actually invoked by the loader — see loader.py."""

    async def on_disable(self, ctx: PluginContext) -> None:
        """Called before the plugin's registrations are torn down."""

    async def on_uninstall(self, ctx: PluginContext) -> None:
        """Called once, right before the plugin's code is unloaded for good."""

    async def on_config_change(self, ctx: PluginContext, new_config: dict[str, Any]) -> None:
        """Called after a PUT to the plugin's /config endpoint validates
        successfully against its configuration_schema."""

    def health_check(self) -> PluginHealth:
        """Default: report ENABLED with no message. Override for a real
        liveness probe (e.g. an AI_PROVIDER plugin pinging its endpoint)."""
        return PluginHealth(plugin_id=self.plugin_type.value, state=PluginState.ENABLED)

    @abstractmethod
    def register(self, ctx: PluginContext) -> None:
        """Wire this plugin into the platform — call the matching adapter
        in app.plugins.adapters for this plugin's type. Synchronous by
        design: registration is in-memory dict/list mutation, never I/O."""

    def unregister(self, ctx: PluginContext) -> None:
        """Reverse of register() — remove this plugin's entries from
        whatever registry register() added them to. Default no-op; override
        if register() did anything (most types should override this)."""
