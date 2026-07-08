"""
CommandAgent — wraps a CommandContext invocation as an isolated Agent.

Every command executed through the Kernel runs inside a CommandAgent.
This gives each command:
  - Its own AgentState (isolated from other commands)
  - Full lifecycle (initialize / execute / finalize)
  - Event emission during execution
  - Timeout enforcement

The Kernel's AgentScheduler can run multiple CommandAgents concurrently.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.kernel.agents.base import AgentState, BaseAgent

if TYPE_CHECKING:
    from app.commands.context import CommandContext
    from app.commands.registry import CommandMeta
    from app.commands.result import CommandResult


class CommandAgent(BaseAgent):
    """
    Executes a single command invocation as an isolated agent.

    Created by AIKernel for every execute() call.
    """

    def __init__(
        self,
        meta: "CommandMeta",
        ctx: "CommandContext",
        timeout_s: float = 300.0,
    ) -> None:
        self.meta      = meta
        self.ctx       = ctx
        self.timeout_s = timeout_s
        self.result: "CommandResult | None" = None
        self.name = f"agent:{meta.name}"

    async def execute(self, state: AgentState) -> None:
        state.emit(f"▶ {self.meta.name}  caller={self.ctx.caller}")
        try:
            self.result = await asyncio.wait_for(
                self.meta.handler(self.ctx),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            from app.commands.result import CommandResult
            self.result = CommandResult.fail(
                self.meta.name,
                f"Command timed out after {self.timeout_s:.0f}s",
                "AGENT_TIMEOUT",
            )
            state.error = self.result.error
        except Exception as exc:
            from app.commands.result import CommandResult
            self.result = CommandResult.fail(
                self.meta.name,
                f"Agent execution error: {exc}",
                "AGENT_EXCEPTION",
            )
            state.error = str(exc)
            raise

        if self.result:
            state.data["result"]  = self.result.to_dict()
            state.data["success"] = self.result.success
            state.emit(
                f"{'✓' if self.result.success else '✗'} "
                f"{self.meta.name} in {self.result.duration_ms:.0f}ms"
            )

    async def finalize(self, state: AgentState) -> None:
        # Agents are fire-and-forget — no persistent resources to release
        pass
