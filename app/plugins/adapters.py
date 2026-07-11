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
