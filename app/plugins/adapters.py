"""
Per-type registration adapters — the one place a plugin author needs to
import from, regardless of which of six different core modules actually
owns the underlying registry. Each adapter is a thin forward to an EXISTING
registry (app.ai.tools, AgentKernel, the AI provider registry, the event
bus) or one of the two genuinely-new registries this SDK adds
(WorkflowNodeRegistry, app.plugins.registry's three provider dicts) — no
registry is duplicated here, only wrapped for a single consistent surface.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.plugins.provider_types import AuthProviderBase, MemoryProviderBase, StorageProviderBase


def adapt_tool(schema: Any, fn: Callable) -> None:
    from app.ai.tools import register_tool
    register_tool(schema, fn)


def unadapt_tool(tool_name: str) -> bool:
    from app.ai.tools import unregister_tool
    return unregister_tool(tool_name)


def adapt_agent(agent: Any) -> None:
    from app.agents.kernel import get_agent_kernel
    get_agent_kernel().register_agent(agent)


def unadapt_agent(name: str) -> bool:
    from app.agents.kernel import get_agent_kernel
    return get_agent_kernel().unregister_agent(name)


def adapt_ai_provider(provider_id: str, provider: Any) -> None:
    from app.ai.providers.registry import registry as provider_registry
    provider_registry.register_provider(provider_id, provider)


def unadapt_ai_provider(provider_id: str) -> bool:
    from app.ai.providers.registry import registry as provider_registry
    return provider_registry.unregister_provider(provider_id)


def adapt_event_listener(pattern: str, handler: Callable[[Any], Awaitable[None]]) -> None:
    from app.core.events import get_event_bus
    get_event_bus().subscribe(pattern, handler)


def unadapt_event_listener(pattern: str, handler: Callable[[Any], Awaitable[None]]) -> None:
    from app.core.events import get_event_bus
    get_event_bus().unsubscribe(pattern, handler)


def adapt_workflow_node(name: str, fn: Callable) -> None:
    from app.plugins.workflow_nodes import get_workflow_node_registry
    get_workflow_node_registry().register(name, fn)


def unadapt_workflow_node(name: str) -> bool:
    from app.plugins.workflow_nodes import get_workflow_node_registry
    return get_workflow_node_registry().unregister(name)


def adapt_memory_provider(provider_id: str, provider: MemoryProviderBase) -> None:
    from app.plugins.registry import register_memory_provider
    register_memory_provider(provider_id, provider)


def unadapt_memory_provider(provider_id: str) -> bool:
    from app.plugins.registry import unregister_memory_provider
    return unregister_memory_provider(provider_id)


def adapt_storage_provider(provider_id: str, provider: StorageProviderBase) -> None:
    from app.plugins.registry import register_storage_provider
    register_storage_provider(provider_id, provider)


def unadapt_storage_provider(provider_id: str) -> bool:
    from app.plugins.registry import unregister_storage_provider
    return unregister_storage_provider(provider_id)


def adapt_auth_provider(provider_id: str, provider: AuthProviderBase) -> None:
    from app.plugins.registry import register_auth_provider
    register_auth_provider(provider_id, provider)


def unadapt_auth_provider(provider_id: str) -> bool:
    from app.plugins.registry import unregister_auth_provider
    return unregister_auth_provider(provider_id)


# ── Sandbox worker proxies ──────────────────────────────────────────────────
#
# Agent Sandbox (app/sandbox/) runs a plugin's own code inside an isolated
# worker (Docker container or subprocess) for the plugin's whole enabled
# lifetime — app/plugins/loader.py never instantiates a plugin's classes
# in-process anymore. Instead it calls worker.call("register") once, gets
# back JSON-safe registration records (name/schema/pattern — never a live
# closure, since the real closure only exists inside the worker), and
# adapt_registrations() below wires each one into the SAME real registries
# above (app.ai.tools, AgentKernel, WorkflowNodeRegistry, EventBus, the
# provider registries) — but the object handed to each adapt_*() call is a
# proxy whose every invocation dispatches back into the worker over
# app.sandbox.protocol, rather than a real in-process function. This keeps
# every existing call site (app/ai/tools.py's execute(), the workflow
# engines' step.fn(...), AgentKernel.run()->agent.run(ctx), EventBus's
# subscribe/publish) completely unchanged — they can't tell the difference
# between a real closure and a worker proxy.

class WorkerProxyCallable:
    """Stands in for a plugin's tool handler / workflow node function /
    event listener handler. Every call is dispatched into the worker and
    awaited — matches the "call it, await if awaitable" convention every
    real call site (app/ai/tools.py:execute, the workflow engines) already
    uses for a real closure."""

    def __init__(self, worker: Any, name: str) -> None:
        self._worker = worker
        self._name = name

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return await self._worker.call("invoke", method=self._name, args=list(args), kwargs=kwargs)


class WorkerProxyProvider:
    """Stands in for a MEMORY_PROVIDER/STORAGE_PROVIDER/AUTH_PROVIDER/
    AI_PROVIDER-type plugin's object, which (unlike a tool/workflow-node)
    has several distinct methods (load/append/clear, put/get/delete,
    get_authorization_url/exchange_code, ...). __getattr__ turns any
    attribute access into a proxied call dispatching that specific method
    name inside the worker (see runner_entrypoint.py's _call_invoke,
    which reads kwargs.pop("_sub_method"))."""

    def __init__(self, worker: Any, name: str) -> None:
        self._worker = worker
        self._name = name

    def __getattr__(self, method_name: str):
        async def _call(*args: Any, **kwargs: Any) -> Any:
            kwargs["_sub_method"] = method_name
            return await self._worker.call("invoke", method=self._name, args=list(args), kwargs=kwargs)
        return _call


def _make_worker_proxy_agent(name: str, worker: Any) -> Any:
    """A real EvolvableAgent subclass (not a duck-typed stand-in) so
    AgentKernel's existing agent.run(ctx) call path — validation, timing,
    health_check, to_dict — keeps working unchanged; only execute() is
    proxied into the worker. Built lazily inside a function (not a
    module-level class) because app.agents.base is a heavier import than
    the rest of this module needs for callers that never touch AGENT-type
    plugins."""
    from app.agents.base import AgentContext, AgentResult, EvolvableAgent

    class WorkerProxyAgent(EvolvableAgent):
        def __init__(self) -> None:
            self.name = name
            self._worker = worker

        async def execute(self, ctx: AgentContext) -> AgentResult:
            result = await self._worker.call(
                "invoke", method=self.name,
                kwargs={
                    "input": ctx.input, "args": ctx.args, "caller": ctx.caller,
                    "user_id": ctx.user_id, "workspace": ctx.workspace, "project_id": ctx.project_id,
                },
            )
            if isinstance(result, dict) and "success" in result:
                return AgentResult(
                    agent=result.get("agent", self.name), success=result["success"],
                    output=result.get("output", ""), data=result.get("data", {}),
                    error=result.get("error"),
                )
            return AgentResult.ok(self.name, "" if result is None else str(result))

    return WorkerProxyAgent()


_PROVIDER_ADAPTERS = {
    "memory_provider": (adapt_memory_provider, unadapt_memory_provider),
    "storage_provider": (adapt_storage_provider, unadapt_storage_provider),
    "auth_provider": (adapt_auth_provider, unadapt_auth_provider),
    "ai_provider": (adapt_ai_provider, unadapt_ai_provider),
}

# installation_id -> the list of {"type","name","proxy",...} records that
# were actually adapted, so unadapt_registrations can reverse exactly what
# adapt_registrations did without re-deriving it from the worker (which may
# already be stopped by the time unadapt runs).
_ADAPTED: dict[str, list[dict[str, Any]]] = {}


def adapt_registrations(installation_id: str, worker: Any, registrations: list[dict[str, Any]]) -> None:
    """Called once by PluginLoader right after worker.call("register")
    returns. Wires every JSON-safe registration record into the real
    registry for its type, via a proxy that dispatches back into the
    worker on every actual call."""
    adapted: list[dict[str, Any]] = []
    for reg in registrations:
        rtype, name = reg.get("type"), reg.get("name")
        if not rtype or not name:
            continue
        if rtype == "tool":
            from app.ai.models import ToolSchema
            schema = ToolSchema(**reg["schema"]) if isinstance(reg.get("schema"), dict) else reg.get("schema")
            proxy = WorkerProxyCallable(worker, name)
            adapt_tool(schema, proxy)
            adapted.append({"type": rtype, "name": name})
        elif rtype == "workflow_node":
            proxy = WorkerProxyCallable(worker, name)
            adapt_workflow_node(name, proxy)
            adapted.append({"type": rtype, "name": name})
        elif rtype == "agent":
            adapt_agent(_make_worker_proxy_agent(name, worker))
            adapted.append({"type": rtype, "name": name})
        elif rtype == "event_listener":
            pattern = reg.get("pattern", name)
            proxy = WorkerProxyCallable(worker, name)
            adapt_event_listener(pattern, proxy)
            adapted.append({"type": rtype, "name": name, "pattern": pattern, "proxy": proxy})
        elif rtype in _PROVIDER_ADAPTERS:
            adapt_fn, _ = _PROVIDER_ADAPTERS[rtype]
            adapt_fn(name, WorkerProxyProvider(worker, name))
            adapted.append({"type": rtype, "name": name})
        else:
            adapted.append({"type": "unknown", "name": name})
    _ADAPTED[installation_id] = adapted


def unadapt_registrations(installation_id: str) -> None:
    """Reverses exactly what adapt_registrations wired up for this
    installation — called by PluginLoader on disable/unload, before the
    worker itself is stopped."""
    for reg in _ADAPTED.pop(installation_id, []):
        rtype, name = reg["type"], reg["name"]
        if rtype == "tool":
            unadapt_tool(name)
        elif rtype == "workflow_node":
            unadapt_workflow_node(name)
        elif rtype == "agent":
            unadapt_agent(name)
        elif rtype == "event_listener":
            unadapt_event_listener(reg["pattern"], reg["proxy"])
        elif rtype in _PROVIDER_ADAPTERS:
            _, unadapt_fn = _PROVIDER_ADAPTERS[rtype]
            unadapt_fn(name)
