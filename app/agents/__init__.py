"""
Agentic OS — Autonomous Self-Evolving Runtime.

4-layer execution pipeline per request:
  1. Intent Understanding  (IntentParser + LLMRouter)
  2. Agent Selection       (Deliberation voting when ambiguous)
  3. Execution             (EvolvableAgent.run)
  4. Self-Reflection       (SelfReflector → EvolutionEngine)

Background:
  ImprovementLoop          continuous self-improvement every N seconds
  AutonomyEngine           autonomous feature generation via LLM

Public API:
    from app.agents import get_agent_kernel

    kernel = get_agent_kernel()
    result = await kernel.run("deploy my project")

    # Autonomous
    await kernel.generate_agent("a caching agent for build outputs")
    await kernel.suggest(n=3)
    await kernel.autonomous_loop(cycles=3)

    # Deliberation
    result, vote = await kernel.deliberate_and_run("build and ship")
"""
from app.agents.kernel      import AgentKernel, get_agent_kernel
from app.agents.base        import EvolvableAgent, AgentContext, AgentResult
from app.agents.memory      import AgentMemory, ExecutionRecord, get_memory
from app.agents.intent      import IntentParser, IntentResult
from app.agents.llm_router  import LLMRouter, RoutedIntent, get_llm_router
from app.agents.reflection  import SelfReflector, ReflectionRecord, get_reflector
from app.agents.deliberation import Deliberation, AgentBid, DeliberationResult
from app.agents.evolution   import EvolutionEngine, EvolutionReport
from app.agents.autonomy    import AutonomyEngine, Suggestion
from app.agents.loop        import ImprovementLoop, LoopTick

__all__ = [
    # Core
    "AgentKernel",    "get_agent_kernel",
    "EvolvableAgent", "AgentContext",      "AgentResult",
    # Memory
    "AgentMemory",    "ExecutionRecord",   "get_memory",
    # Intent
    "IntentParser",   "IntentResult",
    "LLMRouter",      "RoutedIntent",      "get_llm_router",
    # Reflection
    "SelfReflector",  "ReflectionRecord",  "get_reflector",
    # Deliberation
    "Deliberation",   "AgentBid",          "DeliberationResult",
    # Evolution
    "EvolutionEngine","EvolutionReport",
    # Autonomy
    "AutonomyEngine", "Suggestion",
    # Loop
    "ImprovementLoop","LoopTick",
]
