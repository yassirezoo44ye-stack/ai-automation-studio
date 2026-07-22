"""
AIPlatform — the single entry point for the entire AI subsystem.

Import this everywhere instead of importing individual services.

Usage::

    from app.core.ai.platform import platform

    # Complete
    resp = await platform.complete(request, user_id=uid)

    # Stream
    async for chunk in platform.stream(request, user_id=uid):
        ...

    # Memory
    await platform.memory.store("User likes Python", user_id=uid)

    # Conversation
    cid = await platform.conversations.create(user_id=uid)

    # Prompts
    preview = await platform.prompts.preview("my-prompt", variables={"x": "y"})

    # Diagnostics
    report = await platform.diagnostics()
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

from app.ai.models import CompletionRequest, CompletionResponse
from app.core.ai.agents.runtime import AgentConfig, AgentRuntime
from app.core.ai.agents.builtin import create_builtin, BUILTIN_AGENTS
from app.core.ai.cache.manager import CacheManager, cache_manager
from app.core.ai.context.manager import ContextManager
from app.core.ai.cost.manager import CostManager
from app.core.ai.embeddings.service import EmbeddingsService, embeddings
from app.core.ai.events.bus import EventBus, bus
from app.core.ai.inference.engine import InferenceEngine
from app.core.ai.knowledge.engine import KnowledgeEngine
from app.core.ai.memory.manager import MemoryManager
from app.core.ai.orchestrator.orchestrator import AIOrchestrator, OrchestratorRequest, OrchestratorResult
from app.core.ai.policy.engine import PolicyEngine, PolicyConfig
from app.core.ai.prompts.engine import PromptEngine
from app.core.ai.registry.registry import PlatformProviderRegistry, platform_registry
from app.core.ai.router.model_router import ModelRouter, model_router
from app.core.ai.services.conversation import ConversationService
from app.core.ai.services.diagnostics import diagnostics
from app.core.ai.streaming.engine import StreamingEngine
from app.core.ai.telemetry.service import TelemetryService, telemetry
from app.core.ai.tools.executor import ToolExecutor, executor as tool_executor
from app.core.ai.tools.marketplace import ToolMarketplace
from app.core.ai.workflow.engine import WorkflowEngine

log = logging.getLogger(__name__)


class AIPlatform:
    """
    Unified facade for all AI platform capabilities.

    One import, all services.  Phase 3 adds: orchestrator, workflow engine,
    context manager, cost manager, policy engine, streaming engine,
    knowledge engine, tool marketplace, and 8 built-in agents.
    """

    def __init__(self, pool=None) -> None:
        self._pool = pool

        # Lazy-created per-request services (pool-dependent)
        self._engine:        Optional[InferenceEngine]  = None
        self._memory_mgr:    Optional[MemoryManager]    = None
        self._conv_svc:      Optional[ConversationService] = None
        self._prompt_engine: Optional[PromptEngine]     = None

        # Stateless / singleton services (Phase 1-2)
        self.registry:    PlatformProviderRegistry = platform_registry
        self.router:      ModelRouter              = model_router
        self.cache:       CacheManager             = cache_manager
        self.embeddings:  EmbeddingsService        = embeddings
        self.telemetry:   TelemetryService         = telemetry
        self.events:      EventBus                 = bus

        # Phase 3 services
        self._context_mgr:  ContextManager    = ContextManager()
        self._cost_mgr:     CostManager       = CostManager(bus=bus)
        self._policy:       PolicyEngine      = PolicyEngine(bus=bus)
        self.streaming:     StreamingEngine   = StreamingEngine(bus=bus)
        self.workflow:      WorkflowEngine    = WorkflowEngine(bus=bus)
        self._knowledge:    Optional[KnowledgeEngine]  = None
        self._marketplace:  Optional[ToolMarketplace]  = None
        self._orchestrator: Optional[AIOrchestrator]   = None
        self._builtin_agents: dict[str, AgentRuntime]  = {}

        # tools exposed directly (Phase 1 compat) + marketplace wrapper
        self.tools: ToolExecutor = tool_executor

    def init(self, pool) -> None:
        """
        Wire in the database pool at startup.
        Call this once from the app lifespan handler.
        """
        self._pool           = pool
        self._engine         = InferenceEngine(pool=pool)
        self._memory_mgr     = MemoryManager(pool=pool)
        self._conv_svc       = ConversationService(pool=pool)
        self._prompt_engine  = PromptEngine(pool=pool)
        telemetry._pool      = pool

        # Phase 3 pool wiring
        self._context_mgr.init(pool)

        # Phase 3 compound services
        self._knowledge   = KnowledgeEngine(embeddings=embeddings, bus=bus)
        self._marketplace = ToolMarketplace(executor=tool_executor)
        self._orchestrator = AIOrchestrator(
            platform=self,
            bus=bus,
            policy=self._policy,
            cost_manager=self._cost_mgr,
            ctx_manager=self._context_mgr,
        )

        # Pre-instantiate built-in agents
        for name in BUILTIN_AGENTS:
            try:
                self._builtin_agents[name] = create_builtin(
                    name=name, bus=bus, pool=pool, executor=tool_executor
                )
            except Exception as exc:
                log.warning("Failed to create built-in agent %r: %s", name, exc)

        log.info("AIPlatform initialized with database pool (Phase 3 active)")

    # ── Inference ─────────────────────────────────────────────────────────────

    async def complete(
        self,
        request: CompletionRequest,
        *,
        user_id:    Optional[str] = None,
        org_id:     Optional[str] = None,
        auto_tools: bool          = True,
    ) -> CompletionResponse:
        return await self._engine_or_raise().complete(
            request, user_id=user_id, org_id=org_id, auto_tools=auto_tools
        )

    async def stream(
        self,
        request: CompletionRequest,
        *,
        user_id:    Optional[str] = None,
        org_id:     Optional[str] = None,
        auto_tools: bool          = True,
    ) -> AsyncGenerator[dict, None]:
        async for chunk in self._engine_or_raise().stream(
            request, user_id=user_id, org_id=org_id, auto_tools=auto_tools
        ):
            yield chunk

    # ── Service properties (pool-dependent) ───────────────────────────────────

    @property
    def memory(self) -> MemoryManager:
        return self._memory_mgr or MemoryManager(pool=self._pool)

    @property
    def conversations(self) -> ConversationService:
        return self._conv_svc or ConversationService(pool=self._pool)

    @property
    def prompts(self) -> PromptEngine:
        return self._prompt_engine or PromptEngine(pool=self._pool)

    # ── Phase 3: Orchestrator ─────────────────────────────────────────────────

    async def orchestrate(self, request: OrchestratorRequest) -> OrchestratorResult:
        """Run a request through the full enterprise orchestration pipeline."""
        if self._orchestrator is None:
            self._orchestrator = AIOrchestrator(
                platform=self, bus=bus,
                policy=self._policy, cost_manager=self._cost_mgr, ctx_manager=self._context_mgr,
            )
        return await self._orchestrator.run(request)

    @property
    def orchestrator(self) -> AIOrchestrator:
        if self._orchestrator is None:
            self._orchestrator = AIOrchestrator(platform=self, bus=bus)
        return self._orchestrator

    # ── Phase 3: Knowledge ────────────────────────────────────────────────────

    @property
    def knowledge(self) -> KnowledgeEngine:
        if self._knowledge is None:
            self._knowledge = KnowledgeEngine(embeddings=embeddings, bus=bus)
        return self._knowledge

    # ── Phase 3: Marketplace ──────────────────────────────────────────────────

    @property
    def marketplace(self) -> ToolMarketplace:
        if self._marketplace is None:
            self._marketplace = ToolMarketplace(executor=tool_executor)
        return self._marketplace

    # ── Phase 3: Policy ───────────────────────────────────────────────────────

    def set_policy(self, config: PolicyConfig) -> None:
        self._policy.update(config)

    # ── Phase 3: Cost ─────────────────────────────────────────────────────────

    @property
    def cost(self) -> CostManager:
        return self._cost_mgr

    # ── Phase 3: Context ──────────────────────────────────────────────────────

    @property
    def context_manager(self) -> ContextManager:
        return self._context_mgr

    # ── Agents ────────────────────────────────────────────────────────────────

    def create_agent(self, config: AgentConfig) -> AgentRuntime:
        return AgentRuntime(config=config, pool=self._pool, executor=self.tools)

    def get_agent(self, name: str) -> Optional[AgentRuntime]:
        """Return a pre-instantiated built-in agent by name, or None."""
        return self._builtin_agents.get(name)

    def list_agents(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "status": "ready"}
            for name in self._builtin_agents
        ]

    # ── Diagnostics ───────────────────────────────────────────────────────────

    async def diagnostics(self, *, include_db: bool = False) -> dict:
        report = await diagnostics.report(pool=self._pool, include_db_metrics=include_db)
        base   = report.as_dict()

        # Augment with Phase 3 metrics
        base["phase3"] = {
            "orchestrator":  self._orchestrator.diagnostics() if self._orchestrator else None,
            "streaming":     self.streaming.diagnostics(),
            "knowledge":     self._knowledge.diagnostics() if self._knowledge else None,
            "marketplace":   self._marketplace.diagnostics() if self._marketplace else None,
            "cost":          self._cost_mgr.summary(),
            "agents":        list(self._builtin_agents.keys()),
            "workflow_execs": len(self.workflow._executions),
        }
        return base

    @property
    def inference_engine(self) -> InferenceEngine:
        return self._engine_or_raise()

    # ── Private ───────────────────────────────────────────────────────────────

    def _engine_or_raise(self) -> InferenceEngine:
        if self._engine is None:
            # Fallback: create engine without pool (cache/memory won't persist)
            self._engine = InferenceEngine(pool=self._pool)
        return self._engine


# Module-level singleton — initialized at startup
platform = AIPlatform()
