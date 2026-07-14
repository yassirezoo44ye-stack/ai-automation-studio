"""
BaseAgent — protocol for agent-based command execution.

In the agent model, every command is an independent Agent with:
  - Its own isolated state
  - A lifecycle: initialize → execute → finalize
  - The ability to emit events during execution
  - Optional timeout and resource limits

Agents run independently — one agent crashing never affects others.
The Kernel's AgentScheduler manages concurrent agent execution.

Agent = Command + Isolated State + Lifecycle
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
import time


@dataclass
class AgentState:
    """Per-agent mutable state, isolated from other agents."""
    agent_id  : str
    started_at: float = field(default_factory=time.time)
    ended_at  : Optional[float] = None
    status    : str = "idle"       # idle | running | done | failed | cancelled
    output    : list[str] = field(default_factory=list)
    error     : str = ""
    data      : dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> Optional[float]:
        if self.ended_at is None:
            return None
        return round(self.ended_at - self.started_at, 3)

    def emit(self, message: str) -> None:
        self.output.append(message)

    def to_dict(self) -> dict:
        return {
            "agent_id"  : self.agent_id,
            "started_at": round(self.started_at, 3),
            "ended_at"  : round(self.ended_at, 3) if self.ended_at else None,
            "duration_s": self.duration_s,
            "status"    : self.status,
            "output"    : self.output,
            "error"     : self.error,
            "data"      : self.data,
        }


class BaseAgent(ABC):
    """
    Abstract base for all kernel agents.

    Sub-class this to create agents that run inside the kernel:

        class MyAgent(BaseAgent):
            name = "my-agent"

            async def execute(self, state: AgentState) -> None:
                state.emit("Starting...")
                result = await do_work()
                state.data["result"] = result
                state.emit(f"Done: {result}")
    """

    name: str = "agent"

    async def initialize(self, state: AgentState) -> None:
        """Called before execute(). Override for setup."""
        pass

    @abstractmethod
    async def execute(self, state: AgentState) -> None:
        """Main agent work. Write output to state.emit()."""

    async def finalize(self, state: AgentState) -> None:
        """Called after execute(), even on failure. Override for cleanup."""
        pass

    async def run(self, agent_id: str | None = None) -> AgentState:
        """
        Full lifecycle: initialize → execute → finalize.
        Returns AgentState with all results.
        """
        import uuid
        aid   = agent_id or str(uuid.uuid4())[:8]
        state = AgentState(agent_id=aid, status="running")
        try:
            await self.initialize(state)
            await self.execute(state)
            state.status = "done"
        except Exception as exc:
            state.status = "failed"
            state.error  = str(exc)
        finally:
            state.ended_at = time.time()
            try:
                await self.finalize(state)
            except Exception:
                pass
        return state
