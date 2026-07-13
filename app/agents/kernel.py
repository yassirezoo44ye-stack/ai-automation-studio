"""
AgentKernel — Autonomous Agentic OS orchestrator.

Execution pipeline for every kernel.run(input):
  ┌─────────────────────────────────────────────────────┐
  │  1. IntentParser (heuristic, <1ms)                  │
  │  2. LLMRouter    (Claude, only if confidence < 0.6) │
  │  3. Deliberation (agent voting, if ambiguous)       │
  │  4. Agent.run()  (execution + timing)               │
  │  5. Memory.add() (record result)                    │
  │  6. SelfReflector (async, non-blocking)             │
  └─────────────────────────────────────────────────────┘

Also exposes:
  - collaborate(tasks)       sequential or parallel pipeline
  - plan_and_run(goal)       decompose + execute
  - evolve()                 trigger evolution cycle
  - generate_agent(desc)     write a new agent autonomously
  - suggest()                propose new features
  - loop_stats()             background improvement loop status
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.agents.base    import AgentContext, AgentResult, EvolvableAgent
from app.agents.intent  import IntentParser
from app.agents.memory  import ExecutionRecord, AgentMemory, get_memory
from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)

_LLM_THRESHOLD       = 0.6    # below this: use LLM router
_DELIBERATION_THRESH = 0.75   # below this: use multi-agent voting


async def _publish_agent_event(event_type: str, agent_name: str, **data) -> None:
    """Best-effort event bus publish — never affects agent execution."""
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish(event_type, {"agent": agent_name, **data})
    except Exception:
        log.warning("event publish failed for agent=%s %s", agent_name, event_type, exc_info=True)


class AgentKernel:
    """Agentic OS — central orchestrator."""

    def __init__(self) -> None:
        self._agents    : dict[str, EvolvableAgent] = {}
        self._memory    : AgentMemory = get_memory()
        self._parser    : IntentParser = IntentParser()
        self._booted    : bool = False

        # Components set during boot
        self._modifier  = None
        self._reloader  = None
        self._evolution = None
        self._router    = None   # LLMRouter
        self._reflector = None   # SelfReflector
        self._deliberation = None   # Deliberation
        self._autonomy  = None   # AutonomyEngine
        self._loop      = None   # ImprovementLoop

    # ── Boot ──────────────────────────────────────────────────────────────────

    def boot(self, start_loop: bool = False) -> "AgentKernel":
        if self._booted:
            return self

        from app.kernel.self_modify import SelfModifyingEngine
        from app.kernel.reloader    import HotReloader
        from app.kernel.policy      import PolicyEngine
        from app.kernel.state       import KernelState
        from app.agents.evolution   import EvolutionEngine
        from app.agents.llm_router  import LLMRouter
        from app.agents.reflection  import SelfReflector
        from app.agents.deliberation import Deliberation
        from app.agents.autonomy    import AutonomyEngine
        from app.agents.loop        import ImprovementLoop
        from app.agents.loader      import load_all

        state              = KernelState()
        policy             = PolicyEngine()
        self._modifier     = SelfModifyingEngine(policy, state)
        self._reloader     = HotReloader(None, state)
        self._evolution    = EvolutionEngine(self._memory, self._modifier, self._reloader)
        self._router       = LLMRouter()
        self._reflector    = SelfReflector()
        self._deliberation = Deliberation()
        self._autonomy     = AutonomyEngine(self)
        self._loop         = ImprovementLoop(self)

        count = load_all(self)
        self._parser.update_agents(list(self._agents.keys()))
        self._booted = True

        if start_loop:
            asyncio.ensure_future(self._loop.start())

        log.info("AgentKernel booted: %d agents, LLM=%s",
                 count, "✓" if self._router.available() else "✗")
        return self

    # ── Agent registry ────────────────────────────────────────────────────────

    def register_agent(self, agent: EvolvableAgent) -> None:
        self._agents[agent.name] = agent
        self._parser.update_agents(list(self._agents.keys()))

    def unregister_agent(self, name: str) -> bool:
        if name in self._agents:
            del self._agents[name]
            self._parser.update_agents(list(self._agents.keys()))
            return True
        return False

    def get_agent(self, name: str) -> Optional[EvolvableAgent]:
        return self._agents.get(name)

    def all_agents(self) -> list[EvolvableAgent]:
        return list(self._agents.values())

    # ── Core execution pipeline ───────────────────────────────────────────────

    async def run(
        self,
        raw_input  : str,
        caller     : str = "system",
        user_id    : Optional[str] = None,
        workspace  : Optional[str] = None,
        project_id : Optional[str] = None,
        deliberate : bool = False,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Full pipeline: parse → route → (vote) → execute → reflect.
        """
        tracer = get_tracer()
        with tracer.start_span("agent.run", service="agent_kernel") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            if organization_id:
                span.set_tag("organization_id", organization_id)
            if user_id:
                span.set_tag("user_id", user_id)

            known = list(self._agents.keys())

            # ── 1. Heuristic intent parse ──────────────────────────────────
            ir = self._parser.parse(raw_input)

            # ── 2. LLM router (when heuristic is uncertain) ─────────────────
            if ir.confidence < _LLM_THRESHOLD and self._router and self._router.available():
                routed = await self._router.route(raw_input, known, org_id=organization_id)
                if routed and routed.intent in self._agents:
                    ir = _adapt_routed(routed)

            # ── 3. Multi-agent deliberation (when still ambiguous) ──────────
            intent_name = ir.intent
            if (deliberate or ir.confidence < _DELIBERATION_THRESH) and \
                    self._deliberation and len(self._agents) >= 2:
                delib = await self._deliberation.vote(raw_input, self, ir.intent, org_id=organization_id)
                if delib.winner in self._agents:
                    intent_name = delib.winner

            span.set_tag("intent", intent_name)

            # ── 4. Agent selection + execution ───────────────────────────────
            agent = self._agents.get(intent_name)

            if agent is None:
                result = AgentResult(
                    agent   = "kernel",
                    success = False,
                    output  = f"No agent for intent: {intent_name!r}",
                    data    = {
                        "intent"     : intent_name,
                        "confidence" : ir.confidence,
                        "suggestions": ir.suggestions,
                        "agents"     : known,
                    },
                    error = "agent_not_found",
                )
                span.set_tag("error", "agent_not_found")
            else:
                ctx = AgentContext(
                    input      = raw_input,
                    args       = ir.args,
                    kernel     = self,
                    memory     = self._memory,
                    caller     = caller,
                    user_id    = user_id,
                    workspace  = workspace,
                    project_id = project_id,
                    organization_id = organization_id,
                )
                await _publish_agent_event("agent.started", intent_name, user_id=user_id)
                result = await agent.run(ctx)
                await _publish_agent_event(
                    "agent.finished", intent_name, user_id=user_id,
                    success=result.success, duration_ms=result.duration_ms,
                )
                if not result.success:
                    span.set_tag("error", result.error or "agent_failed")
                if organization_id:
                    try:
                        from app.billing import get_usage_service
                        await get_usage_service().record(
                            organization_id, "running_agents", 1,
                            ref_type="agent", ref_id=intent_name,
                        )
                    except Exception:
                        log.warning("agent usage record failed for org=%s", organization_id, exc_info=True)

            # ── 5. Memory ────────────────────────────────────────────────────
            self._memory.add(ExecutionRecord(
                agent       = result.agent,
                input       = raw_input,
                args        = ir.args,
                success     = result.success,
                duration_ms = result.duration_ms,
                error       = result.error,
                data        = {"intent_confidence": ir.confidence, "intent_method": ir.method},
            ))

            # ── 6. Self-reflection (non-blocking) ────────────────────────────
            if self._reflector:
                self._reflector.reflect(result, self._memory, self._evolution, org_id=organization_id)

            return result

    # ── Multi-agent collaboration ─────────────────────────────────────────────

    async def collaborate(
        self,
        tasks     : list[str],
        caller    : str = "system",
        user_id   : Optional[str] = None,
        workspace : Optional[str] = None,
        parallel  : bool = False,
        organization_id: Optional[str] = None,
    ) -> list[AgentResult]:
        if parallel:
            return list(await asyncio.gather(*[
                self.run(t, caller=caller, user_id=user_id, workspace=workspace,
                         organization_id=organization_id)
                for t in tasks
            ]))

        results: list[AgentResult] = []
        for task in tasks:
            r = await self.run(task, caller=caller, user_id=user_id, workspace=workspace,
                               organization_id=organization_id)
            results.append(r)
            if not r.success:
                log.warning("pipeline stopped at: %s", task)
                break
        return results

    async def deliberate_and_run(
        self,
        raw_input: str,
        **kwargs,
    ) -> tuple[AgentResult, dict]:
        """Run with explicit deliberation — returns (result, vote_record)."""
        delib = await self._deliberation.vote(raw_input, self, org_id=kwargs.get("organization_id"))
        result = await self.run(raw_input, deliberate=False, **kwargs)
        return result, delib.to_dict()

    async def plan_and_run(
        self,
        goal      : str,
        caller    : str = "system",
        user_id   : Optional[str] = None,
        workspace : Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> dict:
        plan_result = await self.run(f"plan {goal}", caller=caller,
                                     user_id=user_id, workspace=workspace,
                                     organization_id=organization_id)
        tasks = plan_result.data.get("tasks", [])
        if not tasks:
            return {
                "plan"   : [],
                "results": [plan_result.to_dict()],
                "success": plan_result.success,
            }
        results = await self.collaborate(tasks, caller=caller, user_id=user_id,
                                         workspace=workspace, organization_id=organization_id)
        return {
            "plan"   : tasks,
            "results": [r.to_dict() for r in results],
            "success": all(r.success for r in results),
        }

    # ── Autonomous development ────────────────────────────────────────────────

    async def generate_agent(self, description: str,
                             agent_name: Optional[str] = None,
                             organization_id: Optional[str] = None) -> dict:
        if self._autonomy is None:
            return {"status": "error", "error": "autonomy engine not initialized"}
        return await self._autonomy.generate_agent(description, agent_name, org_id=organization_id)

    async def suggest(self, n: int = 3, organization_id: Optional[str] = None) -> list[dict]:
        if self._autonomy is None:
            return []
        suggestions = await self._autonomy.suggest_improvements(n, org_id=organization_id)
        return [s.to_dict() for s in suggestions]

    async def implement(self, index: int, organization_id: Optional[str] = None) -> dict:
        if self._autonomy is None:
            return {"status": "error"}
        return await self._autonomy.implement_suggestion(index, org_id=organization_id)

    async def autonomous_loop(self, cycles: int = 3, organization_id: Optional[str] = None) -> list[dict]:
        if self._autonomy is None:
            return []
        return await self._autonomy.continuous_loop(cycles, org_id=organization_id)

    # ── Evolution ─────────────────────────────────────────────────────────────

    async def evolve(self, organization_id: Optional[str] = None) -> dict:
        if self._evolution is None:
            return {"status": "error", "error": "evolution engine not initialized"}
        return (await self._evolution.evolve(org_id=organization_id)).to_dict()

    def evolution_analysis(self) -> dict:
        if self._evolution is None:
            return {"status": "not_initialized"}
        return self._evolution.analyze().to_dict()

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        stats = self._memory.global_stats()
        return {
            "agents"       : len(self._agents),
            "agent_names"  : list(self._agents.keys()),
            "memory_count" : self._memory.total_count(),
            "performance"  : [s.to_dict() for s in stats],
            "booted"       : self._booted,
            "llm_available": self._router.available() if self._router else False,
            "loop_stats"   : self._loop.stats() if self._loop else {},
            "reflections"  : self._reflector.to_dict_list() if self._reflector else [],
            "suggestions"  : self._autonomy.all_suggestions() if self._autonomy else [],
        }

    def loop_stats(self) -> dict:
        return self._loop.stats() if self._loop else {"running": False}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _adapt_routed(routed) -> "IntentResult":
    """Convert RoutedIntent → IntentResult duck-type."""
    from app.agents.intent import IntentResult
    return IntentResult(
        intent     = routed.intent,
        args       = routed.args,
        confidence = routed.confidence,
        method     = routed.method,
        raw        = routed.raw_input,
    )


# ── Singleton ─────────────────────────────────────────────────────────────────

_kernel: AgentKernel | None = None


def get_agent_kernel() -> AgentKernel:
    global _kernel
    if _kernel is None:
        _kernel = AgentKernel()
        _kernel.boot()
    return _kernel
