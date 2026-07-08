"""Run agent — executes a project using the UnifiedExecutionEngine."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.agents.base import AgentContext, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)


class RunAgent(EvolvableAgent):
    name        = "run"
    description = "Execute a project (auto-detects Node, Python, Docker)"
    group       = "execution"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        workspace = ctx.args.strip() or ctx.workspace
        if not workspace:
            return AgentResult.fail(
                self.name,
                "No workspace specified. Usage: run <path>",
            )

        ws = Path(workspace).expanduser().resolve()
        if not ws.exists():
            return AgentResult.fail(self.name, f"Workspace not found: {workspace}")

        project_id = ctx.project_id or ws.name

        try:
            from app.execution.platform.engine import UnifiedExecutionEngine
            import uuid
            execution_id = str(uuid.uuid4())
            engine = UnifiedExecutionEngine()

            events: list[dict] = []
            async for event in engine.run(ws, project_id, execution_id):
                events.append(event)
                if event.get("type") == "error":
                    return AgentResult.fail(
                        self.name,
                        event.get("message", "execution error"),
                        data={"events": events[-10:], "workspace": str(ws)},
                    )

            return AgentResult.ok(
                self.name,
                f"Project executed successfully: {ws.name}",
                data={
                    "workspace"   : str(ws),
                    "execution_id": execution_id,
                    "event_count" : len(events),
                },
            )
        except Exception as exc:
            log.error("run agent error: %s", exc)
            return AgentResult.fail(self.name, str(exc),
                                    data={"workspace": str(workspace)})

    def performance_hint(self) -> dict:
        return {"complexity": "high", "io_bound": True, "timeout_s": 300}


agent = RunAgent()
