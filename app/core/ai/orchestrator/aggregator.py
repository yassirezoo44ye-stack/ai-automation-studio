"""
ResultAggregator — merges per-task results into a unified OrchestratorResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .planner import ExecutionPlan


@dataclass
class OrchestratorResult:
    request_id:   str
    content:      str
    tasks:        list[dict[str, Any]]
    total_cost:   float
    total_tokens: int
    success:      bool
    errors:       list[str]          = field(default_factory=list)
    metadata:     dict[str, Any]     = field(default_factory=dict)


class ResultAggregator:
    """
    Combines individual task results into a final OrchestratorResult.

    Strategy:
    - Content: join task contents in plan-order, separated by headings.
    - Costs/tokens: sum across all tasks.
    - Success: True if no task has success=False, or only non-critical tasks failed.
    """

    def aggregate(
        self,
        plan: ExecutionPlan,
        task_results: dict[str, dict[str, Any]],
    ) -> OrchestratorResult:
        ordered = plan.tasks
        content_parts: list[str] = []
        errors: list[str] = []
        total_cost   = 0.0
        total_tokens = 0

        for task in ordered:
            res = task_results.get(task.id, {})
            if res.get("success") is False:
                errors.append(f"Task {task.id} ({task.task_type}): {res.get('error', 'unknown error')}")
                continue
            text = res.get("content", "")
            if text:
                header = f"### {task.task_type.title()}: {task.description[:60]}"
                content_parts.append(f"{header}\n{text}")
            total_cost   += res.get("cost_usd", 0.0)
            total_tokens += res.get("output_tokens", 0)

        combined = "\n\n".join(content_parts) if content_parts else "(no output)"
        success  = len(errors) < len(ordered)   # partial success counts

        return OrchestratorResult(
            request_id=plan.request_id,
            content=combined,
            tasks=[
                {
                    "id":       t.id,
                    "type":     t.task_type,
                    "desc":     t.description[:100],
                    "result":   task_results.get(t.id, {}),
                }
                for t in ordered
            ],
            total_cost=total_cost,
            total_tokens=total_tokens,
            success=success,
            errors=errors,
            metadata={"plan": plan.diagnostics},
        )
