"""
ExecutionCoordinator — connects scheduler tasks to the actual agent/inference pipeline.

Resolves which agent or inference path executes each task, emits lifecycle
events, and records costs.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional, TYPE_CHECKING

from ..events.bus import EventBus
from ..events.events import (
    AgentStarted, AgentCompleted,
    TaskStarted, TaskCompleted, TaskFailed,
    CostRecorded,
)
from .scheduler import ScheduledTask

if TYPE_CHECKING:
    from ..platform import AIPlatform


class ExecutionCoordinator:
    """
    Given a ScheduledTask, runs it through the correct pipeline and returns a result dict.

    Priority:
    1. If task has a preferred_agent, try the built-in agent registry.
    2. Fall back to AIPlatform.complete() with task description as prompt.
    """

    def __init__(
        self,
        platform: "AIPlatform",
        bus: EventBus,
        request_id: str,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> None:
        self._platform  = platform
        self._bus       = bus
        self._request_id = request_id
        self._user_id   = user_id
        self._org_id    = org_id

    async def run_task(self, task: ScheduledTask) -> dict[str, Any]:
        t0 = time.perf_counter()
        tid = task.planned.id

        await self._bus.emit(TaskStarted(
            task_id=tid,
            task_type=task.planned.task_type,
            agent_id=task.agent_name,
            request_id=self._request_id,
        ))

        try:
            result = await self._dispatch(task)
            duration_ms = (time.perf_counter() - t0) * 1000
            cost = result.get("cost_usd", 0.0)

            await self._bus.emit(TaskCompleted(
                task_id=tid,
                request_id=self._request_id,
                duration_ms=duration_ms,
                cost_usd=cost,
            ))
            if cost > 0:
                await self._bus.emit(CostRecorded(
                    amount_usd=cost,
                    provider_id=result.get("provider_id", ""),
                    model=result.get("model", ""),
                    agent_name=task.agent_name,
                ))
            result.update({"success": True, "duration_ms": duration_ms, "task_id": tid})
            return result

        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            await self._bus.emit(TaskFailed(
                task_id=tid,
                request_id=self._request_id,
                error=str(exc),
                attempt=task.attempt,
            ))
            raise

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _dispatch(self, task: ScheduledTask) -> dict[str, Any]:
        agent_name = task.agent_name
        t0 = time.perf_counter()

        if agent_name:
            # Try built-in agent first
            agent = self._platform.get_agent(agent_name)
            if agent is not None:
                await self._bus.emit(AgentStarted(
                    agent_name=agent_name,
                    task_id=task.planned.id,
                ))
                run_result = await agent.run(task.planned.description, self._user_id)
                duration_ms = (time.perf_counter() - t0) * 1000
                await self._bus.emit(AgentCompleted(
                    agent_name=agent_name,
                    task_id=task.planned.id,
                    duration_ms=duration_ms,
                    success=run_result.success,
                ))
                return {
                    "content":     run_result.content,
                    "tool_calls":  [tc.__dict__ for tc in run_result.tool_calls],
                    "rounds":      run_result.rounds,
                    "cost_usd":    0.0,
                    "provider_id": "",
                    "model":       "",
                }

        # Fallback: direct inference
        from ..inference.engine import InferenceEngine
        from app.ai.models import CompletionRequest, Message

        req = CompletionRequest(
            messages=[Message(role="user", content=task.planned.description)],
            conversation_id=None,
        )
        engine = self._platform.inference_engine
        resp = await engine.complete(req, user_id=self._user_id, org_id=self._org_id)
        return {
            "content":     resp.content,
            "tool_calls":  [],
            "rounds":      1,
            "cost_usd":    resp.cost_usd if hasattr(resp, "cost_usd") else 0.0,
            "provider_id": resp.provider_id if hasattr(resp, "provider_id") else "",
            "model":       resp.model if hasattr(resp, "model") else "",
        }
