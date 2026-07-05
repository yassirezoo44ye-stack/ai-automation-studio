"""
TaskScheduler — assigns agents to planned tasks and orders execution.

Respects parallel groups, applies retry policy, and respects policy limits.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from .planner import ExecutionPlan, PlannedTask


@dataclass
class ScheduledTask:
    planned:       PlannedTask
    agent_name:    Optional[str]
    max_retries:   int   = 2
    timeout_s:     float = 60.0
    attempt:       int   = 0
    started_at:    float = field(default_factory=time.time)


TaskRunner = Callable[[ScheduledTask], Coroutine[Any, Any, dict[str, Any]]]


class TaskScheduler:
    """
    Executes a plan's parallel groups in order, running each group concurrently.

    The caller supplies a `runner` coroutine that accepts a ScheduledTask and
    returns a result dict.  The scheduler handles concurrency, retries, and
    timeouts at the group level.
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._max_concurrent = max_concurrent

    async def run(
        self,
        plan: ExecutionPlan,
        runner: TaskRunner,
    ) -> dict[str, dict[str, Any]]:
        """
        Returns a mapping of task_id → result dict.
        Raises RuntimeError only if a non-retriable task fails after all retries.
        """
        task_map = {t.id: t for t in plan.tasks}
        results: dict[str, dict[str, Any]] = {}

        for group in plan.parallel_groups:
            group_tasks = [task_map[tid] for tid in group if tid in task_map]
            scheduled = [
                ScheduledTask(
                    planned=t,
                    agent_name=t.preferred_agent,
                )
                for t in group_tasks
            ]

            sem = asyncio.Semaphore(self._max_concurrent)
            group_results = await asyncio.gather(
                *[self._run_with_retry(st, runner, sem) for st in scheduled],
                return_exceptions=True,
            )
            for st, res in zip(scheduled, group_results):
                if isinstance(res, Exception):
                    results[st.planned.id] = {"error": str(res), "success": False}
                else:
                    results[st.planned.id] = res   # type: ignore[assignment]

        return results

    async def _run_with_retry(
        self,
        task: ScheduledTask,
        runner: TaskRunner,
        sem: asyncio.Semaphore,
    ) -> dict[str, Any]:
        async with sem:
            last_exc: Optional[Exception] = None
            for attempt in range(task.max_retries + 1):
                task.attempt = attempt
                try:
                    return await asyncio.wait_for(
                        runner(task),
                        timeout=task.timeout_s,
                    )
                except asyncio.TimeoutError:
                    last_exc = TimeoutError(f"Task {task.planned.id} timed out after {task.timeout_s}s")
                except Exception as exc:
                    last_exc = exc
                if attempt < task.max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))   # exponential-ish backoff
            raise last_exc or RuntimeError("Unknown scheduler error")
