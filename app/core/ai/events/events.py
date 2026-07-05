"""
AI Platform event types.

Every cross-cutting concern communicates through events — no direct coupling
between services. Emit an event; subscribers handle side-effects.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


def _id() -> str:
    return str(uuid.uuid4())


def _ts() -> float:
    return time.time()


# ── Base ──────────────────────────────────────────────────────────────────────

@dataclass
class AIEvent:
    event_id:   str   = field(default_factory=_id)
    timestamp:  float = field(default_factory=_ts)
    # Subclasses set this to their canonical name
    event_type: str   = "ai.event"

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ── Provider / Model events ───────────────────────────────────────────────────

@dataclass
class ProviderSelected(AIEvent):
    event_type:  str = "ai.provider.selected"
    provider_id: str = ""
    model:       str = ""
    reason:      str = ""          # "preferred" | "failover" | "default"


@dataclass
class ProviderFailed(AIEvent):
    event_type:  str = "ai.provider.failed"
    provider_id: str = ""
    error:       str = ""
    attempt:     int = 0


@dataclass
class ModelSelected(AIEvent):
    event_type:   str = "ai.model.selected"
    provider_id:  str = ""
    model:        str = ""
    selection_reason: str = ""


# ── Prompt events ─────────────────────────────────────────────────────────────

@dataclass
class PromptStarted(AIEvent):
    event_type:      str            = "ai.prompt.started"
    request_id:      str            = field(default_factory=_id)
    provider_id:     str            = ""
    model:           str            = ""
    conversation_id: Optional[str]  = None
    user_id:         Optional[str]  = None
    input_tokens_estimate: int      = 0


@dataclass
class PromptCompleted(AIEvent):
    event_type:      str   = "ai.prompt.completed"
    request_id:      str   = ""
    provider_id:     str   = ""
    model:           str   = ""
    input_tokens:    int   = 0
    output_tokens:   int   = 0
    cost_usd:        float = 0.0
    latency_ms:      float = 0.0
    cached:          bool  = False


# ── Stream events ─────────────────────────────────────────────────────────────

@dataclass
class StreamStarted(AIEvent):
    event_type:  str           = "ai.stream.started"
    request_id:  str           = field(default_factory=_id)
    provider_id: str           = ""
    model:       str           = ""
    user_id:     Optional[str] = None


@dataclass
class StreamEnded(AIEvent):
    event_type:   str   = "ai.stream.ended"
    request_id:   str   = ""
    provider_id:  str   = ""
    chunks_emitted: int = 0
    latency_ms:   float = 0.0


# ── Tool events ───────────────────────────────────────────────────────────────

@dataclass
class ToolCalled(AIEvent):
    event_type:  str            = "ai.tool.called"
    tool_name:   str            = ""
    arguments:   dict[str, Any] = field(default_factory=dict)
    call_id:     str            = field(default_factory=_id)
    user_id:     Optional[str]  = None


@dataclass
class ToolFinished(AIEvent):
    event_type:  str   = "ai.tool.finished"
    tool_name:   str   = ""
    call_id:     str   = ""
    success:     bool  = True
    latency_ms:  float = 0.0
    error:       Optional[str] = None


# ── Conversation events ───────────────────────────────────────────────────────

@dataclass
class ConversationCreated(AIEvent):
    event_type:      str           = "ai.conversation.created"
    conversation_id: str           = ""
    user_id:         Optional[str] = None
    title:           str           = ""


@dataclass
class ConversationArchived(AIEvent):
    event_type:      str = "ai.conversation.archived"
    conversation_id: str = ""


# ── Memory events ─────────────────────────────────────────────────────────────

@dataclass
class MemoryUpdated(AIEvent):
    event_type:      str           = "ai.memory.updated"
    memory_id:       str           = ""
    memory_type:     str           = ""
    user_id:         Optional[str] = None


# ── Prompt-store events ───────────────────────────────────────────────────────

@dataclass
class PromptSaved(AIEvent):
    event_type: str           = "ai.prompt.saved"
    prompt_id:  str           = ""
    slug:       str           = ""
    version:    int           = 1
    user_id:    Optional[str] = None


# ── Orchestrator events ───────────────────────────────────────────────────────

@dataclass
class OrchestratorStarted(AIEvent):
    event_type:  str            = "ai.orchestrator.started"
    request_id:  str            = field(default_factory=_id)
    mode:        str            = "auto"
    task_count:  int            = 0
    user_id:     Optional[str]  = None


@dataclass
class OrchestratorCompleted(AIEvent):
    event_type:   str   = "ai.orchestrator.completed"
    request_id:   str   = ""
    task_count:   int   = 0
    duration_ms:  float = 0.0
    total_cost:   float = 0.0
    total_tokens: int   = 0


@dataclass
class OrchestratorFailed(AIEvent):
    event_type:  str   = "ai.orchestrator.failed"
    request_id:  str   = ""
    error:       str   = ""
    phase:       str   = ""   # "planning" | "scheduling" | "execution" | "aggregation"


@dataclass
class TaskStarted(AIEvent):
    event_type:  str            = "ai.task.started"
    task_id:     str            = ""
    task_type:   str            = ""
    agent_id:    Optional[str]  = None
    request_id:  str            = ""


@dataclass
class TaskCompleted(AIEvent):
    event_type:   str   = "ai.task.completed"
    task_id:      str   = ""
    request_id:   str   = ""
    duration_ms:  float = 0.0
    cost_usd:     float = 0.0


@dataclass
class TaskFailed(AIEvent):
    event_type:  str   = "ai.task.failed"
    task_id:     str   = ""
    request_id:  str   = ""
    error:       str   = ""
    attempt:     int   = 0


# ── Workflow events ───────────────────────────────────────────────────────────

@dataclass
class WorkflowStarted(AIEvent):
    event_type:    str   = "ai.workflow.started"
    workflow_id:   str   = ""
    execution_id:  str   = field(default_factory=_id)
    node_count:    int   = 0


@dataclass
class WorkflowNodeEntered(AIEvent):
    event_type:    str  = "ai.workflow.node.entered"
    execution_id:  str  = ""
    node_id:       str  = ""
    node_type:     str  = ""


@dataclass
class WorkflowNodeCompleted(AIEvent):
    event_type:    str   = "ai.workflow.node.completed"
    execution_id:  str   = ""
    node_id:       str   = ""
    duration_ms:   float = 0.0


@dataclass
class WorkflowCompleted(AIEvent):
    event_type:    str   = "ai.workflow.completed"
    execution_id:  str   = ""
    workflow_id:   str   = ""
    duration_ms:   float = 0.0
    nodes_executed: int  = 0


@dataclass
class WorkflowFailed(AIEvent):
    event_type:   str  = "ai.workflow.failed"
    execution_id: str  = ""
    workflow_id:  str  = ""
    node_id:      str  = ""
    error:        str  = ""


# ── Multi-agent events ────────────────────────────────────────────────────────

@dataclass
class AgentStarted(AIEvent):
    event_type:  str            = "ai.agent.started"
    agent_name:  str            = ""
    agent_id:    Optional[str]  = None
    task_id:     str            = ""


@dataclass
class AgentCompleted(AIEvent):
    event_type:  str   = "ai.agent.completed"
    agent_name:  str   = ""
    task_id:     str   = ""
    duration_ms: float = 0.0
    success:     bool  = True


@dataclass
class AgentMessage(AIEvent):
    """Agent-to-agent communication through the bus."""
    event_type:   str            = "ai.agent.message"
    from_agent:   str            = ""
    to_agent:     Optional[str]  = None    # None = broadcast
    message_type: str            = ""
    payload:      dict[str, Any] = field(default_factory=dict)


# ── Policy events ─────────────────────────────────────────────────────────────

@dataclass
class PolicyViolation(AIEvent):
    event_type:  str  = "ai.policy.violation"
    policy_name: str  = ""
    rule:        str  = ""
    value:       str  = ""
    limit:       str  = ""


# ── Cost events ───────────────────────────────────────────────────────────────

@dataclass
class CostRecorded(AIEvent):
    event_type:      str            = "ai.cost.recorded"
    amount_usd:      float          = 0.0
    provider_id:     str            = ""
    model:           str            = ""
    conversation_id: Optional[str]  = None
    project_id:      Optional[str]  = None
    agent_name:      Optional[str]  = None


@dataclass
class BudgetExceeded(AIEvent):
    event_type:  str   = "ai.cost.budget_exceeded"
    scope:       str   = ""    # "request" | "conversation" | "project" | "global"
    scope_id:    str   = ""
    limit_usd:   float = 0.0
    actual_usd:  float = 0.0


# ── Streaming events ──────────────────────────────────────────────────────────

@dataclass
class StreamCancelled(AIEvent):
    event_type:  str  = "ai.stream.cancelled"
    request_id:  str  = ""
    reason:      str  = ""


@dataclass
class StreamResumed(AIEvent):
    event_type:  str  = "ai.stream.resumed"
    request_id:  str  = ""
    from_offset: int  = 0


# ── Knowledge events ──────────────────────────────────────────────────────────

@dataclass
class DocumentIngested(AIEvent):
    event_type:  str  = "ai.knowledge.ingested"
    doc_id:      str  = ""
    chunk_count: int  = 0
    source:      str  = ""


@dataclass
class KnowledgeSearched(AIEvent):
    event_type:     str   = "ai.knowledge.searched"
    query:          str   = ""
    result_count:   int   = 0
    latency_ms:     float = 0.0
