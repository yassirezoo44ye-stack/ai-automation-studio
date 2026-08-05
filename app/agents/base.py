"""
EvolvableAgent — production-grade interface for all Agentic OS agents.

Every agent exposes:
  - metadata       : AgentMetadata (name, version, group, tags)
  - capabilities   : list[AgentCapability]
  - permissions    : AgentPermissions
  - execute()      : core logic → AgentResult
  - validate()     : pre-flight check on context/args → ValidationResult
  - estimate_cost(): token + time + risk estimate
  - health_check() : liveness probe → HealthStatus

Backward-compatible: existing agents that only implement execute() continue
to work; new methods have safe defaults.
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.agents.memory import AgentMemory
    from app.agents.kernel import AgentKernel


# ── Metadata ──────────────────────────────────────────────────────────────────

@dataclass
class AgentMetadata:
    name       : str
    version    : str            = "1.0.0"
    description: str            = ""
    group      : str            = "general"
    author     : str            = "system"
    tags       : list[str]      = field(default_factory=list)
    created_at : str            = ""
    deprecated : bool           = False

    def to_dict(self) -> dict:
        return {
            "name"       : self.name,
            "version"    : self.version,
            "description": self.description,
            "group"      : self.group,
            "author"     : self.author,
            "tags"       : self.tags,
            "deprecated" : self.deprecated,
        }


# ── Capabilities ──────────────────────────────────────────────────────────────

class CapabilityKind(str, Enum):
    READ      = "read"
    WRITE     = "write"
    EXECUTE   = "execute"
    NETWORK   = "network"
    LLM       = "llm"
    MEMORY    = "memory"
    EVOLUTION = "evolution"
    UI        = "ui"


@dataclass
class AgentCapability:
    kind       : CapabilityKind
    description: str
    required   : bool = True

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "description": self.description, "required": self.required}


# ── Permissions ───────────────────────────────────────────────────────────────

@dataclass
class AgentPermissions:
    """Declares what this agent is allowed to touch."""
    can_read_filesystem    : bool = False
    can_write_filesystem   : bool = False
    can_execute_subprocess : bool = False
    can_call_llm           : bool = True
    can_access_network     : bool = False
    can_modify_agents      : bool = False
    can_access_memory      : bool = True
    max_execution_seconds  : float = 30.0
    # Cumulative $/token ceiling for one run, enforced between successive
    # LLM calls (see RunBudget below) — None means unlimited, so every
    # existing agent is unaffected by default.
    max_cost_usd           : Optional[float] = None
    max_tokens             : Optional[int]   = None
    allowed_paths          : list[str] = field(default_factory=list)
    denied_paths           : list[str] = field(default_factory=lambda: [
        ".git", "migrations", "alembic", ".env", ".pem", ".key"
    ])

    def to_dict(self) -> dict:
        return {
            "can_read_filesystem"   : self.can_read_filesystem,
            "can_write_filesystem"  : self.can_write_filesystem,
            "can_execute_subprocess": self.can_execute_subprocess,
            "can_call_llm"          : self.can_call_llm,
            "can_access_network"    : self.can_access_network,
            "can_modify_agents"     : self.can_modify_agents,
            "can_access_memory"     : self.can_access_memory,
            "max_execution_seconds" : self.max_execution_seconds,
            "max_cost_usd"          : self.max_cost_usd,
            "max_tokens"            : self.max_tokens,
        }


# ── Run budget (Cost Guard) ───────────────────────────────────────────────────

@dataclass
class RunBudget:
    """Cumulative cost/token ceiling for one agent run.

    Enforced BETWEEN successive LLM calls, not mid-single-call — no current
    agent code path streams a response incrementally (see
    AgentContext.report_usage's docstring), so a running total accumulated
    via report_usage() after each complete call is what's actually
    achievable today. `max_cost_usd`/`max_tokens` of None means that
    dimension is unlimited.
    """
    max_cost_usd : Optional[float] = None
    max_tokens   : Optional[int]   = None
    spent_usd    : float = 0.0
    spent_tokens : int   = 0
    _exceeded    : asyncio.Event = field(default_factory=asyncio.Event, repr=False, compare=False)

    def record(self, cost_usd: float, tokens: int) -> None:
        self.spent_usd    += cost_usd
        self.spent_tokens += tokens
        if self.max_cost_usd is not None and self.spent_usd >= self.max_cost_usd:
            self._exceeded.set()
        if self.max_tokens is not None and self.spent_tokens >= self.max_tokens:
            self._exceeded.set()

    @property
    def exceeded(self) -> bool:
        return self._exceeded.is_set()

    async def wait_exceeded(self) -> None:
        await self._exceeded.wait()


# ── Context ───────────────────────────────────────────────────────────────────

@dataclass
class AgentContext:
    """Shared execution environment passed to every agent."""
    input      : str
    args       : str
    kernel     : "AgentKernel"
    memory     : "AgentMemory"
    caller     : str  = "system"
    user_id    : Optional[str] = None
    workspace  : Optional[str] = None
    project_id : Optional[str] = None
    organization_id: Optional[str] = None
    extra      : dict = field(default_factory=dict)
    # Correlates this specific invocation's live step narration (see
    # step() below) — distinct from trace_id, which is for OTel spans,
    # not the AgentOS "live computer" UI. Set by AgentKernel.run() before
    # execute() is ever called; agents never generate their own.
    run_id     : str = ""
    # Tracing / observability
    trace_id   : Optional[str] = None
    span_id    : Optional[str] = None

    # Set by EvolvableAgent.run() right before execute() so step() can
    # report which agent it's narrating for without every call site
    # having to pass the name in explicitly.
    _agent_name_hint: str = field(default="", repr=False, compare=False)

    # Set by EvolvableAgent.run() right before execute(), from
    # self.permissions.max_cost_usd/max_tokens — never None during a real
    # run, but Optional here since a hand-constructed AgentContext (tests,
    # ad hoc callers) may not set one.
    budget: Optional["RunBudget"] = None

    async def report_usage(self, cost_usd: float, tokens: int) -> None:
        """Best-effort cost/token accounting — call after every LLM call
        an agent makes. Modeled on step()'s contract: never raises, never
        affects control flow directly on its own failure. It CAN trip the
        run's budget (see RunBudget.record), which EvolvableAgent.run()
        watches for and uses to cancel the run — that's the entire
        mechanism, there is no other side effect."""
        try:
            if self.budget is not None:
                self.budget.record(cost_usd, tokens)
        except Exception:
            pass

    async def step(self, description: str, kind: str = "info", **data) -> None:
        """Narrate a live sub-step of this run — e.g. "Running npm build",
        "Reading config.json" — broadcast immediately so a "live computer"
        view can show what the agent is doing as it happens, not just the
        final AgentResult once execute() returns. Purely additive and
        best-effort: agents call this for UX, never for control flow, and
        a broadcast failure must never surface as an agent error."""
        try:
            from app.agents.liveness import publish_step
            await publish_step(self.run_id, self._agent_name_hint, description, kind, **data)
        except Exception:
            pass


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    """Execution outcome returned by every agent."""
    agent      : str
    success    : bool
    output     : str
    data       : dict = field(default_factory=dict)
    error      : Optional[str] = None
    duration_ms: float = 0.0
    # Tracing
    trace_id   : Optional[str] = None

    @classmethod
    def ok(cls, agent: str, output: str, data: dict | None = None,
           duration_ms: float = 0.0) -> "AgentResult":
        return cls(agent=agent, success=True, output=output,
                   data=data or {}, duration_ms=duration_ms)

    @classmethod
    def fail(cls, agent: str, error: str, data: dict | None = None,
             duration_ms: float = 0.0) -> "AgentResult":
        return cls(agent=agent, success=False, output=f"Error: {error}",
                   error=error, data=data or {}, duration_ms=duration_ms)

    def to_dict(self) -> dict:
        return {
            "agent"      : self.agent,
            "success"    : self.success,
            "output"     : self.output,
            "data"       : self.data,
            "error"      : self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


# ── Validation ────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid   : bool
    errors  : list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(valid=True)

    @classmethod
    def fail(cls, *errors: str) -> "ValidationResult":
        return cls(valid=False, errors=list(errors))

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


# ── Cost estimation ───────────────────────────────────────────────────────────

@dataclass
class CostEstimate:
    estimated_tokens  : int   = 0
    estimated_cost_usd: float = 0.0
    estimated_ms      : float = 100.0
    complexity        : str   = "low"    # low | medium | high
    risk_level        : str   = "low"    # low | medium | high | critical
    requires_approval : bool  = False

    def to_dict(self) -> dict:
        return {
            "estimated_tokens"  : self.estimated_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "estimated_ms"      : round(self.estimated_ms, 1),
            "complexity"        : self.complexity,
            "risk_level"        : self.risk_level,
            "requires_approval" : self.requires_approval,
        }


# ── Health ────────────────────────────────────────────────────────────────────

class HealthStatus(str, Enum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN   = "unknown"


@dataclass
class AgentHealth:
    status : HealthStatus
    message: str = ""
    checks : dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"status": self.status.value, "message": self.message, "checks": self.checks}


# ── Agent lifecycle ───────────────────────────────────────────────────────────

class AgentLifecycle(str, Enum):
    CREATED    = "created"
    ACTIVE     = "active"
    SUSPENDED  = "suspended"
    DEPRECATED = "deprecated"
    REMOVED    = "removed"


# ── Base class ────────────────────────────────────────────────────────────────

class EvolvableAgent(ABC):
    """
    Production-grade base for all Agentic OS agents.

    Required:
      - name, description — class-level constants
      - execute(ctx)      — core async logic

    Optional overrides (all have safe defaults):
      - metadata          — AgentMetadata instance
      - capabilities      — list[AgentCapability]
      - permissions       — AgentPermissions instance
      - validate(ctx)     — pre-flight validation
      - estimate_cost(ctx)— resource estimation
      - health_check()    — liveness probe
      - performance_hint()— hints for evolution engine
    """

    name       : str = "unnamed"
    description: str = "No description."
    group      : str = "general"
    version    : str = "1.0.0"

    # Lifecycle state
    _lifecycle : AgentLifecycle = AgentLifecycle.ACTIVE

    # ── Required ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def execute(self, ctx: AgentContext) -> AgentResult:
        ...

    # ── Metadata + capabilities (safe defaults) ───────────────────────────────

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            name=self.name,
            version=self.version,
            description=self.description,
            group=self.group,
        )

    @property
    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(kind=CapabilityKind.LLM, description="LLM-assisted execution")]

    @property
    def permissions(self) -> AgentPermissions:
        return AgentPermissions()

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self, ctx: AgentContext) -> ValidationResult:
        """Pre-flight check. Override to add custom validation logic."""
        if not ctx.input.strip():
            return ValidationResult.fail("Input cannot be empty")
        return ValidationResult.ok()

    # ── Cost estimation ───────────────────────────────────────────────────────

    def estimate_cost(self, ctx: AgentContext) -> CostEstimate:
        """Rough estimation. Override with agent-specific logic."""
        tokens = max(100, len(ctx.input) * 2)
        return CostEstimate(
            estimated_tokens=tokens,
            estimated_cost_usd=tokens * 3e-6,
            estimated_ms=200.0,
        )

    # ── Health check ──────────────────────────────────────────────────────────

    def health_check(self) -> AgentHealth:
        """Liveness probe. Override to add dependency checks."""
        return AgentHealth(
            status=HealthStatus.HEALTHY if self._lifecycle == AgentLifecycle.ACTIVE else HealthStatus.DEGRADED,
            message="OK",
            checks={"lifecycle": self._lifecycle == AgentLifecycle.ACTIVE},
        )

    # ── Performance hint (kept for backward compat) ───────────────────────────

    def performance_hint(self) -> dict:
        return {}

    # ── Timed wrapper ─────────────────────────────────────────────────────────

    async def run(self, ctx: AgentContext) -> AgentResult:
        """Execute with validation + timing + budget enforcement. Called by
        AgentKernel.

        Races execute(ctx) against two independent cancellation triggers:
        the pre-existing wall-clock timeout (max_execution_seconds), and —
        new — the run's cost/token budget (max_cost_usd/max_tokens), which
        ctx.report_usage() trips via ctx.budget. When neither limit is set
        (the default for every existing agent) the budget_task simply isn't
        created, and the result is externally equivalent to the prior
        asyncio.wait_for(...) behavior — same wall-clock timeout, same
        cancel-then-AgentResult.fail() outcome. Not byte-for-byte
        identical internally (asyncio.wait() over a task set has slightly
        different cancellation-propagation timing than asyncio.wait_for()
        wrapping a single coroutine), but no existing agent's observable
        behavior changes."""
        # Validate first
        validation = self.validate(ctx)
        if not validation.valid:
            return AgentResult.fail(
                self.name,
                "Validation failed: " + "; ".join(validation.errors),
            )

        ctx._agent_name_hint = self.name
        ctx.budget = RunBudget(
            max_cost_usd=self.permissions.max_cost_usd,
            max_tokens=self.permissions.max_tokens,
        )
        t0 = time.perf_counter()

        exec_task = asyncio.ensure_future(self.execute(ctx))
        budget_task = None
        if ctx.budget.max_cost_usd is not None or ctx.budget.max_tokens is not None:
            budget_task = asyncio.ensure_future(ctx.budget.wait_exceeded())
        waitables = {exec_task} | ({budget_task} if budget_task else set())

        done, _pending = await asyncio.wait(
            waitables, timeout=self.permissions.max_execution_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if exec_task in done:
            if budget_task is not None and not budget_task.done():
                budget_task.cancel()
                try:
                    await budget_task
                except asyncio.CancelledError:
                    pass
            try:
                result = exec_task.result()
            except asyncio.CancelledError:
                ms = (time.perf_counter() - t0) * 1000
                result = AgentResult.fail(self.name, "execution cancelled", duration_ms=ms)
            except Exception as exc:
                ms = (time.perf_counter() - t0) * 1000
                result = AgentResult.fail(self.name, str(exc), duration_ms=ms)
            else:
                result.duration_ms = (time.perf_counter() - t0) * 1000
        elif budget_task is not None and budget_task in done:
            exec_task.cancel()
            try:
                await exec_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            ms = (time.perf_counter() - t0) * 1000
            b = ctx.budget
            spent = []
            if b.max_cost_usd is not None:
                spent.append(f"${b.spent_usd:.4f}/${b.max_cost_usd:.4f}")
            if b.max_tokens is not None:
                spent.append(f"{b.spent_tokens}/{b.max_tokens} tokens")
            result = AgentResult.fail(
                self.name, "budget_exceeded: spent " + ", ".join(spent), duration_ms=ms,
            )
        else:
            # Neither finished within max_execution_seconds.
            exec_task.cancel()
            if budget_task is not None:
                budget_task.cancel()
            try:
                await exec_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            if budget_task is not None:
                try:
                    await budget_task
                except asyncio.CancelledError:
                    pass
            ms = (time.perf_counter() - t0) * 1000
            result = AgentResult.fail(
                self.name, f"execution exceeded max_execution_seconds={self.permissions.max_execution_seconds}",
                duration_ms=ms,
            )

        # Propagate trace if ctx has one
        if ctx.trace_id:
            result.trace_id = ctx.trace_id

        return result

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name"        : self.name,
            "description" : self.description,
            "group"       : self.group,
            "version"     : self.version,
            "lifecycle"   : self._lifecycle.value,
            "metadata"    : self.metadata.to_dict(),
            "capabilities": [c.to_dict() for c in self.capabilities],
            "permissions" : self.permissions.to_dict(),
            "hints"       : self.performance_hint(),
        }
