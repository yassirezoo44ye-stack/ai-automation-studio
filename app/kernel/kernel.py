"""
AIKernel — the central AI Operating System kernel.

Replaces the simple CommandRunner with a full lifecycle system:

  Boot sequence:
    1. Initialize KernelState (persistent)
    2. Build PolicyEngine
    3. Build SelfModifyingEngine
    4. Build HotReloader
    5. Run middleware pipeline
    6. Load plugins (auto-discovery)
    7. Register kernel commands (reload, status, patch, rollback, agent-ls)
    8. Kernel is ready

  Execution path for every command:
    input → middleware pipeline → KernelContext
    KernelContext → CommandRunner → CommandAgent
    CommandAgent lifecycle: initialize → execute → finalize
    → CommandResult

  Self-modification path:
    modify patch → PolicyEngine.check_write → SelfModifyingEngine.patch
    → KernelState.record_modification → HotReloader.reload_plugin

The Kernel is a singleton — one per process.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, TYPE_CHECKING

from app.commands.context import CommandContext
from app.commands.registry import CommandRegistry
from app.commands.result import CommandResult
from app.commands.runner import CommandRunner, _parse
from app.kernel.agents.command_agent import CommandAgent
from app.kernel.middleware import (
    KernelContext,
    MiddlewareFn,
    default_pipeline,
)
from app.kernel.policy import PolicyEngine
from app.kernel.reloader import HotReloader
from app.kernel.self_modify import SelfModifyingEngine
from app.kernel.state import KernelState

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class AIKernel:
    """
    The AI Operating System kernel.

    Usage:
        kernel = AIKernel()
        kernel.boot()
        result = await kernel.execute("modify patch app/kernel/state.py ...")
        print(result.to_cli_text())
    """

    def __init__(self) -> None:
        self.state    = KernelState()
        self.policy   = PolicyEngine()
        self.modifier = SelfModifyingEngine(self.policy, self.state)
        self.registry = CommandRegistry()
        self.reloader = HotReloader(self.registry, self.state)
        self._runner  = CommandRunner(self.registry)
        self._mw: list[MiddlewareFn] = default_pipeline(self.state)
        self._booted  = False

    # ── Boot ─────────────────────────────────────────────────────────────────

    def boot(self, load_plugins: bool = True) -> None:
        """
        Full kernel boot sequence.
        Idempotent — safe to call multiple times.
        """
        if self._booted:
            return

        t0 = time.monotonic()
        log.info("kernel boot started")

        # Register built-in commands (same set as CommandRunner)
        from app.commands.builtin import (
            build_cmd, deploy_cmd, help_cmd, inspect_cmd, modify_cmd, run_cmd,
        )
        for mod in (help_cmd, run_cmd, build_cmd, modify_cmd, inspect_cmd, deploy_cmd):
            mod.register(self.registry)

        # Register kernel-native commands
        _register_kernel_commands(self.registry, self)

        # Auto-load plugins
        if load_plugins:
            from app.commands.loader import load_plugins as _load_plugins
            n = _load_plugins(self.registry)
            log.info("kernel boot: %d plugins loaded", n)

        self._booted = True
        boot_ms = (time.monotonic() - t0) * 1000
        log.info("kernel boot complete in %.1f ms  commands=%d", boot_ms, len(self.registry.names()))
        self.state.set("boot_ms", round(boot_ms, 1))

    # ── Middleware registration ────────────────────────────────────────────────

    def use(self, fn: MiddlewareFn) -> None:
        """Add middleware to the pipeline (appended after built-ins)."""
        self._mw.append(fn)

    def use_first(self, fn: MiddlewareFn) -> None:
        """Prepend middleware (runs before all others)."""
        self._mw.insert(0, fn)

    # ── Execution ─────────────────────────────────────────────────────────────

    async def execute(
        self,
        raw: str,
        *,
        caller: str = "cli",
        user_id: Optional[str] = None,
    ) -> CommandResult:
        """
        Full kernel execution path:
        raw input → middleware → agent → result.
        Never raises.
        """
        # ── Middleware pipeline ───────────────────────────────────────────────
        kctx = KernelContext(input=raw, caller=caller, user_id=user_id)
        try:
            for mw in self._mw:
                kctx = await mw(kctx) or kctx
                if kctx.blocked:
                    return CommandResult.fail(
                        "(blocked)", kctx.block_reason, "MIDDLEWARE_BLOCKED"
                    )
        except Exception as exc:
            log.exception("middleware raised: %s", exc)
            return CommandResult.fail("(middleware)", str(exc), "MIDDLEWARE_ERROR")

        # ── Parse ─────────────────────────────────────────────────────────────
        try:
            command, args, flags = _parse(kctx.input)
        except Exception as exc:
            return CommandResult.fail("(parse)", str(exc), "PARSE_ERROR")

        if not command:
            return CommandResult.fail("(empty)", "No command provided.",
                                      "EMPTY_COMMAND",
                                      suggestions=["Run 'help' to see available commands."])

        meta = self.registry.lookup(command)
        if meta is None:
            return CommandResult.unknown(command, self.registry.names())

        # ── Build CommandContext ───────────────────────────────────────────────
        from pathlib import Path
        ws_raw = flags.get("workspace") or flags.get("w") or (args[0] if args else "")
        workspace: Optional[Path] = None
        if ws_raw:
            p = Path(ws_raw).expanduser().resolve()
            workspace = p if p.exists() else Path(ws_raw)

        ctx = CommandContext(
            command      = command,
            args         = args,
            flags        = flags,
            raw_input    = raw,
            workspace    = workspace,
            project_id   = flags.get("project", flags.get("p", "")),
            caller       = caller,
            user_id      = user_id,
            runtime_state= {"kernel": self},
        )

        # ── Run through CommandAgent (isolated lifecycle) ──────────────────────
        agent  = CommandAgent(meta, ctx, timeout_s=float(flags.get("timeout", "300")))
        astate = await agent.run()

        result = agent.result or CommandResult.fail(
            command, astate.error or "Agent produced no result", "AGENT_NO_RESULT"
        )
        result.command    = command
        result.duration_ms = (astate.duration_s or 0) * 1000
        return result

    # ── Introspection ─────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "booted"      : self._booted,
            "uptime_s"    : self.state.uptime_s(),
            "commands"    : len(self.registry.names()),
            "modifications": len(self.state.modifications),
            "hot_reloads" : len(self.state.hot_reloads),
            "boot_ms"     : self.state.get("boot_ms"),
        }


# ── Kernel-native commands ─────────────────────────────────────────────────────

def _register_kernel_commands(registry: CommandRegistry, kernel: AIKernel) -> None:
    """Register commands that need direct access to the kernel."""

    # ── status ────────────────────────────────────────────────────────────────
    async def _status(ctx: CommandContext) -> CommandResult:
        import os
        import sys
        s = kernel.status()
        state_dict = kernel.state.to_dict()
        lines = [
            "── AI Kernel Status ───────────────────────────────────",
            f"  Uptime         : {s['uptime_s']}s",
            f"  Commands       : {s['commands']}",
            f"  Modifications  : {s['modifications']}",
            f"  Hot reloads    : {s['hot_reloads']}",
            f"  Boot time      : {s['boot_ms']}ms",
            f"  Python         : {sys.version.split()[0]}",
            f"  PID            : {os.getpid()}",
            "────────────────────────────────────────────────────────",
        ]
        return CommandResult.ok("status", output="\n".join(lines),
                                data={**s, "state": state_dict})

    # ── reload ────────────────────────────────────────────────────────────────
    async def _reload(ctx: CommandContext) -> CommandResult:
        target = ctx.first_arg()
        if not target:
            return CommandResult.fail("reload",
                                      "Usage: reload <plugin-file-or-module>",
                                      "MISSING_ARGS")
        try:
            result = kernel.reloader.reload_plugin(target)
            return CommandResult.ok("reload",
                                    output=f"✓ Reloaded {target}  +{result['added']}  -{result['removed']}",
                                    data=result)
        except Exception as exc:
            return CommandResult.fail("reload", str(exc), "RELOAD_FAILED")

    # ── patch ──────────────────────────────────────────────────────────────────
    async def _patch(ctx: CommandContext) -> CommandResult:
        file    = ctx.flag("file", ctx.flag("f"))
        find    = ctx.flag("find")
        replace = ctx.flag("replace", ctx.flag("with", ""))
        desc    = ctx.flag("description", ctx.flag("d", ""))
        if not file or not find:
            return CommandResult.fail("patch",
                                      "Usage: patch --file=<path> --find=<text> --replace=<text>",
                                      "MISSING_ARGS")
        try:
            result = kernel.modifier.patch(file, find=find, replace=replace, description=desc)
            return CommandResult.ok("patch",
                                    output=(f"✓ Patched {file}: "
                                            f"{result['occurrences']} occurrence(s) replaced"),
                                    data=result)
        except Exception as exc:
            return CommandResult.fail("patch", str(exc), "PATCH_FAILED")

    # ── rollback ──────────────────────────────────────────────────────────────
    async def _rollback(ctx: CommandContext) -> CommandResult:
        raw_idx = ctx.first_arg() or ctx.flag("index", ctx.flag("i", ""))
        if not raw_idx:
            mods = kernel.state.modifications
            if not mods:
                return CommandResult.ok("rollback", output="No modifications to roll back.")
            lines = ["Recent modifications (newest first):"]
            for i, m in enumerate(reversed(mods)):
                lines.append(f"  [{len(mods)-1-i}] {m.action:<10} {m.file}  ({'rolled back' if m.rolled_back else 'active'})")
            return CommandResult.ok("rollback", output="\n".join(lines),
                                    data={"modifications": [m.to_dict() for m in mods]})
        try:
            idx = int(raw_idx)
            result = kernel.modifier.rollback(idx)
            return CommandResult.ok("rollback",
                                    output=f"✓ Rolled back modification {idx}: {result['file']}",
                                    data=result)
        except (ValueError, TypeError):
            return CommandResult.fail("rollback", f"Invalid index: {raw_idx}", "INVALID_INDEX")
        except Exception as exc:
            return CommandResult.fail("rollback", str(exc), "ROLLBACK_FAILED")

    # ── diff ──────────────────────────────────────────────────────────────────
    async def _diff(ctx: CommandContext) -> CommandResult:
        file = ctx.flag("file", ctx.flag("f", ctx.first_arg()))
        if not file:
            return CommandResult.fail("diff", "Usage: diff --file=<path>", "MISSING_ARGS")
        try:
            result = kernel.modifier.diff(file)
            status = "changed" if result.get("changed") else "unchanged"
            return CommandResult.ok("diff",
                                    output=f"{file}: {status}  (hash: {result.get('current_hash')})",
                                    data=result)
        except Exception as exc:
            return CommandResult.fail("diff", str(exc), "DIFF_FAILED")

    # ── create ─────────────────────────────────────────────────────────────────
    async def _create(ctx: CommandContext) -> CommandResult:
        file    = ctx.flag("file", ctx.flag("f", ctx.first_arg()))
        content = ctx.flag("content", ctx.flag("c", ""))
        template= ctx.flag("template", ctx.flag("t", ""))
        desc    = ctx.flag("description", "")

        if not file:
            return CommandResult.fail("create",
                                      "Usage: create --file=<path> [--content=<text>] [--template=plugin|command]",
                                      "MISSING_ARGS")
        if template == "plugin":
            content = _plugin_template(file)
        elif template == "command":
            content = _command_template(file)

        try:
            result = kernel.modifier.create(file, content=content, description=desc)
            return CommandResult.ok("create",
                                    output=f"✓ Created {file}",
                                    data=result)
        except Exception as exc:
            return CommandResult.fail("create", str(exc), "CREATE_FAILED")

    # ── agents list ───────────────────────────────────────────────────────────
    async def _agents(ctx: CommandContext) -> CommandResult:
        cmds = kernel.registry.all()
        lines = ["── Registered Commands (Agent Model) ──────────────────"]
        for m in sorted(cmds, key=lambda x: x.name):
            lines.append(f"  [agent:{m.name:<14}]  {m.description}")
        lines.append(f"\n  Total: {len(cmds)} command agents")
        return CommandResult.ok("agents", output="\n".join(lines),
                                data={"count": len(cmds),
                                      "names": [m.name for m in cmds]})

    # ── Register all kernel-native commands ───────────────────────────────────
    for name, handler, desc, aliases, usage, group in [
        ("status",   _status,   "Show kernel status and system health",
         ["os", "sysinfo", "info"],    "status",                  "kernel"),
        ("reload",   _reload,   "Hot-reload a plugin file without restart",
         ["hot-reload"],               "reload <plugin-file>",    "kernel"),
        ("patch",    _patch,    "Patch a file: find-and-replace a string",
         [],                           "patch --file=F --find=X --replace=Y", "kernel"),
        ("rollback", _rollback, "Roll back a modification to its previous state",
         ["undo"],                     "rollback [index]",        "kernel"),
        ("diff",     _diff,     "Show whether a file has been modified vs its backup",
         [],                           "diff --file=<path>",      "kernel"),
        ("create",   _create,   "Create a new file (plugin, command, or custom)",
         ["new", "touch"],             "create --file=F [--template=plugin|command]", "kernel"),
        ("agents",   _agents,   "List all command agents",
         ["agent-ls", "agent-list"],   "agents",                  "kernel"),
    ]:
        registry.register(
            name, handler,
            description=desc, aliases=aliases,
            group=group, source="kernel", usage=usage,
        )


# ── File templates ────────────────────────────────────────────────────────────

def _plugin_template(file: str) -> str:
    name = file.rstrip(".py").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return f'''\
"""
{name} plugin — auto-loaded from the plugins directory.
"""
from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def {name}_handler(ctx: CommandContext) -> CommandResult:
    arg = ctx.first_arg("world")
    return CommandResult.ok("{name}", output=f"Hello from {name}: {{arg}}")


def register(registry) -> None:
    registry.register(
        "{name}",
        {name}_handler,
        description="{name} — auto-generated plugin",
        group="plugin",
        source="plugin",
        usage="{name} [arg]",
    )
'''


def _command_template(file: str) -> str:
    name = file.rstrip(".py").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return f'''\
"""
{name} — builtin command module.
"""
from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def {name}_handler(ctx: CommandContext) -> CommandResult:
    return CommandResult.ok("{name}", output="Command {name} executed.")


def register(registry) -> None:
    registry.register(
        "{name}",
        {name}_handler,
        description="{name} — auto-generated command",
        group="general",
        usage="{name} [args]",
    )
'''
