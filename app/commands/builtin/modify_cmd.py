"""
modify — runtime and file modification command.

Allows reshaping the running application without restart.

Sub-actions:
    modify register <name> <handler_path>
        Register a new command at runtime from a Python file.

    modify unregister <name>
        Remove a command from the registry.

    modify file --file=<path> --action=<append|prepend|replace> --content=<text>
        Modify a file in a project workspace.

    modify env --key=<K> --value=<V>
        Set/override a runtime environment variable for subsequent commands.

    modify config --key=<K> --value=<V>
        Update a runtime configuration key.

Usage:
    modify register greet ./plugins/greet.py
    modify unregister greet
    modify file --file=./main.py --action=append --content="# added"
    modify env --key=PORT --value=4000
"""
from __future__ import annotations

import os
from pathlib import Path

from app.commands.context import CommandContext
from app.commands.result import CommandResult

# Mutable runtime config — survives within process lifetime
_RUNTIME_CONFIG: dict[str, str] = {}


async def modify_handler(ctx: CommandContext) -> CommandResult:
    action = ctx.first_arg()
    if not action:
        return CommandResult.fail(
            "modify",
            "Usage: modify <action> [args]  —  actions: register, unregister, file, env, config",
            "MISSING_ACTION",
        )

    dispatch = {
        "register"  : _modify_register,
        "unregister": _modify_unregister,
        "file"      : _modify_file,
        "env"       : _modify_env,
        "config"    : _modify_config,
    }
    fn = dispatch.get(action)
    if fn is None:
        return CommandResult.fail(
            "modify",
            f"Unknown modify action: '{action}'",
            "UNKNOWN_ACTION",
            suggestions=[f"Available actions: {', '.join(dispatch)}"],
        )
    return await fn(ctx)


# ── Sub-actions ───────────────────────────────────────────────────────────────

async def _modify_register(ctx: CommandContext) -> CommandResult:
    """Dynamically register a command from a Python file at runtime."""
    args = ctx.args[1:]  # skip "register"
    if len(args) < 2:
        return CommandResult.fail("modify", "Usage: modify register <name> <plugin_file>",
                                  "MISSING_ARGS")
    name, plugin_path = args[0], args[1]
    path = Path(plugin_path).expanduser().resolve()
    if not path.exists():
        return CommandResult.fail("modify", f"Plugin file not found: {path}", "FILE_NOT_FOUND")

    from app.commands import get_registry
    from app.commands.loader import _load_file
    registry = get_registry()

    ok = _load_file(registry, path)
    if not ok:
        return CommandResult.fail("modify", f"Plugin {path.name} has no register() function",
                                  "PLUGIN_NO_REGISTER")

    return CommandResult.ok(
        "modify",
        output=f"✓ Registered commands from {path.name}",
        data={"plugin": str(path), "action": "register"},
    )


async def _modify_unregister(ctx: CommandContext) -> CommandResult:
    """Remove a command from the registry at runtime."""
    args = ctx.args[1:]
    if not args:
        return CommandResult.fail("modify", "Usage: modify unregister <command-name>",
                                  "MISSING_ARGS")
    name = args[0]
    from app.commands import get_registry
    removed = get_registry().unregister(name)
    if not removed:
        return CommandResult.fail("modify", f"Command '{name}' not found in registry",
                                  "NOT_FOUND")
    return CommandResult.ok("modify", output=f"✓ Unregistered command: {name}",
                            data={"action": "unregister", "name": name})


async def _modify_file(ctx: CommandContext) -> CommandResult:
    """Modify a file: append, prepend, or replace content."""
    file_path = ctx.flag("file", ctx.flag("f"))
    action    = ctx.flag("action", ctx.flag("a", "append"))
    content   = ctx.flag("content", ctx.flag("c", ""))

    if not file_path:
        return CommandResult.fail("modify", "Usage: modify file --file=<path> --action=<append|prepend|replace> --content=<text>",
                                  "MISSING_ARGS")

    p = Path(file_path).expanduser().resolve()
    if not p.exists() and action != "replace":
        return CommandResult.fail("modify", f"File not found: {p}", "FILE_NOT_FOUND")

    try:
        original = p.read_text(encoding="utf-8") if p.exists() else ""
        if action == "append":
            p.write_text(original + "\n" + content, encoding="utf-8")
        elif action == "prepend":
            p.write_text(content + "\n" + original, encoding="utf-8")
        elif action == "replace":
            p.write_text(content, encoding="utf-8")
        else:
            return CommandResult.fail("modify", f"Unknown file action: '{action}'",
                                      "UNKNOWN_ACTION",
                                      suggestions=["Valid actions: append, prepend, replace"])
        return CommandResult.ok("modify", output=f"✓ File modified ({action}): {p}",
                                data={"file": str(p), "action": action})
    except Exception as exc:
        return CommandResult.fail("modify", f"Could not modify file: {exc}", "IO_ERROR")


async def _modify_env(ctx: CommandContext) -> CommandResult:
    """Set a runtime environment variable."""
    key   = ctx.flag("key", ctx.flag("k"))
    value = ctx.flag("value", ctx.flag("v"))
    if not key:
        return CommandResult.fail("modify", "Usage: modify env --key=K --value=V", "MISSING_ARGS")
    os.environ[key] = value
    return CommandResult.ok("modify", output=f"✓ ENV {key}={value!r}",
                            data={"action": "env", "key": key, "value": value})


async def _modify_config(ctx: CommandContext) -> CommandResult:
    """Update a runtime configuration key (in-process only)."""
    key   = ctx.flag("key", ctx.flag("k"))
    value = ctx.flag("value", ctx.flag("v"))
    if not key:
        return CommandResult.fail("modify", "Usage: modify config --key=K --value=V",
                                  "MISSING_ARGS")
    _RUNTIME_CONFIG[key] = value
    return CommandResult.ok("modify",
                            output=f"✓ Config {key}={value!r}  (process-lifetime only)",
                            data={"action": "config", "key": key, "value": value,
                                  "all_config": dict(_RUNTIME_CONFIG)})


def get_runtime_config() -> dict[str, str]:
    return dict(_RUNTIME_CONFIG)


def register(registry) -> None:
    registry.register(
        "modify",
        modify_handler,
        description="Modify runtime behaviour, commands, or project files",
        aliases=["mod", "patch"],
        group="runtime",
        usage="modify <register|unregister|file|env|config> [args]",
    )
