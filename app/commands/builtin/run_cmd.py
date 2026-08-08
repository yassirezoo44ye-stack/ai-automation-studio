"""
run — execute a project through the UnifiedExecutionEngine.

Usage:
    run --project=<id>

Streams TypedEvent SSE from the engine.  In CLI mode, prints lines as they
arrive.  In API mode, the REST layer handles streaming separately.

SECURITY FIX: this used to derive the workspace from
ctx.resolved_workspace() — a raw client-controlled path (--workspace flag
or first positional arg via POST /api/commands/execute's `args`/`flags`
body fields) — and hand it to UnifiedExecutionEngine, which copies it into
a sandbox and runs install/build/launch against it: an arbitrary-file-read
+ arbitrary-code-execution primitive gated by nothing but a valid session,
mirroring runtime_api.py's POST /api/runtime/execute bug. The workspace is
now always re-derived from a verified project_id (ctx.user_id +
resolve_project_id), never a client-supplied path. ctx.resolved_workspace()
is no longer called here.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException

from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def run_handler(ctx: CommandContext) -> CommandResult:
    # ctx.user_id is only trustworthy here once commands_api.py resolves
    # it from the verified auth token rather than a client-supplied field
    # (see commands_api.py's fix) — this handler must not derive identity
    # or workspace from anything else client-controlled.
    if not ctx.user_id:
        return CommandResult.fail(
            "run", "Authentication required.", "UNAUTHENTICATED",
        )
    if not ctx.project_id:
        return CommandResult.fail(
            "run",
            "No project specified. Usage: run --project=<id>",
            "MISSING_PROJECT",
            suggestions=["Example: run --project=demo", "Example: run --project=<your-project-id>"],
        )

    try:
        uid = uuid.UUID(ctx.user_id)
    except ValueError:
        return CommandResult.fail("run", "Invalid caller identity.", "BAD_USER_ID")

    from app.core.db import get_pool
    from app.core.filesystem import workspace as project_workspace
    from app.core.helpers import resolve_project_id

    async with get_pool().acquire() as conn:
        try:
            pid = await resolve_project_id(conn, ctx.project_id, uid)
        except HTTPException as exc:
            return CommandResult.fail("run", str(exc.detail), "PROJECT_NOT_FOUND")

    ws = project_workspace(str(pid))

    from app.execution.platform import UnifiedExecutionEngine

    engine     = UnifiedExecutionEngine()
    project_id = str(pid)
    output_lines: list[str] = []
    report: dict = {}

    async for event in engine.run(ws, project_id=project_id):
        d = event.to_sse_dict()
        t = d.get("type", "")
        if t == "log":
            line = d.get("line", "")
            output_lines.append(line)
        elif t == "server_ready":
            output_lines.append(f"✓ Server ready: {d.get('preview_url', '')}")
        elif t == "report":
            report = d.get("report", {})
        elif t == "execution_failed":
            output_lines.append(f"✗ {d.get('message', 'execution failed')}")

    success = report.get("success", False)
    output  = "\n".join(output_lines)

    if success:
        return CommandResult.ok("run", output=output, data=report)
    return CommandResult.fail(
        "run",
        report.get("error_message", "Execution failed"),
        error_code=report.get("error_code", "EXEC_FAILED"),
        suggestions=report.get("error_fix", []),
    )


def register(registry) -> None:
    registry.register(
        "run",
        run_handler,
        description="Run a project through the execution engine",
        aliases=["execute", "start"],
        group="execution",
        usage="run --project=<id>",
    )
