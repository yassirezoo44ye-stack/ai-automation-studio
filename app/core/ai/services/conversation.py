"""
ConversationService — full conversation lifecycle management.

Responsibilities:
- Create / archive / delete conversations
- Load paginated messages
- Generate titles (via AI)
- Branching (future)
- Summaries
- Message ordering

Routers delegate completely — no SQL in routers.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.core.ai.events.bus import bus
from app.core.ai.events.events import ConversationCreated, ConversationArchived

log = logging.getLogger(__name__)


@dataclass
class ConversationSummary:
    id:         str
    title:      str
    created_at: str
    updated_at: str
    archived:   bool = False
    message_count: int = 0


@dataclass
class MessageRecord:
    id:           str
    role:         str
    content:      str
    tool_call_id: Optional[str]
    created_at:   str


class ConversationService:
    """
    All conversation CRUD goes through this service.

    Usage::

        svc = ConversationService(pool)
        conv_id = await svc.create(user_id=uid, title="My chat")
        msgs    = await svc.messages(conv_id, page=1, page_size=50)
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        user_id:    Optional[str] = None,
        title:      str           = "New conversation",
        project_id: Optional[str] = None,
        agent_id:   Optional[str] = None,
    ) -> str:
        uid = uuid.UUID(user_id)    if user_id    else None
        pid = uuid.UUID(project_id) if project_id else None
        aid = uuid.UUID(agent_id)   if agent_id   else None

        async with self._pool.acquire() as conn:
            cid = await conn.fetchval(
                """
                INSERT INTO ai_conversations (user_id, project_id, agent_id, title)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                uid, pid, aid, title,
            )
        cid_str = str(cid)

        await bus.emit(ConversationCreated(
            conversation_id=cid_str,
            user_id=user_id,
            title=title,
        ))

        log.debug("ConversationService: created %s", cid_str)
        return cid_str

    # ── List ──────────────────────────────────────────────────────────────────

    async def list(
        self,
        *,
        user_id: Optional[str] = None,
        limit:   int           = 50,
        offset:  int           = 0,
        archived: bool         = False,
    ) -> list[ConversationSummary]:
        uid = uuid.UUID(user_id) if user_id else None
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT c.id, c.title, c.created_at, c.updated_at,
                           COUNT(m.id) AS message_count
                    FROM ai_conversations c
                    LEFT JOIN ai_messages m ON m.conversation_id = c.id
                    WHERE ($1::uuid IS NULL OR c.user_id = $1)
                    GROUP BY c.id
                    ORDER BY c.updated_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    uid, limit, offset,
                )
            return [
                ConversationSummary(
                    id=str(r["id"]),
                    title=r["title"],
                    created_at=r["created_at"].isoformat(),
                    updated_at=r["updated_at"].isoformat(),
                    message_count=r["message_count"],
                )
                for r in rows
            ]
        except Exception as exc:
            log.error("ConversationService.list failed: %s", exc)
            return []

    # ── Messages (paginated) ──────────────────────────────────────────────────

    async def messages(
        self,
        conversation_id: str,
        *,
        page:      int = 1,
        page_size: int = 50,
    ) -> list[MessageRecord]:
        cid    = uuid.UUID(conversation_id)
        offset = (page - 1) * page_size
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, role, content, tool_call_id, created_at
                    FROM ai_messages
                    WHERE conversation_id = $1
                    ORDER BY created_at
                    LIMIT $2 OFFSET $3
                    """,
                    cid, page_size, offset,
                )
            return [
                MessageRecord(
                    id=str(r["id"]),
                    role=r["role"],
                    content=r["content"],
                    tool_call_id=r["tool_call_id"],
                    created_at=r["created_at"].isoformat(),
                )
                for r in rows
            ]
        except Exception as exc:
            log.error("ConversationService.messages failed: %s", exc)
            return []

    # ── Archive / Delete ──────────────────────────────────────────────────────

    async def delete(self, conversation_id: str) -> None:
        cid = uuid.UUID(conversation_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM ai_conversations WHERE id = $1", cid
            )
        await bus.emit(ConversationArchived(conversation_id=conversation_id))

    # ── Title generation ──────────────────────────────────────────────────────

    async def generate_title(
        self,
        conversation_id: str,
        *,
        first_user_message: str,
        provider_id: Optional[str] = None,
    ) -> str:
        """
        Generate a short title via AI. Falls back to truncated message on error.
        """
        from app.ai.models import CompletionRequest, Message
        from app.core.ai.registry.registry import platform_registry

        try:
            req = CompletionRequest(
                messages=[
                    Message(role="user", content=first_user_message),
                ],
                system=(
                    "Generate a concise 4-6 word title for this conversation. "
                    "Return ONLY the title, no quotes, no punctuation at the end."
                ),
                max_tokens=20,
                temperature=0.3,
            )
            resp, _ = await platform_registry.complete_with_events(req)
            title = resp.content.strip().strip('"').strip("'")
            if title:
                await self._update_title(conversation_id, title)
                return title
        except Exception as exc:
            log.debug("Title generation failed: %s", exc)

        # Fallback: truncate the first message
        fallback = first_user_message[:40] + ("…" if len(first_user_message) > 40 else "")
        await self._update_title(conversation_id, fallback)
        return fallback

    async def _update_title(self, conversation_id: str, title: str) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE ai_conversations SET title=$1, updated_at=$2 WHERE id=$3",
                    title, datetime.now(timezone.utc), uuid.UUID(conversation_id),
                )
        except Exception as exc:
            log.error("ConversationService._update_title failed: %s", exc)

    # ── Summary generation ────────────────────────────────────────────────────

    async def summarize(
        self,
        conversation_id: str,
        max_messages: int = 20,
    ) -> str:
        """Generate a prose summary of the conversation using AI."""
        from app.ai.models import CompletionRequest, Message
        from app.core.ai.registry.registry import platform_registry

        msgs = await self.messages(conversation_id, page_size=max_messages)
        if not msgs:
            return ""

        transcript = "\n".join(f"{m.role}: {m.content[:300]}" for m in msgs)

        req = CompletionRequest(
            messages=[Message(role="user", content=transcript)],
            system="Summarize this conversation in 2-3 sentences. Be concise.",
            max_tokens=150,
            temperature=0.3,
        )
        try:
            resp, _ = await platform_registry.complete_with_events(req)
            return resp.content.strip()
        except Exception as exc:
            log.error("ConversationService.summarize failed: %s", exc)
            return ""
