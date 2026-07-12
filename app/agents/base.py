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
from typing import TYPE_CHECKING, Any, Optional

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
        }


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
    extra      : dict = field(default_factory=dict)
    # Tracing / observability
    trace_id   : Optional[str] = None
    span_id    : Optional[str] = None


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
        """Execute with validation + timing. Called by AgentKernel."""
        # Validate first
        validation = self.validate(ctx)
        if not validation.valid:
            return AgentResult.fail(
                self.name,
                "Validation failed: " + "; ".join(validation.errors),
            )

        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(self.execute(ctx), timeout=self.permissions.max_execution_seconds)
        except asyncio.TimeoutError:
            ms = (time.perf_counter() - t0) * 1000
            result = AgentResult.fail(
                self.name, f"execution exceeded max_execution_seconds={self.permissions.max_execution_seconds}",
                duration_ms=ms,
            )
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            result = AgentResult.fail(self.name, str(exc), duration_ms=ms)
        else:
            result.duration_ms = (time.perf_counter() - t0) * 1000

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
