"""
Conversation memory.

Short-term: loads recent messages from ai_messages for context window.
Long-term:  stores key facts in ai_memory_items, injected as system context.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.ai.models import Message

log = logging.getLogger(__name__)

# Max messages to inject from short-term history
MAX_HISTORY_MESSAGES = 40


# ── Short-term: conversation history ─────────────────────────────────────────

async def load_history(pool, conversation_id: str) -> list[Message]:
    """Return recent messages for a conversation, oldest first."""
    try:
        cid = uuid.UUID(conversation_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content FROM ai_messages
                WHERE conversation_id = $1
                ORDER BY created_at
                LIMIT $2
                """,
                cid, MAX_HISTORY_MESSAGES,
            )
        return [Message(role=r["role"], content=r["content"]) for r in rows]
    except Exception as exc:
        log.error("memory.load_history failed: %s", exc)
        return []


async def append_message(
    pool,
    conversation_id: str,
    role: str,
    content: str,
    tool_call_id: Optional[str] = None,
) -> None:
    """Persist one message to ai_messages."""
    try:
        cid = uuid.UUID(conversation_id)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ai_messages
                  (conversation_id, role, content, tool_call_id, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                cid, role, content, tool_call_id, datetime.now(timezone.utc),
            )
            await conn.execute(
                "UPDATE ai_conversations SET updated_at=$1 WHERE id=$2",
                datetime.now(timezone.utc), cid,
            )
    except Exception as exc:
        log.error("memory.append_message failed: %s", exc)


async def create_conversation(
    pool,
    *,
    user_id: Optional[str],
    title: str = "New conversation",
    project_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> str:
    """Create a new conversation and return its ID."""
    uid = uuid.UUID(user_id)  if user_id    else None
    pid = uuid.UUID(project_id) if project_id else None
    aid = uuid.UUID(agent_id)   if agent_id   else None
    async with pool.acquire() as conn:
        cid = await conn.fetchval(
            """
            INSERT INTO ai_conversations (user_id, project_id, agent_id, title)
            VALUES ($1, $2, $3, $4) RETURNING id
            """,
            uid, pid, aid, title,
        )
    return str(cid)


# ── Long-term memory ──────────────────────────────────────────────────────────

async def store_memory(
    pool,
    *,
    user_id: Optional[str],
    content: str,
    conversation_id: Optional[str] = None,
    importance: float = 1.0,
) -> str:
    """Store a long-term memory item. Returns its ID."""
    uid = uuid.UUID(user_id)          if user_id          else None
    cid = uuid.UUID(conversation_id)  if conversation_id  else None
    async with pool.acquire() as conn:
        mid = await conn.fetchval(
            """
            INSERT INTO ai_memory_items
              (user_id, conversation_id, content, importance, created_at)
            VALUES ($1,$2,$3,$4,$5) RETURNING id
            """,
            uid, cid, content, importance, datetime.now(timezone.utc),
        )
    return str(mid)


async def recall(
    pool,
    *,
    user_id: Optional[str],
    limit: int = 8,
) -> list[str]:
    """Retrieve the most important long-term memory items for a user."""
    try:
        uid = uuid.UUID(user_id) if user_id else None
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT content FROM ai_memory_items
                WHERE user_id = $1
                ORDER BY importance DESC, created_at DESC
                LIMIT $2
                """,
                uid, limit,
            )
        return [r["content"] for r in rows]
    except Exception as exc:
        log.error("memory.recall failed: %s", exc)
        return []


async def build_memory_context(pool, *, user_id: Optional[str]) -> str:
    """Build a system context string from long-term memory items."""
    items = await recall(pool, user_id=user_id)
    if not items:
        return ""
    lines = "\n".join(f"- {item}" for item in items)
    return f"[Memory context]\n{lines}"
