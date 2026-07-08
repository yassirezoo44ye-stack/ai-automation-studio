"""
RuntimeRegistry — Phase 10 (Plugin Architecture).

Maintains the ordered list of registered runtime adapters.
Selects the best runtime for a given workspace via detect().

Runtimes are tried in priority order (lowest number wins).
The first runtime whose detect() returns True is selected.

Built-in runtimes registered at module load:
  10  NodeRuntime
  20  PythonRuntime
  30  DockerRuntime
  40  ElectronRuntime

Plugin runtimes are registered via RuntimeRegistry.register().
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.execution.platform.runtimes.abstract import AbstractRuntime

log = logging.getLogger(__name__)


class RuntimeRegistry:
    """
    Ordered registry of runtime adapters.

    Usage:
        registry = RuntimeRegistry.default()
        runtime = registry.select(workspace)
    """

    def __init__(self) -> None:
        self._runtimes: list[AbstractRuntime] = []

    def register(self, runtime: AbstractRuntime) -> None:
        """Register a runtime adapter. Sorted by priority after each insert."""
        self._runtimes.append(runtime)
        self._runtimes.sort(key=lambda r: r.priority)
        log.debug("registered runtime: %s (priority=%d)", runtime.name, runtime.priority)

    def select(self, workspace: Path) -> Optional[AbstractRuntime]:
        """
        Return the highest-priority runtime that detects the workspace.
        Returns None if no runtime matches.
        """
        for rt in self._runtimes:
            try:
                if rt.detect(workspace):
                    log.info("runtime selected: %s for workspace %s", rt.name, workspace)
                    return rt
            except Exception as exc:
                log.warning("runtime %s detect() raised: %s", rt.name, exc)
        log.warning("no runtime detected for workspace: %s", workspace)
        return None

    def all(self) -> list[AbstractRuntime]:
        return list(self._runtimes)

    @classmethod
    def default(cls) -> "RuntimeRegistry":
        """Create a registry pre-loaded with all built-in runtimes."""
        from app.execution.platform.runtimes.node        import NodeRuntime
        from app.execution.platform.runtimes.python_rt   import PythonRuntime
        from app.execution.platform.runtimes.docker_rt   import DockerRuntime
        from app.execution.platform.runtimes.electron_rt import ElectronRuntime

        registry = cls()
        for rt in (NodeRuntime(), PythonRuntime(), DockerRuntime(), ElectronRuntime()):
            registry.register(rt)
        return registry


# Process-lifetime default registry
_default_registry = RuntimeRegistry.default()


def get_registry() -> RuntimeRegistry:
    return _default_registry
