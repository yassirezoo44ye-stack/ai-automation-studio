"""
HotReloader — reload Python modules and command handlers without restart.

When a plugin file is modified, HotReloader:
  1. Unregisters the old commands from that module
  2. Re-imports the module using importlib.reload
  3. Calls register(registry) again to re-register the commands
  4. Records the reload in KernelState

This lets the kernel evolve its own command set at runtime.

Usage:
    reloader = HotReloader(registry, state)
    reloader.reload_file("app/commands/builtin/run_cmd.py")
    reloader.reload_plugin("app/commands/plugins/greet.py")
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.commands.registry import CommandRegistry
    from app.kernel.state import KernelState

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class ReloadError(Exception):
    pass


class HotReloader:
    """
    Hot-reload command modules without process restart.

    Tracks which commands each module owns so they can be cleanly
    unregistered before re-registration.
    """

    def __init__(self, registry: "CommandRegistry", state: "KernelState") -> None:
        self._registry = registry
        self._state    = state
        # module_name → list of command names it registered
        self._ownership: dict[str, list[str]] = {}

    def reload_plugin(self, file: str) -> dict:
        """
        Reload a plugin file: unregister old commands, re-import, re-register.
        Returns {"status", "module", "removed", "added"}.
        """
        path = _resolve(file)
        if not path.exists():
            raise ReloadError(f"File not found: {file}")

        module_name = _module_name(path)

        # Track which commands exist before reload
        before = set(self._registry.names())

        # Unregister commands previously owned by this module
        removed = []
        for cmd in self._ownership.get(module_name, []):
            if self._registry.unregister(cmd):
                removed.append(cmd)
                log.debug("hot-reload: unregistered %s (owned by %s)", cmd, path.name)

        # Remove from sys.modules to force full re-import
        keys_to_remove = [k for k in sys.modules if module_name in k]
        for k in keys_to_remove:
            del sys.modules[k]

        # Re-import and re-register
        spec   = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ReloadError(f"Cannot create module spec for {file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)     # type: ignore[attr-defined]

        register_fn = getattr(module, "register", None)
        if register_fn is None:
            raise ReloadError(f"{path.name} has no register() function")
        register_fn(self._registry)

        after = set(self._registry.names())
        added = list(after - before | set(removed))   # re-added are counted as added
        self._ownership[module_name] = added

        self._state.record_reload(module=str(path), trigger="hot_reload")
        log.info("hot-reloaded %s: removed=%s added=%s", path.name, removed, added)
        return {
            "status" : "reloaded",
            "module" : str(path),
            "removed": removed,
            "added"  : added,
        }

    def reload_builtin(self, module_path: str) -> dict:
        """
        Reload a builtin command module (e.g. 'app.commands.builtin.run_cmd').
        The module must be importable and must expose register(registry).
        """
        before = set(self._registry.names())

        # Remove from sys.modules
        keys = [k for k in sys.modules if k.startswith(module_path)]
        for k in keys:
            del sys.modules[k]

        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise ReloadError(f"Cannot import {module_path}: {exc}") from exc

        register_fn = getattr(module, "register", None)
        if register_fn is None:
            raise ReloadError(f"{module_path} has no register() function")
        register_fn(self._registry)

        after = set(self._registry.names())
        added = list(after - before)

        self._state.record_reload(module=module_path, trigger="reload_builtin")
        log.info("reloaded builtin %s: added=%s", module_path, added)
        return {"status": "reloaded", "module": module_path, "added": added}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve(file: str) -> Path:
    p = Path(file)
    return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()


def _module_name(path: Path) -> str:
    """Stable synthetic module name for a file path."""
    rel = str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/").replace("/", ".").removesuffix(".py")
    return rel
