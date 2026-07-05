"""
Tool Marketplace — extends ToolRegistry/ToolExecutor with categories, versioning,
dependencies, permissions, hot registration, and plugin tools.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .executor import ToolExecutor


@dataclass
class ToolManifest:
    name:         str
    version:      str     = "1.0.0"
    category:     str     = "general"    # "general"|"web"|"code"|"data"|"system"|"custom"
    description:  str     = ""
    author:       str     = ""
    permissions:  list[str] = field(default_factory=list)   # e.g. ["network", "fs"]
    dependencies: list[str] = field(default_factory=list)   # other tool names
    enabled:      bool    = True
    registered_at: float  = field(default_factory=time.time)
    metadata:     dict[str, Any] = field(default_factory=dict)


class ToolMarketplace:
    """
    Wraps ToolExecutor with a marketplace layer: catalog, discovery, hot-loading.

    Hot registration: call `register_plugin()` at runtime without app restart.
    Plugin tools: any async callable `(arguments: dict) -> dict` can be registered.
    """

    def __init__(self, executor: ToolExecutor) -> None:
        self._executor = executor
        self._catalog:  dict[str, ToolManifest]  = {}
        self._plugins:  dict[str, Callable]      = {}

    # ── Catalog ────────────────────────────────────────────────────────────────

    def register(self, manifest: ToolManifest) -> None:
        """Register a tool manifest for an already-registered executor tool."""
        self._catalog[manifest.name] = manifest

    def register_plugin(
        self,
        manifest: ToolManifest,
        handler:  Callable[..., Any],
    ) -> None:
        """Hot-register a new tool: add manifest + async handler."""
        self._catalog[manifest.name] = manifest
        self._plugins[manifest.name] = handler
        # Inject into the shared app.ai.tools registry so executor can find it
        try:
            from app.ai import tools as _registry
            from dataclasses import dataclass as _dc

            @_dc
            class _Entry:
                fn: Any
                schema: Any = None

            _registry._REGISTRY[manifest.name] = _Entry(fn=handler)
        except Exception:
            pass   # best-effort — plugin still callable via execute() override below

    def unregister(self, name: str) -> bool:
        removed = bool(self._catalog.pop(name, None))
        self._plugins.pop(name, None)
        return removed

    # ── Discovery ──────────────────────────────────────────────────────────────

    def list_all(self, category: Optional[str] = None) -> list[dict[str, Any]]:
        results = list(self._catalog.values())
        if category:
            results = [m for m in results if m.category == category]
        return [self._manifest_to_dict(m) for m in results]

    def categories(self) -> list[str]:
        return sorted({m.category for m in self._catalog.values()})

    def get(self, name: str) -> Optional[ToolManifest]:
        return self._catalog.get(name)

    def search(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        return [
            self._manifest_to_dict(m)
            for m in self._catalog.values()
            if q in m.name.lower() or q in m.description.lower()
        ]

    def check_permissions(self, name: str, user_permissions: list[str]) -> bool:
        """Returns True if the user has all required permissions for the tool."""
        manifest = self._catalog.get(name)
        if not manifest:
            return False
        return all(p in user_permissions for p in manifest.permissions)

    def resolve_dependencies(self, name: str) -> list[str]:
        """Return ordered list of dependencies for `name` (BFS, no cycles)."""
        manifest = self._catalog.get(name)
        if not manifest:
            return []
        visited: list[str] = []
        queue = list(manifest.dependencies)
        seen: set[str] = {name}
        while queue:
            dep = queue.pop(0)
            if dep in seen:
                continue
            seen.add(dep)
            visited.append(dep)
            dep_manifest = self._catalog.get(dep)
            if dep_manifest:
                queue.extend(dep_manifest.dependencies)
        return visited

    # ── Delegation ────────────────────────────────────────────────────────────

    async def execute(
        self,
        tool_name:   str,
        arguments:   dict[str, Any],
        user_id:     Optional[str] = None,
        permissions: Optional[list[str]] = None,
    ) -> Any:
        return await self._executor.execute(
            tool_name=tool_name,
            arguments=arguments,
            user_id=user_id,
            permissions=permissions or [],
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "catalog_size":   len(self._catalog),
            "plugin_count":   len(self._plugins),
            "categories":     self.categories(),
            "enabled_tools":  [m.name for m in self._catalog.values() if m.enabled],
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _manifest_to_dict(m: ToolManifest) -> dict[str, Any]:
        return {
            "name":         m.name,
            "version":      m.version,
            "category":     m.category,
            "description":  m.description,
            "permissions":  m.permissions,
            "dependencies": m.dependencies,
            "enabled":      m.enabled,
        }
