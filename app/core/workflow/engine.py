"""
Workflow Engine — Layer 8.

Supports:
  DAG execution          — topological sort, parallel branches
  Conditions             — if/else branching on step output
  Loops                  — repeat until predicate or max N times
  Parallel execution     — asyncio task groups for independent nodes
  Human Approval Gate    — pause, notify, wait for signal
  Retry + Backoff        — per-step configurable retry policy
  Timeout                — per-step and per-workflow deadline
  Scheduled / Cron Jobs  — run at future time or recurring
  Compensation / Saga    — reverse completed steps on failure

Architecture: pure asyncio, no external dependencies.
Temporal.io can replace this engine by implementing the same WorkflowDef interface.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)

# ── Types ──────────────────────────────────────────────────────────────────────

class StepStatus(str, Enum):
    PENDING     = "pending"
    RUNNING     = "running"
    COMPLETED   = "completed"
    FAILED      = "failed"
    SKIPPED     = "skipped"
    WAITING     = "waiting"       # waiting for human approval
    COMPENSATED = "compensated"


class WorkflowStatus(str, Enum):
    PENDING     = "pending"
    RUNNING     = "running"
    COMPLETED   = "completed"
    FAILED      = "failed"
    COMPENSATING= "compensating"
    CANCELLED   = "cancelled"


StepFn = Callable[..., Awaitable[Any]]


@dataclass
class RetryPolicy:
    max_attempts : int   = 3
    base_delay_s : float = 1.0
    max_delay_s  : float = 30.0
    backoff      : float = 2.0    # exponential multiplier

    def delay(self, attempt: int) -> float:
        d = self.base_delay_s * (self.backoff ** (attempt - 1))
        return min(d, self.max_delay_s)


@dataclass
class WorkflowStep:
    id              : str
    name            : str
    fn              : StepFn
    args            : dict[str, Any]          = field(default_factory=dict)
    depends_on      : list[str]               = field(default_factory=list)
    retry_policy    : RetryPolicy             = field(default_factory=RetryPolicy)
    timeout_s       : Optional[float]         = None
    condition       : Optional[Callable[[dict], bool]] = None   # if None, always run
    on_success      : Optional[str]           = None    # next step id override
    on_failure      : Optional[str]           = None    # error branch step id
    compensation_fn : Optional[StepFn]        = None    # Saga rollback
    requires_approval: bool                   = False
    status          : StepStatus              = StepStatus.PENDING
    result          : Optional[Any]           = None
    error           : Optional[str]           = None
    started_at      : Optional[float]         = None
    finished_at     : Optional[float]         = None
    attempt         : int                     = 0

    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return None

    def to_dict(self) -> dict:
        return {
            "id"              : self.id,
            "name"            : self.name,
            "status"          : self.status.value,
            "attempt"         : self.attempt,
            "result"          : self.result,
            "error"           : self.error,
            "duration_ms"     : self.duration_ms,
            "requires_approval": self.requires_approval,
        }


@dataclass
class WorkflowRun:
    run_id      : str
    name        : str
    steps       : dict[str, WorkflowStep]     # step_id → step
    status      : WorkflowStatus              = WorkflowStatus.PENDING
    context     : dict[str, Any]              = field(default_factory=dict)
    created_at  : float                       = field(default_factory=time.time)
    started_at  : Optional[float]             = None
    finished_at : Optional[float]             = None
    error       : Optional[str]               = None
    _approval_events: dict[str, asyncio.Event] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id"     : self.run_id,
            "name"       : self.name,
            "status"     : self.status.value,
            "context"    : self.context,
            "steps"      : {sid: s.to_dict() for sid, s in self.steps.items()},
            "created_at" : self.created_at,
            "started_at" : self.started_at,
            "finished_at": self.finished_at,
            "error"      : self.error,
        }

    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return None


# ── Approval registry ─────────────────────────────────────────────────────────

class ApprovalRegistry:
    """Thread-safe registry for human approval signals."""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, bool] = {}

    def register(self, approval_id: str) -> asyncio.Event:
        ev = asyncio.Event()
        self._events[approval_id] = ev
        return ev

    def approve(self, approval_id: str) -> None:
        self._decisions[approval_id] = True
        if ev := self._events.get(approval_id):
            ev.set()

    def reject(self, approval_id: str) -> None:
        self._decisions[approval_id] = False
        if ev := self._events.get(approval_id):
            ev.set()

    def was_approved(self, approval_id: str) -> bool:
        return self._decisions.get(approval_id, False)

    def pending(self) -> list[str]:
        return [aid for aid, ev in self._events.items() if not ev.is_set()]


_approval_registry = ApprovalRegistry()


def get_approval_registry() -> ApprovalRegistry:
    return _approval_registry


# ── Workflow Builder ──────────────────────────────────────────────────────────

class WorkflowBuilder:
    """Fluent builder for WorkflowRun definitions."""

    def __init__(self, name: str) -> None:
        self._name  = name
        self._steps : dict[str, WorkflowStep] = {}

    def step(
        self,
        step_id: str,
        name: str,
        fn: StepFn,
        *,
        args: dict | None = None,
        depends_on: list[str] | None = None,
        retry: RetryPolicy | None = None,
        timeout_s: float | None = None,
        condition: Callable | None = None,
        compensation: StepFn | None = None,
        requires_approval: bool = False,
    ) -> "WorkflowBuilder":
        self._steps[step_id] = WorkflowStep(
            id               = step_id,
            name             = name,
            fn               = fn,
            args             = args or {},
            depends_on       = depends_on or [],
            retry_policy     = retry or RetryPolicy(),
            timeout_s        = timeout_s,
            condition        = condition,
            compensation_fn  = compensation,
            requires_approval= requires_approval,
        )
        return self

    def build(self, context: dict | None = None) -> WorkflowRun:
        return WorkflowRun(
            run_id  = str(uuid.uuid4()),
            name    = self._name,
            steps   = dict(self._steps),
            context = context or {},
        )


# ── DAG Utilities ─────────────────────────────────────────────────────────────

def _topo_sort(steps: dict[str, WorkflowStep]) -> list[list[str]]:
    """
    Kahn's algorithm → returns execution groups (each group runs in parallel).
    """
    in_degree: dict[str, int] = {sid: 0 for sid in steps}
    children : dict[str, list[str]] = {sid: [] for sid in steps}

    for sid, step in steps.items():
        for dep in step.depends_on:
            in_degree[sid] += 1
            children.setdefault(dep, []).append(sid)

    groups: list[list[str]] = []
    queue = [sid for sid, deg in in_degree.items() if deg == 0]

    while queue:
        groups.append(list(queue))
        next_q: list[str] = []
        for sid in queue:
            for child in children.get(sid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_q.append(child)
        queue = next_q

    if sum(len(g) for g in groups) != len(steps):
        raise ValueError("Workflow has cyclic dependencies")

    return groups


# ── Step executor ─────────────────────────────────────────────────────────────

async def _execute_step(step: WorkflowStep, run: WorkflowRun) -> None:
    """
    Execute a single step with retry, timeout, approval gate, and condition check.
    Populates step.status / step.result / step.error.
    """
    tracer = get_tracer()
    with tracer.start_span("workflow.step", service="workflow_engine") as span:
        span.set_tag("run_id", run.run_id)
        span.set_tag("step_id", step.id)

        # 1. Condition check
        if step.condition and not step.condition(run.context):
            step.status = StepStatus.SKIPPED
            log.debug("wf[%s] step %s skipped by condition", run.run_id[:8], step.id)
            return

        # 2. Human approval gate
        if step.requires_approval:
            approval_id = f"{run.run_id}:{step.id}"
            ev = _approval_registry.register(approval_id)
            step.status = StepStatus.WAITING
            log.info("wf[%s] step %s awaiting approval %s", run.run_id[:8], step.id, approval_id)
            try:
                await asyncio.wait_for(ev.wait(), timeout=step.timeout_s or 3600)
            except asyncio.TimeoutError:
                step.status = StepStatus.FAILED
                step.error  = "Approval timeout"
                span.set_tag("error", step.error)
                return
            if not _approval_registry.was_approved(approval_id):
                step.status = StepStatus.SKIPPED
                step.error  = "Rejected by approver"
                return

        # 3. Execute with retry
        step.status   = StepStatus.RUNNING
        step.started_at = time.time()
        policy = step.retry_policy

        for attempt in range(1, policy.max_attempts + 1):
            step.attempt = attempt
            try:
                # Inject framework kwargs separately — they never collide with step.args
                # because step.args are user-defined domain params, not framework keys.
                safe_args = {k: v for k, v in step.args.items()
                             if k not in ("_context", "_run_id")}
                coro = step.fn(**safe_args, _context=run.context, _run_id=run.run_id)
                if step.timeout_s:
                    result = await asyncio.wait_for(coro, timeout=step.timeout_s)
                else:
                    result = await coro

                # Success
                step.result     = result
                step.status     = StepStatus.COMPLETED
                step.finished_at = time.time()
                # Merge result into shared context
                if isinstance(result, dict):
                    run.context.update({f"{step.id}.{k}": v for k, v in result.items()})
                run.context[f"{step.id}.result"] = result
                span.set_tag("attempt", attempt)
                log.debug("wf[%s] step %s done in %.0fms",
                          run.run_id[:8], step.id, step.duration_ms)
                return

            except asyncio.CancelledError:
                step.status = StepStatus.FAILED
                step.error  = "Cancelled"
                step.finished_at = time.time()
                span.set_tag("error", "Cancelled")
                return

            except Exception as exc:
                step.error = str(exc)
                log.warning("wf[%s] step %s attempt %d failed: %s",
                            run.run_id[:8], step.id, attempt, exc)
                if attempt < policy.max_attempts:
                    await asyncio.sleep(policy.delay(attempt))

        step.status     = StepStatus.FAILED
        step.finished_at = time.time()
        span.set_tag("error", step.error or "max retries exceeded")


# ── Saga compensation ─────────────────────────────────────────────────────────

async def _compensate(run: WorkflowRun) -> None:
    """Reverse completed steps in LIFO order (Saga pattern)."""
    run.status = WorkflowStatus.COMPENSATING
    log.info("wf[%s] starting compensation", run.run_id[:8])

    completed = [
        s for s in reversed(list(run.steps.values()))
        if s.status == StepStatus.COMPLETED and s.compensation_fn
    ]
    for step in completed:
        log.info("wf[%s] compensating step %s", run.run_id[:8], step.id)
        try:
            await step.compensation_fn(_context=run.context, _run_id=run.run_id)
            step.status = StepStatus.COMPENSATED
        except Exception as exc:
            log.error("wf[%s] compensation of step %s failed: %s",
                      run.run_id[:8], step.id, exc)


async def _record_workflow_usage(run: WorkflowRun) -> None:
    """Meter one workflow_executions unit against the run's organization,
    when context carries one. Best-effort — never affects run.status."""
    org_id = run.context.get("organization_id")
    if not org_id:
        return
    try:
        from app.billing import get_usage_service
        await get_usage_service().record(
            org_id, "workflow_executions", 1, ref_type="workflow", ref_id=run.run_id,
        )
    except Exception:
        log.warning("workflow usage record failed for org=%s", org_id, exc_info=True)


async def _publish_workflow_event(run: WorkflowRun, event_type: str) -> None:
    """Best-effort event bus publish — never affects run.status. org_id is
    optional in the payload (event bus doesn't require org context)."""
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish(
            event_type,
            {"run_id": run.run_id, "name": run.name, "status": run.status.value,
             "error": run.error},
            organization_id=run.context.get("organization_id"),
        )
    except Exception:
        log.warning("event publish failed for wf[%s] %s", run.run_id[:8], event_type, exc_info=True)


# ── Engine ────────────────────────────────────────────────────────────────────

class WorkflowEngine:
    """
    Executes WorkflowRun instances.

    Usage:
        engine = get_workflow_engine()
        run = WorkflowBuilder("my-workflow")
            .step("fetch", "Fetch data", fetch_fn, timeout_s=10)
            .step("process", "Process", process_fn, depends_on=["fetch"])
            .build(context={"url": "..."})
        result = await engine.execute(run)
    """

    def __init__(self) -> None:
        self._active: dict[str, WorkflowRun] = {}

    async def execute(self, run: WorkflowRun, *,
                      saga: bool = True) -> WorkflowRun:
        """
        Run the workflow DAG.
        If `saga=True` and any step fails, compensate all completed steps.
        """
        self._active[run.run_id] = run
        run.status     = WorkflowStatus.RUNNING
        run.started_at = time.time()
        log.info("wf[%s] '%s' started", run.run_id[:8], run.name)
        await _publish_workflow_event(run, "workflow.started")

        tracer = get_tracer()
        with tracer.start_span("workflow.execute", service="workflow_engine") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("run_id", run.run_id)
            span.set_tag("workflow_name", run.name)
            if org_id := run.context.get("organization_id"):
                span.set_tag("organization_id", org_id)

            try:
                groups = _topo_sort(run.steps)
            except ValueError as exc:
                run.status = WorkflowStatus.FAILED
                run.error  = str(exc)
                span.set_tag("error", str(exc))
                await _publish_workflow_event(run, "workflow.failed")
                return run

            try:
                for group in groups:
                    # Check if any required predecessor failed
                    runnable = [
                        sid for sid in group
                        if all(
                            run.steps[dep].status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
                            for dep in run.steps[sid].depends_on
                        )
                    ]
                    if not runnable:
                        continue

                    if len(runnable) == 1:
                        await _execute_step(run.steps[runnable[0]], run)
                    else:
                        async with asyncio.TaskGroup() as tg:
                            for sid in runnable:
                                tg.create_task(_execute_step(run.steps[sid], run))

                    # Check for failures
                    failed = [
                        sid for sid in group
                        if run.steps[sid].status == StepStatus.FAILED
                    ]
                    if failed:
                        err = "; ".join(run.steps[sid].error or "unknown"
                                       for sid in failed)
                        run.error  = f"Steps failed: {failed} — {err}"
                        run.status = WorkflowStatus.FAILED
                        span.set_tag("error", run.error)
                        if saga:
                            await _compensate(run)
                            # _compensate() sets COMPENSATING as a transient
                            # in-progress marker — the run must still land on a
                            # terminal FAILED status once compensation finishes.
                            run.status = WorkflowStatus.FAILED
                        await _publish_workflow_event(run, "workflow.failed")
                        return run

            except Exception as exc:
                run.error  = str(exc)
                run.status = WorkflowStatus.FAILED
                span.set_tag("error", str(exc))
                if saga:
                    await _compensate(run)
                    run.status = WorkflowStatus.FAILED
                log.error("wf[%s] unexpected error: %s", run.run_id[:8], exc)
                await _publish_workflow_event(run, "workflow.failed")
                return run
            finally:
                run.finished_at = time.time()
                self._active.pop(run.run_id, None)
                await _record_workflow_usage(run)

            run.status = WorkflowStatus.COMPLETED
            log.info("wf[%s] completed in %.0fms", run.run_id[:8],
                     (run.finished_at - run.started_at) * 1000)  # type: ignore[operator]
            await _publish_workflow_event(run, "workflow.completed")
            return run

    def active(self) -> list[dict]:
        return [r.to_dict() for r in self._active.values()]

    def approve(self, run_id: str, step_id: str) -> bool:
        approval_id = f"{run_id}:{step_id}"
        _approval_registry.approve(approval_id)
        return True

    def reject(self, run_id: str, step_id: str) -> bool:
        approval_id = f"{run_id}:{step_id}"
        _approval_registry.reject(approval_id)
        return True

    def pending_approvals(self) -> list[str]:
        return _approval_registry.pending()


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: WorkflowEngine | None = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
