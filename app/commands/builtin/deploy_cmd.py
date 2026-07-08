"""
deploy — scaffold for deployment workflows.

Currently emits a structured deployment plan.  Actual deployment drivers
can be registered as plugins (deploy-render.py, deploy-fly.py, etc.)

Usage:
    deploy <workspace> --target=render
    deploy <workspace> --target=docker
    deploy <workspace> --target=zip
"""
from __future__ import annotations

from pathlib import Path

from app.commands.context import CommandContext
from app.commands.result import CommandResult

_TARGETS = {
    "zip"   : "Build ZIP archive and download",
    "docker": "Build Docker image locally",
    "render": "Deploy to Render.com (requires RENDER_API_KEY env var)",
    "fly"   : "Deploy to Fly.io (requires fly CLI)",
}


async def deploy_handler(ctx: CommandContext) -> CommandResult:
    ws = ctx.resolved_workspace()
    if ws is None or not ws.exists():
        return CommandResult.fail(
            "deploy",
            f"Workspace not found: {ctx.first_arg()}",
            "WORKSPACE_NOT_FOUND",
        )

    target = ctx.flag("target", ctx.flag("t", "zip"))
    if target not in _TARGETS:
        return CommandResult.fail(
            "deploy",
            f"Unknown deploy target: '{target}'",
            "UNKNOWN_TARGET",
            suggestions=[f"Available targets: {', '.join(_TARGETS)}"],
        )

    if target == "zip":
        # Reuse the build command
        from app.commands.builtin.build_cmd import build_handler
        return await build_handler(ctx)

    # All other targets are scaffolded — emit a plan
    lines = [
        f"── Deploy Plan: {ws.name} → {target} ─────────────────────",
        f"  Target      : {target}",
        f"  Description : {_TARGETS[target]}",
        f"  Workspace   : {ws}",
        "",
        "  This target is a scaffold.  Install the corresponding deploy",
        f"  plugin (e.g. plugins/deploy-{target}.py) to enable it.",
    ]
    return CommandResult.ok(
        "deploy",
        output="\n".join(lines),
        data={"workspace": str(ws), "target": target, "status": "scaffold"},
    )


def register(registry) -> None:
    registry.register(
        "deploy",
        deploy_handler,
        description="Deploy a project to a target environment",
        aliases=["ship", "publish"],
        group="execution",
        usage="deploy <workspace> [--target=zip|docker|render|fly]",
    )
