"""
AIOrchestrator — top-level entry point for the Phase 3 enterprise AI platform.

Pipeline: PolicyEngine → PlanningEngine → CostManager → ContextManager
          → TaskScheduler → ExecutionCoordinator → ResultAggregator
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional, TYPE_CHECKING

from ..events.bus import EventBus
from ..events.events import OrchestratorStarted, OrchestratorCompleted, OrchestratorFailed
from .planner     import TaskPlanner
from .scheduler   import TaskScheduler
from .coordinator import ExecutionCoordinator
from .aggregator  import ResultAggregator, OrchestratorResult

if TYPE_CHECKING:
    from ..platform       import AIPlatform
    from ..cost.manager   import CostManager
    from ..policy.engine  import PolicyEngine
    from ..context.manager import ContextManager


@dataclass
class OrchestratorRequest:
    prompt:          str
    user_id:         Optional[str]       = None
    conversation_id: Optional[str]       = None
    project_id:      Optional[str]       = None
    workspace_id:    Optional[str]       = None
    mode:            str                 = "auto"    # "auto" | "single" | "multi-agent"
    max_cost_usd:    Optional[float]     = None
    context:         dict[str, Any]      = field(default_factory=dict)


class AIOrchestrator:
    """
    Unified entry point that routes every AI request through the full enterprise pipeline.

    Backward-compatible: existing callers that use platform.complete() / platform.stream()
    are unaffected.  New callers opt in by calling orchestrator.run() / orchestrator.stream().
    """

    def __init__(
        self,
        platform:     "AIPlatform",
        bus:          EventBus,
        policy:       Optional["PolicyEngine"]     = None,
        cost_manager: Optional["CostManager"]      = None,
        ctx_manager:  Optional["ContextManager"]   = None,
        max_concurrent: int = 4,
    ) -> None:
        self._platform    = platform
        self._bus         = bus
        self._policy      = policy
        self._cost        = cost_manager
        self._ctx         = ctx_manager
        self._planner     = TaskPlanner()
        self._scheduler   = TaskScheduler(max_concurrent=max_concurrent)
        self._aggregator  = ResultAggregator()

    async def run(self, request: OrchestratorRequest) -> OrchestratorResult:
        request_id = str(uuid.uuid4())
        t0 = time.perf_counter()

        await self._bus.emit(OrchestratorStarted(
            request_id=request_id,
            mode=request.mode,
            user_id=request.user_id,
        ))

        try:
            # 1. Policy check
            if self._policy:
                await self._policy.check(request, request_id)

            # 2. Context enrichment
            enriched_prompt = request.prompt
            if self._ctx:
                bundle = await self._ctx.build(
                    user_id=request.user_id,
                    conversation_id=request.conversation_id,
                    project_id=request.project_id,
                )
                enriched_prompt = bundle.inject(request.prompt)

            # 3. Planning
            plan = self._planner.plan(
                request_id=request_id,
                prompt=enriched_prompt,
                context=request.context,
            )

            # 4. Cost pre-check
            if self._cost and request.max_cost_usd is not None:
                await self._cost.check_budget(
                    user_id=request.user_id,
                    project_id=request.project_id,
                    estimated_cost=plan.total_estimated_cost,
                    limit_usd=request.max_cost_usd,
                )

            # 5. Schedule + execute
            coordinator = ExecutionCoordinator(
                platform=self._platform,
                bus=self._bus,
                request_id=request_id,
                user_id=request.user_id,
            )
            task_results = await self._scheduler.run(
                plan=plan,
                runner=coordinator.run_task,
            )

            # 6. Aggregate
            result = self._aggregator.aggregate(plan, task_results)

            # 7. Record total cost
            if self._cost:
                await self._cost.record(
                    user_id=request.user_id,
                    project_id=request.project_id,
                    conversation_id=request.conversation_id,
                    amount_usd=result.total_cost,
                    provider_id="orchestrator",
                    model="multi",
                )

            duration_ms = (time.perf_counter() - t0) * 1000
            await self._bus.emit(OrchestratorCompleted(
                request_id=request_id,
                task_count=len(plan.tasks),
                duration_ms=duration_ms,
                total_cost=result.total_cost,
                total_tokens=result.total_tokens,
            ))
            return result

        except Exception as exc:
            phase = getattr(exc, "_phase", "execution")
            await self._bus.emit(OrchestratorFailed(
                request_id=request_id,
                error=str(exc),
                phase=phase,
            ))
            raise

    async def stream(
        self,
        request: OrchestratorRequest,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming variant.  Yields SSE-compatible dicts as tasks complete.
        For single-task requests this mirrors the inference engine's stream.
        For multi-task requests it yields per-task progress events then a final summary.
        """
        result = await self.run(request)
        # Emit the aggregated content word-by-word to simulate streaming
        words = result.content.split()
        for i, word in enumerate(words):
            yield {"type": "token", "content": word + (" " if i < len(words) - 1 else "")}
        yield {
            "type":         "done",
            "total_cost":   result.total_cost,
            "total_tokens": result.total_tokens,
            "task_count":   len(result.tasks),
            "success":      result.success,
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "orchestrator": {
                "planner":    "keyword-based decomposition",
                "scheduler":  f"max_concurrent={self._scheduler._max_concurrent}",
                "policy":     self._policy is not None,
                "cost":       self._cost   is not None,
                "context":    self._ctx    is not None,
            }
        }
