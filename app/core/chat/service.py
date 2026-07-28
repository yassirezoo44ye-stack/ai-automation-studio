"""
ChatService — persistence + query layer for Teams/Organizations real-time
chat (chat_messages table, see app/tenancy/schema.py).

One table serves two room kinds: team_id IS NULL is the organization's
org-wide "General" room; a non-NULL team_id scopes messages to that team's
own room. Reading/posting to either room requires org membership, gated
the same way team rosters already are elsewhere in this codebase
(require_permission("teams", "read"), i.e. any org member — team chat
follows that same org-wide-visible convention rather than inventing a
stricter per-team gate the rest of the app doesn't have). The router is
responsible for confirming a team_id actually belongs to the org before
calling into this service.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import asyncpg

MAX_BODY_LENGTH = 4000


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for key in ("id", "organization_id", "team_id", "user_id"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    for key in ("created_at", "edited_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat()
    return d


class ChatService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def create_message(
        self, *, organization_id: str, team_id: Optional[str], user_id: str, body: str,
    ) -> dict[str, Any]:
        body = body.strip()
        if not body:
            raise ValueError("message body must not be empty")
        if len(body) > MAX_BODY_LENGTH:
            raise ValueError(f"message body exceeds {MAX_BODY_LENGTH} characters")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO chat_messages (organization_id, team_id, user_id, body)
                VALUES ($1,$2,$3,$4)
                RETURNING id, organization_id, team_id, user_id, body, created_at, edited_at
                """,
                uuid.UUID(organization_id), uuid.UUID(team_id) if team_id else None,
                uuid.UUID(user_id), body,
            )
        return _row_to_dict(row)

    async def list_messages(
        self, *, organization_id: str, team_id: Optional[str],
        before: Optional[str] = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        clauses = ["cm.organization_id=$1", "cm.deleted_at IS NULL"]
        params: list[Any] = [uuid.UUID(organization_id)]

        if team_id:
            params.append(uuid.UUID(team_id))
            clauses.append(f"cm.team_id=${len(params)}")
        else:
            clauses.append("cm.team_id IS NULL")
        if before:
            params.append(uuid.UUID(before))
            clauses.append(
                f"cm.created_at < (SELECT created_at FROM chat_messages WHERE id=${len(params)})"
            )

        params.append(limit)
        query = f"""
            SELECT cm.id, cm.organization_id, cm.team_id, cm.user_id, cm.body,
                   cm.created_at, cm.edited_at, u.email, u.name, u.avatar_url
            FROM chat_messages cm
            JOIN users u ON u.id = cm.user_id
            WHERE {' AND '.join(clauses)}
            ORDER BY cm.created_at DESC
            LIMIT ${len(params)}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [_row_to_dict(r) for r in rows]

    async def delete_message(self, *, message_id: str, user_id: str) -> bool:
        """Owner-only soft delete — no moderator override in this first cut."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE chat_messages SET deleted_at=NOW() "
                "WHERE id=$1 AND user_id=$2 AND deleted_at IS NULL",
                uuid.UUID(message_id), uuid.UUID(user_id),
            )
        return result != "UPDATE 0"


# ── Singleton wiring ─────────────────────────────────────────────────────────

_service: Optional[ChatService] = None


def get_chat_service(pool: asyncpg.Pool | None = None) -> ChatService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = ChatService(pool)
    return _service
