"""
ContextManager — assembles a rich context bundle for every AI request.

Merges: conversation history, user memories, project/workspace metadata,
        compressed summaries when token budget is tight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


_SYSTEM_SEPARATOR = "\n\n---\n\n"
_TOKEN_BUDGET = 4000   # tokens reserved for injected context


@dataclass
class ContextBundle:
    """Assembled context ready for injection into a prompt."""
    system_prefix:    str            = ""
    history:          list[dict]     = field(default_factory=list)
    memories:         list[str]      = field(default_factory=list)
    project_meta:     dict[str, Any] = field(default_factory=dict)
    token_estimate:   int            = 0

    def inject(self, user_prompt: str) -> str:
        """Prepend context sections to the user prompt."""
        parts: list[str] = []
        if self.memories:
            parts.append("## Relevant memories\n" + "\n".join(f"- {m}" for m in self.memories))
        if self.project_meta:
            meta_lines = [f"- {k}: {v}" for k, v in self.project_meta.items()]
            parts.append("## Project context\n" + "\n".join(meta_lines))
        if parts:
            return _SYSTEM_SEPARATOR.join(parts) + _SYSTEM_SEPARATOR + user_prompt
        return user_prompt


class ContextManager:
    """
    Builds ContextBundle for a given request, respecting token budgets.

    Pool is optional — falls back to empty context if unavailable.
    """

    def __init__(self, pool: Optional["asyncpg.Pool"] = None) -> None:
        self._pool = pool

    def init(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    async def build(
        self,
        user_id:         Optional[str] = None,
        conversation_id: Optional[str] = None,
        project_id:      Optional[str] = None,
        token_budget:    int           = _TOKEN_BUDGET,
    ) -> ContextBundle:
        bundle = ContextBundle()

        if not self._pool:
            return bundle

        # Load memories (importance > 0.5, most recent first)
        if user_id:
            bundle.memories = await self._load_memories(user_id, token_budget // 3)

        # Load conversation history (last N messages within budget)
        if conversation_id:
            bundle.history = await self._load_history(conversation_id, token_budget // 3)

        # Load project metadata
        if project_id:
            bundle.project_meta = await self._load_project(project_id)

        bundle.token_estimate = self._estimate_tokens(bundle)
        return bundle

    async def compress_history(
        self,
        conversation_id: str,
        keep_last: int = 10,
    ) -> str:
        """Return a bullet-point summary of messages beyond keep_last."""
        if not self._pool:
            return ""
        rows = await self._pool.fetch(
            """
            SELECT role, content FROM ai_messages
            WHERE conversation_id = $1
            ORDER BY created_at
            LIMIT 100
            """,
            conversation_id,
        )
        messages = [dict(r) for r in rows]
        if len(messages) <= keep_last:
            return ""
        to_compress = messages[:-keep_last]
        lines = [f"- [{m['role']}]: {str(m['content'])[:100]}" for m in to_compress]
        return "Earlier conversation summary:\n" + "\n".join(lines)

    # ── Internals ──────────────────────────────────────────────────────────────

    async def _load_memories(self, user_id: str, budget: int) -> list[str]:
        try:
            rows = await self._pool.fetch(   # type: ignore[union-attr]
                """
                SELECT content FROM ai_memory_items
                WHERE owner_id = $1 AND importance >= 0.5
                ORDER BY importance DESC, created_at DESC
                LIMIT 20
                """,
                user_id,
            )
            memories: list[str] = []
            used = 0
            for row in rows:
                text = str(row["content"])
                est = len(text) // 4
                if used + est > budget:
                    break
                memories.append(text)
                used += est
            return memories
        except Exception:
            return []

    async def _load_history(self, conversation_id: str, budget: int) -> list[dict]:
        try:
            rows = await self._pool.fetch(   # type: ignore[union-attr]
                """
                SELECT role, content FROM ai_messages
                WHERE conversation_id = $1
                ORDER BY created_at DESC
                LIMIT 30
                """,
                conversation_id,
            )
            history: list[dict] = []
            used = 0
            for row in reversed(rows):
                text = str(row["content"])
                est = len(text) // 4
                if used + est > budget:
                    break
                history.append({"role": row["role"], "content": text})
                used += est
            return history
        except Exception:
            return []

    async def _load_project(self, project_id: str) -> dict[str, Any]:
        try:
            row = await self._pool.fetchrow(   # type: ignore[union-attr]
                "SELECT name, description FROM projects WHERE id = $1",
                project_id,
            )
            if row:
                return {"project": row["name"], "description": row["description"] or ""}
        except Exception:
            pass
        return {}

    def _estimate_tokens(self, bundle: ContextBundle) -> int:
        total = sum(len(m) for m in bundle.memories) // 4
        total += sum(len(str(h.get("content", ""))) for h in bundle.history) // 4
        return total
