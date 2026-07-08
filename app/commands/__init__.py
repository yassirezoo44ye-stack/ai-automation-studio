"""
Command-Driven Runtime System.

Public API:

    from app.commands import get_runner, get_registry

    # Execute a raw command string
    result = await get_runner().execute("run ./my-project")

    # Register a new command at runtime
    get_registry().register("greet", greet_handler, description="Say hello")

    # Auto-load plugins
    from app.commands import load_plugins
    load_plugins()

Process-lifetime singletons are created on first import.
Built-in commands are registered automatically.
Plugin directories are scanned when load_plugins() is called.
"""
from __future__ import annotations

from app.commands.context import CommandContext
from app.commands.registry import CommandRegistry
from app.commands.result import CommandResult
from app.commands.runner import CommandRunner

# ── Process-lifetime singletons ───────────────────────────────────────────────

_registry: CommandRegistry | None = None
_runner:   CommandRunner   | None = None


def _build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    # Register all built-in commands
    from app.commands.builtin import (
        build_cmd, deploy_cmd, help_cmd, inspect_cmd, modify_cmd, run_cmd,
    )
    for module in (help_cmd, run_cmd, build_cmd, modify_cmd, inspect_cmd, deploy_cmd):
        module.register(registry)
    return registry


def get_registry() -> CommandRegistry:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_runner() -> CommandRunner:
    global _runner
    if _runner is None:
        _runner = CommandRunner(get_registry())
    return _runner


def load_plugins(extra_dirs=None) -> int:
    """Scan plugin directories and load any found. Returns count loaded."""
    from app.commands.loader import load_plugins as _load
    return _load(get_registry(), extra_dirs)


__all__ = [
    "CommandContext", "CommandRegistry", "CommandResult", "CommandRunner",
    "get_registry", "get_runner", "load_plugins",
]
