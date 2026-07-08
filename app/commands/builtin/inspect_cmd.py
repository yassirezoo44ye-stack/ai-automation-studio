"""
inspect — Runtime Inspector (Phase 13 of the Execution Platform).

Usage:
    inspect                       — show runtime status overview
    inspect cache                 — cache statistics
    inspect runtimes              — list registered runtimes
    inspect commands              — list registered commands
    inspect execution <id>        — report for a specific execution
    inspect workspace <path>      — analyse a workspace (detect runtime)
"""
from __future__ import annotations

from pathlib import Path

from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def inspect_handler(ctx: CommandContext) -> CommandResult:
    sub = ctx.first_arg("overview")
    dispatch = {
        "overview"  : _inspect_overview,
        "cache"     : _inspect_cache,
        "runtimes"  : _inspect_runtimes,
        "commands"  : _inspect_commands,
        "execution" : _inspect_execution,
        "workspace" : _inspect_workspace,
    }
    fn = dispatch.get(sub)
    if fn is None:
        return CommandResult.fail(
            "inspect",
            f"Unknown inspect target: '{sub}'",
            "UNKNOWN_TARGET",
            suggestions=[f"Available: {', '.join(dispatch)}"],
        )
    return await fn(ctx)


async def _inspect_overview(ctx: CommandContext) -> CommandResult:
    from app.execution.platform import get_cache, get_registry as get_rt_registry
    from app.commands import get_registry as get_cmd_registry

    cache     = get_cache()
    runtimes  = get_rt_registry().all()
    commands  = get_cmd_registry().all()

    lines = [
        "── Runtime Inspector ──────────────────────────────────",
        f"  Registered runtimes : {len(runtimes)}  ({', '.join(r.name for r in runtimes)})",
        f"  Registered commands : {len(commands)}",
        f"  Build cache entries : {cache.stats()['entries']}",
        f"  Build cache size    : {cache.stats()['total_size_mb']} MB",
        "────────────────────────────────────────────────────────",
    ]
    return CommandResult.ok("inspect", output="\n".join(lines),
                            data={"runtimes": len(runtimes), "commands": len(commands),
                                  "cache": cache.stats()})


async def _inspect_cache(ctx: CommandContext) -> CommandResult:
    from app.execution.platform import get_cache
    stats = get_cache().stats()
    lines = [
        "── Build Cache ─────────────────────────────────────────",
        f"  Entries   : {stats['entries']}",
        f"  Total size: {stats['total_size_mb']} MB",
        f"  Root      : {stats['root']}",
    ]
    return CommandResult.ok("inspect", output="\n".join(lines), data=stats)


async def _inspect_runtimes(ctx: CommandContext) -> CommandResult:
    from app.execution.platform import get_registry
    rts = get_registry().all()
    lines = ["── Registered Runtimes ─────────────────────────────────"]
    for rt in rts:
        lines.append(f"  {rt.priority:3d}  {rt.name:<16} {rt.__class__.__module__}")
    return CommandResult.ok("inspect", output="\n".join(lines),
                            data={"runtimes": [{"name": r.name, "priority": r.priority}
                                               for r in rts]})


async def _inspect_commands(ctx: CommandContext) -> CommandResult:
    from app.commands import get_registry
    cmds = get_registry().all()
    lines = ["── Registered Commands ─────────────────────────────────"]
    for meta in sorted(cmds, key=lambda m: (m.group, m.name)):
        aliases = f"  [{', '.join(meta.aliases)}]" if meta.aliases else ""
        lines.append(f"  {meta.name:<16} {meta.description}{aliases}  ({meta.source})")
    return CommandResult.ok("inspect", output="\n".join(lines),
                            data={"commands": [m.name for m in cmds]})


async def _inspect_execution(ctx: CommandContext) -> CommandResult:
    exec_id = ctx.args[1] if len(ctx.args) > 1 else ctx.flag("execution", ctx.flag("e"))
    if not exec_id:
        return CommandResult.fail("inspect", "Usage: inspect execution <execution-id>",
                                  "MISSING_ARGS")
    from app.execution.platform.artifacts import ArtifactSystem
    arts = ArtifactSystem.load(exec_id)
    lines = [
        f"── Execution: {exec_id} ─────────────────────────────────",
        f"  Artifacts : {arts.count()}",
        f"  Total size: {arts.total_size_bytes() // 1024} KB",
    ]
    for a in arts.all():
        lines.append(f"  [{a.kind}] {a.name}  ({a.size_bytes} bytes)")
    return CommandResult.ok("inspect", output="\n".join(lines),
                            data={"execution_id": exec_id,
                                  "artifacts": [a.to_dict() for a in arts.all()]})


async def _inspect_workspace(ctx: CommandContext) -> CommandResult:
    ws_str = ctx.args[1] if len(ctx.args) > 1 else ctx.flag("workspace", ctx.flag("w"))
    if not ws_str:
        return CommandResult.fail("inspect", "Usage: inspect workspace <path>", "MISSING_ARGS")
    ws = Path(ws_str).expanduser().resolve()
    if not ws.exists():
        return CommandResult.fail("inspect", f"Workspace not found: {ws}", "NOT_FOUND")

    from app.execution.platform import get_registry
    registry = get_registry()
    rt = registry.select(ws)
    lines = [
        f"── Workspace: {ws} ─────────────────────────────────",
        f"  Detected runtime : {rt.name if rt else 'none'}",
        f"  package.json     : {(ws / 'package.json').exists()}",
        f"  requirements.txt : {(ws / 'requirements.txt').exists()}",
        f"  Dockerfile       : {(ws / 'Dockerfile').exists()}",
    ]
    for lf in ("pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb"):
        if (ws / lf).exists():
            lines.append(f"  Lockfile         : {lf}")
            break
    return CommandResult.ok("inspect", output="\n".join(lines),
                            data={"workspace": str(ws),
                                  "runtime": rt.name if rt else None})


def register(registry) -> None:
    registry.register(
        "inspect",
        inspect_handler,
        description="Inspect runtime state, cache, runtimes, or workspaces",
        aliases=["info", "status"],
        group="runtime",
        usage="inspect [overview|cache|runtimes|commands|execution <id>|workspace <path>]",
    )
