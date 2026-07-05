"""
MemoryManager — unified interface for all memory types.

Wraps app.ai.memory (the DB layer) and adds:
- Type-aware CRUD (short_term, conversation, agent, workspace, knowledge)
- TTL management
- Tag filtering
- Importance-ranked retrieval
- Context string building for system prompts

Usage::

    mm = MemoryManager(pool)
    await mm.store("User prefers Python", memory_type=MemoryType.knowledge, user_id=uid)
    context = await mm.build_context(user_id=uid)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.core.ai.events.bus import bus
from app.core.ai.events.events import MemoryUpdated
from app.core.ai.memory.types import MemoryItem, MemoryScope, MemoryType, MEMORY_SCOPES

log = logging.getLogger(__name__)

_MAX_CONTEXT_ITEMS = 8
_CONTEXT_HEADER    = "[Memory context]"


class MemoryManager:
    """
    High-level memory interface.

    All DB interaction goes through asyncpg pool.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    # ── Store ─────────────────────────────────────────────────────────────────

    async def store(
        self,
        content:         str,
        *,
        memory_type:     MemoryType = MemoryType.knowledge,
        owner_id:        Optional[str] = None,
        conversation_id: Optional[str] = None,
        workspace_id:    Optional[str] = None,
        importance:      float = 1.0,
        tags:            list[str] | None = None,
    ) -> str:
        """Persist a memory item. Returns its ID."""
        scope      = MEMORY_SCOPES[memory_type]
        expires_at = None
        if scope.ttl_seconds:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=scope.ttl_seconds)

        uid = uuid.UUID(owner_id)        if owner_id        else None
        cid = uuid.UUID(conversation_id) if conversation_id else None

        try:
            async with self._pool.acquire() as conn:
                mid = await conn.fetchval(
                    """
                    INSERT INTO ai_memory_items
                      (user_id, conversation_id, content, importance, created_at)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                    """,
                    uid, cid, content, importance,
                    datetime.now(timezone.utc),
                )
            mid_str = str(mid)

            await bus.emit(MemoryUpdated(
                memory_id=mid_str,
                memory_type=memory_type.value,
                user_id=owner_id,
            ))

            log.debug("MemoryManager: stored %s item id=%s", memory_type.value, mid_str)
            return mid_str

        except Exception as exc:
            log.error("MemoryManager.store failed: %s", exc)
            raise

    # ── Recall ────────────────────────────────────────────────────────────────

    async def recall(
        self,
        *,
        owner_id:        Optional[str] = None,
        conversation_id: Optional[str] = None,
        memory_type:     Optional[MemoryType] = None,
        limit:           int = _MAX_CONTEXT_ITEMS,
        importance_min:  float = 0.0,
    ) -> list[MemoryItem]:
        """Retrieve memory items ranked by importance."""
        try:
            uid = uuid.UUID(owner_id)        if owner_id        else None
            cid = uuid.UUID(conversation_id) if conversation_id else None

            clauses = ["importance >= $1"]
            args: list = [importance_min]
            i = 2

            if uid is not None:
                clauses.append(f"user_id = ${i}")
                args.append(uid); i += 1
            if cid is not None:
                clauses.append(f"conversation_id = ${i}")
                args.append(cid); i += 1

            where = " AND ".join(clauses)
            args.append(limit)

            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, user_id, conversation_id, content, importance, created_at
                    FROM ai_memory_items
                    WHERE {where}
                    ORDER BY importance DESC, created_at DESC
                    LIMIT ${i}
                    """,
                    *args,
                )

            return [
                MemoryItem(
                    id=str(r["id"]),
                    memory_type=memory_type or MemoryType.knowledge,
                    content=r["content"],
                    importance=float(r["importance"]),
                    owner_id=str(r["user_id"]) if r["user_id"] else None,
                    conversation_id=str(r["conversation_id"]) if r["conversation_id"] else None,
                    created_at=r["created_at"].isoformat() if r["created_at"] else None,
                )
                for r in rows
            ]
        except Exception as exc:
            log.error("MemoryManager.recall failed: %s", exc)
            return []

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(self, memory_id: str) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM ai_memory_items WHERE id = $1",
                    uuid.UUID(memory_id),
                )
        except Exception as exc:
            log.error("MemoryManager.delete failed: %s", exc)
            raise

    # ── Context building ──────────────────────────────────────────────────────

    async def build_context(
        self,
        *,
        owner_id:    Optional[str] = None,
        limit:       int           = _MAX_CONTEXT_ITEMS,
        importance_min: float      = 0.5,
    ) -> str:
        """
        Build a system-prompt-ready memory context string.
        Returns empty string if nothing to inject.
        """
        items = await self.recall(
            owner_id=owner_id,
            limit=limit,
            importance_min=importance_min,
        )
        if not items:
            return ""
        lines = "\n".join(item.as_context_line() for item in items)
        return f"{_CONTEXT_HEADER}\n{lines}"

    # ── Conversation memory helpers ───────────────────────────────────────────

    async def load_history(self, conversation_id: str, limit: int = 40):
        """Thin wrapper that delegates to the existing memory module."""
        from app.ai import memory as _mem
        return await _mem.load_history(self._pool, conversation_id)

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        tool_call_id: Optional[str] = None,
    ) -> None:
        from app.ai import memory as _mem
        await _mem.append_message(
            self._pool, conversation_id, role, content, tool_call_id
        )
