"""
PlanningEngine — production planning layer.

Wraps app.core.ai.orchestrator.planner.TaskPlanner and adds:

  1. Intent analysis       — classify the goal type
  2. Agent assignment      — map each task to the best available agent
  3. Complexity estimation — token/cost/time from agent.estimate_cost()
  4. Dependency graph      — topological sort, parallel group detection
  5. Permission validation — check agents have the permissions they need
  6. Risk scoring          — low/medium/high/critical
  7. Rollback plan         — set of inverse actions per task

The engine is the mandatory gate before any multi-step execution.
No task enters the execution engine without a completed plan.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Data types ────────────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


@dataclass
class PlanTask:
    id              : str
    description     : str
    task_type       : str
    agent_name      : Optional[str]    = None
    depends_on      : list[str]        = field(default_factory=list)
    estimated_tokens: int              = 0
    estimated_cost  : float            = 0.0
    estimated_ms    : float            = 200.0
    risk_level      : RiskLevel        = RiskLevel.LOW
    rollback_action : Optional[str]    = None
    metadata        : dict[str, Any]   = field(default_factory=dict)
    # Execution state (filled in by execution engine)
    status          : str              = "pending"   # pending|running|done|failed|skipped
    result          : Optional[dict]   = None

    def to_dict(self) -> dict:
        return {
            "id"              : self.id,
            "description"     : self.description,
            "task_type"       : self.task_type,
            "agent_name"      : self.agent_name,
            "depends_on"      : self.depends_on,
            "estimated_tokens": self.estimated_tokens,
            "estimated_cost"  : round(self.estimated_cost, 6),
            "estimated_ms"    : round(self.estimated_ms, 1),
            "risk_level"      : self.risk_level.value,
            "rollback_action" : self.rollback_action,
            "status"          : self.status,
            "metadata"        : self.metadata,
        }


@dataclass
class RichPlan:
    plan_id         : str
    goal            : str
    tasks           : list[PlanTask]
    parallel_groups : list[list[str]]         # groups of task IDs safe to parallelize
    total_tokens    : int
    total_cost_usd  : float
    total_ms        : float
    risk_level      : RiskLevel
    requires_approval: bool
    permission_errors: list[str]
    warnings        : list[str]
    diagnostics     : dict[str, Any]
    rollback_plan   : list[str]               # ordered list of rollback descriptions

    @property
    def is_safe(self) -> bool:
        return not self.permission_errors and self.risk_level != RiskLevel.CRITICAL

    def to_dict(self) -> dict:
        return {
            "plan_id"          : self.plan_id,
            "goal"             : self.goal,
            "tasks"            : [t.to_dict() for t in self.tasks],
            "parallel_groups"  : self.parallel_groups,
            "total_tokens"     : self.total_tokens,
            "total_cost_usd"   : round(self.total_cost_usd, 6),
            "total_ms"         : round(self.total_ms, 1),
            "risk_level"       : self.risk_level.value,
            "requires_approval": self.requires_approval,
            "permission_errors": self.permission_errors,
            "warnings"         : self.warnings,
            "rollback_plan"    : self.rollback_plan,
            "is_safe"          : self.is_safe,
            "diagnostics"      : self.diagnostics,
        }


# Keep a short alias for callers that only use ExecutionPlan
ExecutionPlan = RichPlan


# ── Agent assignment table ────────────────────────────────────────────────────

_TASK_AGENT_MAP: dict[str, str] = {
    "build"   : "build",
    "run"     : "run",
    "deploy"  : "deploy",
    "analyze" : "analyze",
    "modify"  : "modify",
    "evolve"  : "evolve",
    "plan"    : "plan",
    "status"  : "status",
    "help"    : "help",
    "generate": "modify",
    "test"    : "run",
    "code"    : "modify",
    "research": "analyze",
    "design"  : "analyze",
    "document": "analyze",
    "backend" : "build",
    "frontend": "build",
    "devops"  : "deploy",
    "qa"      : "run",
}

_HIGH_RISK_KEYWORDS = {"delete", "remove", "drop", "overwrite", "format",
                       "wipe", "truncate", "destroy", "purge", "kill"}
_CRITICAL_RISK_KEYWORDS = {"production", "prod", "live", "deploy to production"}
_APPROVAL_REQUIRED = {"deploy", "modify", "evolve", "generate"}


class PlanningEngine:
    """
    Full planning pipeline:
      analyze intent → decompose → assign agents → estimate cost →
      validate permissions → score risk → build rollback → return RichPlan
    """

    def __init__(self) -> None:
        # Import lazily to avoid circular imports at module load time
        self._base_planner = None

    def _get_base_planner(self):
        if self._base_planner is None:
            from app.core.ai.orchestrator.planner import TaskPlanner
            self._base_planner = TaskPlanner()
        return self._base_planner

    # ── Public API ────────────────────────────────────────────────────────────

    def plan(
        self,
        goal     : str,
        *,
        caller   : str = "system",
        agents   : Optional[dict] = None,   # name → EvolvableAgent
        context  : Optional[dict] = None,
    ) -> RichPlan:
        """
        Build a complete execution plan for `goal`.

        `agents` is the live agent registry — pass kernel._agents for full
        cost estimation and permission validation.
        """
        from app.core.observability.metrics import get_metrics
        get_metrics().counter("agentos_plans_total").inc()

        plan_id = str(uuid.uuid4())
        base    = self._get_base_planner()
        ep      = base.plan(plan_id, goal, context or {})

        tasks: list[PlanTask] = []
        for pt in ep.tasks:
            agent_name = self._assign_agent(pt.task_type, pt.description, agents)
            est_tokens, est_cost, est_ms = self._estimate(agent_name, goal, agents)
            risk   = self._task_risk(pt.description)
            rollbk = self._rollback_action(pt.description, agent_name)

            tasks.append(PlanTask(
                id              = pt.id,
                description     = pt.description,
                task_type       = pt.task_type,
                agent_name      = agent_name,
                depends_on      = pt.depends_on,
                estimated_tokens= est_tokens,
                estimated_cost  = est_cost,
                estimated_ms    = est_ms,
                risk_level      = risk,
                rollback_action = rollbk,
                metadata        = pt.metadata,
            ))

        # Aggregate
        total_tokens = sum(t.estimated_tokens for t in tasks)
        total_cost   = sum(t.estimated_cost   for t in tasks)
        total_ms     = max((t.estimated_ms for t in tasks), default=0)
        risk_level   = self._aggregate_risk(tasks)
        perm_errors  = self._validate_permissions(tasks, agents)
        warnings     = self._build_warnings(tasks, agents)
        needs_approv = (
            risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            or any(t.agent_name in _APPROVAL_REQUIRED for t in tasks)
        )
        rollback     = [t.rollback_action for t in tasks if t.rollback_action]
        groups       = ep.parallel_groups

        return RichPlan(
            plan_id         = plan_id,
            goal            = goal,
            tasks           = tasks,
            parallel_groups = groups,
            total_tokens    = total_tokens,
            total_cost_usd  = total_cost,
            total_ms        = total_ms,
            risk_level      = risk_level,
            requires_approval= needs_approv,
            permission_errors= perm_errors,
            warnings        = warnings,
            rollback_plan   = list(reversed(rollback)),
            diagnostics     = {
                "caller"           : caller,
                "base_strategy"    : ep.diagnostics.get("decomposition_strategy"),
                "task_count"       : len(tasks),
                "parallel_groups"  : len(groups),
            },
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _assign_agent(self, task_type: str, description: str,
                      agents: Optional[dict]) -> Optional[str]:
        # 1. Direct match on task_type
        candidate = _TASK_AGENT_MAP.get(task_type)
        if candidate and (agents is None or candidate in agents):
            return candidate
        # 2. Keyword scan on description
        lower = description.lower()
        for kw, name in _TASK_AGENT_MAP.items():
            if kw in lower and (agents is None or name in agents):
                return name
        # 3. Fallback to any available agent
        if agents:
            return next(iter(agents), None)
        return None

    def _estimate(self, agent_name: Optional[str], goal: str,
                  agents: Optional[dict]) -> tuple[int, float, float]:
        if agents and agent_name and agent_name in agents:
            # Minimal context for estimation
            try:
                # Lazy import to avoid circular dependency
                estimate = agents[agent_name].estimate_cost(
                    type("_FakeCtx", (), {"input": goal, "args": ""})()
                )
                return estimate.estimated_tokens, estimate.estimated_cost_usd, estimate.estimated_ms
            except Exception:
                pass
        # Heuristic fallback
        tokens = max(200, len(goal) * 3)
        return tokens, tokens * 3e-6, 300.0

    @staticmethod
    def _task_risk(description: str) -> RiskLevel:
        lower = description.lower()
        if any(k in lower for k in _CRITICAL_RISK_KEYWORDS):
            return RiskLevel.CRITICAL
        if any(k in lower for k in _HIGH_RISK_KEYWORDS):
            return RiskLevel.HIGH
        if any(k in lower for k in ("write", "create", "update", "patch", "modify")):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _aggregate_risk(tasks: list[PlanTask]) -> RiskLevel:
        levels = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        max_idx = max((levels.index(t.risk_level) for t in tasks), default=0)
        return levels[max_idx]

    @staticmethod
    def _rollback_action(description: str, agent_name: Optional[str]) -> Optional[str]:
        lower = description.lower()
        if "deploy" in lower:
            return "Rollback deployment to previous version"
        if "write" in lower or "create" in lower or "generate" in lower:
            return f"Delete generated files from {agent_name} execution"
        if "modify" in lower or "patch" in lower:
            return "Restore original files from backup"
        if "install" in lower:
            return "Uninstall added packages and restore lockfile"
        return None

    @staticmethod
    def _validate_permissions(tasks: list[PlanTask],
                               agents: Optional[dict]) -> list[str]:
        if not agents:
            return []
        errors: list[str] = []
        for task in tasks:
            name = task.agent_name
            if not name or name not in agents:
                continue
            agent = agents[name]
            perm  = agent.permissions
            lower = task.description.lower()
            if ("file" in lower or "write" in lower) and not perm.can_write_filesystem:
                errors.append(f"Task '{task.id}': agent '{name}' lacks write_filesystem permission")
            if ("run" in lower or "exec" in lower) and not perm.can_execute_subprocess:
                errors.append(f"Task '{task.id}': agent '{name}' lacks execute_subprocess permission")
        return errors

    @staticmethod
    def _build_warnings(tasks: list[PlanTask],
                        agents: Optional[dict]) -> list[str]:
        warnings: list[str] = []
        unassigned = [t for t in tasks if not t.agent_name]
        if unassigned:
            warnings.append(
                f"{len(unassigned)} task(s) have no assigned agent: "
                + ", ".join(t.id[:8] for t in unassigned)
            )
        if any(t.risk_level == RiskLevel.HIGH for t in tasks):
            warnings.append("Plan contains HIGH-risk tasks — review before executing")
        total_cost = sum(t.estimated_cost for t in tasks)
        if total_cost > 0.10:
            warnings.append(f"Estimated LLM cost ${total_cost:.4f} exceeds $0.10")
        return warnings

    # ── Stage 8: Capability Matcher ───────────────────────────────────────────

    @staticmethod
    def match_capabilities(tasks: list[PlanTask],
                           agents: Optional[dict]) -> dict[str, list[str]]:
        """
        Returns {task_id: [capable_agent_names]} — agents that could handle each task.
        Used by the scheduler to pick the least-loaded capable agent.
        """
        if not agents:
            return {t.id: [t.agent_name] if t.agent_name else [] for t in tasks}

        result: dict[str, list[str]] = {}
        for task in tasks:
            capable: list[str] = []
            for name, agent in agents.items():
                perm  = getattr(agent, "permissions", None)
                lower = task.description.lower()
                # Quick capability filter
                if "file" in lower or "write" in lower:
                    if perm and not perm.can_write_filesystem:
                        continue
                if "exec" in lower or "run" in lower:
                    if perm and not perm.can_execute_subprocess:
                        continue
                capable.append(name)
            result[task.id] = capable
        return result

    # ── Stage 9: Schedule ─────────────────────────────────────────────────────

    @staticmethod
    def schedule(tasks: list[PlanTask],
                 parallel_groups: list[list[str]]) -> list[dict]:
        """
        Build an execution schedule: timeline of waves with estimated start times.
        Returns list of {wave, task_ids, start_ms, end_ms} — for UI display.
        """
        schedule: list[dict] = []
        cursor_ms = 0.0
        task_map  = {t.id: t for t in tasks}

        for wave_idx, group in enumerate(parallel_groups):
            wave_tasks = [task_map[tid] for tid in group if tid in task_map]
            if not wave_tasks:
                continue
            wave_ms = max(t.estimated_ms for t in wave_tasks)
            schedule.append({
                "wave"    : wave_idx,
                "task_ids": group,
                "start_ms": cursor_ms,
                "end_ms"  : cursor_ms + wave_ms,
                "parallel": len(wave_tasks) > 1,
            })
            cursor_ms += wave_ms

        return schedule

    # ── Stage 10: Plan Validator ──────────────────────────────────────────────

    @staticmethod
    def validate_plan(plan: "RichPlan") -> list[str]:
        """
        Final pre-execution validation.
        Returns list of blocking issues (empty = safe to execute).
        """
        issues: list[str] = []

        if not plan.tasks:
            issues.append("Plan has no tasks")

        if plan.permission_errors:
            issues.append(f"Permission violations: {'; '.join(plan.permission_errors)}")

        if plan.risk_level == RiskLevel.CRITICAL and not plan.requires_approval:
            issues.append("Critical risk plan must require approval")

        total_cost = plan.total_cost_usd
        if total_cost > 1.00:
            issues.append(f"Estimated cost ${total_cost:.4f} exceeds $1.00 safety threshold")

        # Detect dependency cycles (any task depending on itself or invalid ID)
        task_ids = {t.id for t in plan.tasks}
        for task in plan.tasks:
            for dep in task.depends_on:
                if dep not in task_ids:
                    issues.append(f"Task {task.id} depends on unknown task {dep}")
                if dep == task.id:
                    issues.append(f"Task {task.id} depends on itself")

        return issues


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: PlanningEngine | None = None


def get_planning_engine() -> PlanningEngine:
    global _engine
    if _engine is None:
        _engine = PlanningEngine()
    return _engine
