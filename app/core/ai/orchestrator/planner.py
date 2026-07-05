"""
TaskPlanner — decomposes a high-level request into an ordered task graph.

Each task carries: id, type, description, depends_on, preferred_agent,
estimated_tokens, estimated_cost_usd.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PlannedTask:
    id:               str
    task_type:        str                   # "research" | "code" | "review" | "design" | etc.
    description:      str
    depends_on:       list[str]             = field(default_factory=list)
    preferred_agent:  Optional[str]         = None
    estimated_tokens: int                   = 500
    estimated_cost:   float                 = 0.0
    metadata:         dict[str, Any]        = field(default_factory=dict)

    @classmethod
    def make(cls, task_type: str, description: str, **kw: Any) -> "PlannedTask":
        return cls(id=str(uuid.uuid4()), task_type=task_type, description=description, **kw)


@dataclass
class ExecutionPlan:
    request_id:       str
    tasks:            list[PlannedTask]
    total_estimated_tokens: int   = 0
    total_estimated_cost:   float = 0.0
    parallel_groups:  list[list[str]] = field(default_factory=list)   # task-id groups that can run in parallel
    diagnostics:      dict[str, Any]  = field(default_factory=dict)


class TaskPlanner:
    """
    Analyzes a request and produces an ExecutionPlan.

    Strategy:
    - Single short requests → single task, no sub-decomposition.
    - Requests that mention multiple distinct goals → one task per goal.
    - Requests with "and then" / "after" / "first ... then" → sequential dependency chain.
    - Everything else → single task with type inferred from keywords.
    """

    _AGENT_HINTS: dict[str, str] = {
        "architect": "architect",
        "design":    "design",
        "frontend":  "frontend",
        "backend":   "backend",
        "test":      "qa",
        "qa":        "qa",
        "document":  "documentation",
        "devops":    "devops",
        "research":  "research",
        "deploy":    "devops",
        "style":     "design",
        "api":       "backend",
        "database":  "backend",
        "db":        "backend",
    }

    def plan(self, request_id: str, prompt: str, context: dict[str, Any]) -> ExecutionPlan:
        tasks = self._decompose(prompt, context)
        groups = self._build_parallel_groups(tasks)
        total_tokens = sum(t.estimated_tokens for t in tasks)
        total_cost   = sum(t.estimated_cost   for t in tasks)
        return ExecutionPlan(
            request_id=request_id,
            tasks=tasks,
            total_estimated_tokens=total_tokens,
            total_estimated_cost=total_cost,
            parallel_groups=groups,
            diagnostics={"decomposition_strategy": "keyword", "task_count": len(tasks)},
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _decompose(self, prompt: str, context: dict[str, Any]) -> list[PlannedTask]:
        lower = prompt.lower()

        # Sequential chain: "first … then …"
        if any(kw in lower for kw in ("first", "then", "after that", "next step")):
            return self._sequential_chain(prompt)

        # Multi-goal: sentences with multiple verbs / "and"
        sentences = [s.strip() for s in prompt.replace("\n", ".").split(".") if s.strip()]
        if len(sentences) > 2:
            tasks = []
            for sent in sentences[:6]:   # cap at 6 tasks
                tasks.append(self._task_from_sentence(sent))
            return tasks

        # Single task
        return [self._task_from_sentence(prompt)]

    def _task_from_sentence(self, sentence: str) -> PlannedTask:
        lower = sentence.lower()
        task_type = "general"
        for kw, agent in self._AGENT_HINTS.items():
            if kw in lower:
                task_type = kw
                break

        agent = self._AGENT_HINTS.get(task_type)
        # Very rough token estimate: 1 token ≈ 4 chars of output; input is prompt
        est_tokens = max(200, len(sentence) * 3)
        est_cost   = est_tokens * 3e-6   # rough mid-tier pricing

        return PlannedTask.make(
            task_type=task_type,
            description=sentence[:300],
            preferred_agent=agent,
            estimated_tokens=est_tokens,
            estimated_cost=est_cost,
        )

    def _sequential_chain(self, prompt: str) -> list[PlannedTask]:
        """Split on transition words, chain dependencies."""
        import re
        parts = re.split(r"\b(then|after that|next step|afterward)\b", prompt, flags=re.I)
        parts = [p.strip() for p in parts if p.strip() and len(p) > 5]
        tasks: list[PlannedTask] = []
        prev_id: Optional[str] = None
        for part in parts[:6]:
            t = self._task_from_sentence(part)
            if prev_id:
                t.depends_on = [prev_id]
            tasks.append(t)
            prev_id = t.id
        return tasks or [self._task_from_sentence(prompt)]

    def _build_parallel_groups(self, tasks: list[PlannedTask]) -> list[list[str]]:
        """Group tasks that have no unresolved dependencies together."""
        resolved: set[str] = set()
        groups: list[list[str]] = []
        remaining = list(tasks)
        while remaining:
            ready = [t for t in remaining if all(d in resolved for d in t.depends_on)]
            if not ready:
                break
            groups.append([t.id for t in ready])
            for t in ready:
                resolved.add(t.id)
            remaining = [t for t in remaining if t.id not in resolved]
        return groups
