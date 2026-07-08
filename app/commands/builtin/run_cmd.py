"""
run — execute a project through the UnifiedExecutionEngine.

Usage:
    run <workspace>
    run --workspace=./my-project --project=proj-id

Streams TypedEvent SSE from the engine.  In CLI mode, prints lines as they
arrive.  In API mode, the REST layer handles streaming separately.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def run_handler(ctx: CommandContext) -> CommandResult:
    ws = ctx.resolved_workspace()
    if ws is None:
        return CommandResult.fail(
            "run",
            "No workspace specified. Usage: run <path>",
            "MISSING_WORKSPACE",
            suggestions=["Example: run ./my-project", "Example: run --workspace=./my-project"],
        )
    if not ws.exists():
        return CommandResult.fail(
            "run",
            f"Workspace does not exist: {ws}",
            "WORKSPACE_NOT_FOUND",
        )

    from app.execution.platform import UnifiedExecutionEngine

    engine     = UnifiedExecutionEngine()
    project_id = ctx.project_id or ws.name
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
        usage="run <workspace> [--project=<id>]",
    )
