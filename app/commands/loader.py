"""
PluginLoader — auto-loads commands from plugin directories.

Any Python file inside:
    app/commands/plugins/
    <project_root>/plugins/
    <project_root>/commands/

that contains a top-level `register(registry)` function is loaded
automatically at startup.  The function receives the CommandRegistry
and calls registry.register() for each command it provides.

No manual wiring in core required — drop a file, restart, done.

Example plugin (plugins/hello.py):

    from app.commands.registry import CommandRegistry
    from app.commands.context import CommandContext
    from app.commands.result import CommandResult

    async def hello_handler(ctx: CommandContext) -> CommandResult:
        name = ctx.first_arg("world")
        return CommandResult.ok("hello", output=f"Hello, {name}!")

    def register(registry: CommandRegistry) -> None:
        registry.register(
            "hello",
            hello_handler,
            description="Say hello",
            group="demo",
            source="plugin",
        )
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.commands.registry import CommandRegistry

log = logging.getLogger(__name__)

# Directories scanned for plugins (in priority order)
_PLUGIN_DIRS: list[Path] = []


def _default_plugin_dirs() -> list[Path]:
    project_root = Path(__file__).parent.parent.parent  # repo root
    return [
        Path(__file__).parent / "plugins",   # app/commands/plugins/
        project_root / "plugins",            # <repo>/plugins/
        project_root / "commands",           # <repo>/commands/
    ]


def load_plugins(registry: "CommandRegistry", extra_dirs: list[Path] | None = None) -> int:
    """
    Scan all plugin directories and call register(registry) in each module found.
    Returns the count of successfully loaded plugins.
    """
    dirs = _default_plugin_dirs() + (extra_dirs or [])
    loaded = 0
    for directory in dirs:
        loaded += _load_dir(registry, directory)
    return loaded


def _load_dir(registry: "CommandRegistry", directory: Path) -> int:
    if not directory.is_dir():
        return 0
    count = 0
    for py_file in sorted(directory.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        if _load_file(registry, py_file):
            count += 1
    return count


def _load_file(registry: "CommandRegistry", path: Path) -> bool:
    module_name = f"_plugin_{path.stem}_{id(path)}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            log.warning("plugin loader: could not create spec for %s", path)
            return False
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)     # type: ignore[attr-defined]

        register_fn = getattr(module, "register", None)
        if register_fn is None:
            log.debug("plugin %s has no register() function — skipped", path.name)
            return False

        register_fn(registry)
        log.info("loaded plugin: %s", path.name)
        return True
    except Exception as exc:
        log.warning("plugin %s failed to load: %s", path.name, exc)
        return False
