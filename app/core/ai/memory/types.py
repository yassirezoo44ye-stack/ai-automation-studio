"""
Memory type definitions for the MemoryManager.

Each type has different scope, TTL semantics, and storage characteristics.
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class MemoryType(str, Enum):
    short_term    = "short_term"     # Current context window messages
    conversation  = "conversation"   # Full conversation history
    agent         = "agent"          # Agent-scoped state between calls
    workspace     = "workspace"      # Project-scoped shared memory
    knowledge     = "knowledge"      # Long-term user facts (highest importance)


@dataclass
class MemoryScope:
    """Describes where a memory item lives and how long it persists."""
    memory_type:     MemoryType
    ttl_seconds:     Optional[int]  = None   # None = persist forever
    max_items:       int            = 100
    importance_min:  float          = 0.0    # Only keep items above this threshold
    tags:            list[str]      = field(default_factory=list)


# Default scopes per memory type
MEMORY_SCOPES: dict[MemoryType, MemoryScope] = {
    MemoryType.short_term: MemoryScope(
        memory_type=MemoryType.short_term,
        ttl_seconds=3_600,       # 1 hour
        max_items=40,
    ),
    MemoryType.conversation: MemoryScope(
        memory_type=MemoryType.conversation,
        ttl_seconds=None,        # permanent until deleted
        max_items=1_000,
    ),
    MemoryType.agent: MemoryScope(
        memory_type=MemoryType.agent,
        ttl_seconds=86_400,      # 1 day
        max_items=50,
    ),
    MemoryType.workspace: MemoryScope(
        memory_type=MemoryType.workspace,
        ttl_seconds=None,
        max_items=200,
    ),
    MemoryType.knowledge: MemoryScope(
        memory_type=MemoryType.knowledge,
        ttl_seconds=None,
        max_items=500,
        importance_min=0.5,
    ),
}


@dataclass
class MemoryItem:
    id:              str
    memory_type:     MemoryType
    content:         str
    importance:      float = 1.0
    owner_id:        Optional[str] = None      # user_id or agent_id
    conversation_id: Optional[str] = None
    workspace_id:    Optional[str] = None
    tags:            list[str] = field(default_factory=list)
    embedding_id:    Optional[str] = None      # future: vector DB ID
    created_at:      Optional[str] = None
    expires_at:      Optional[str] = None

    def as_context_line(self) -> str:
        """Format for injection into a system prompt."""
        tag_str = f" [{', '.join(self.tags)}]" if self.tags else ""
        return f"- {self.content}{tag_str}"
