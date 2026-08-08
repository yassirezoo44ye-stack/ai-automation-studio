"""
ContextManager — assembles a rich context bundle for every AI request.

Merges: conversation history, user memories, project/workspace metadata,
        compressed summaries when token budget is tight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from app.core.ai.models.catalog import catalog
from app.core.ai.utils.tokens import estimate_messages_tokens, estimate_tokens, fits_context

if TYPE_CHECKING:
    import asyncpg


_SYSTEM_SEPARATOR = "\n\n---\n\n"
_TOKEN_BUDGET = 4000   # tokens reserved for injected context

# Conservative fallback context window (tokens) for a model id the catalog
# doesn't recognize (e.g. a caller-supplied/custom model string) — smaller
# than every current catalog entry, so an unknown model degrades to more
# aggressive trimming rather than silently assuming a large window it may
# not actually have.
_DEFAULT_CONTEXT_WINDOW = 128_000


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
        if project_id and user_id:
            bundle.project_meta = await self._load_project(project_id, user_id)

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

    async def _load_project(self, project_id: str, user_id: str) -> dict[str, Any]:
        try:
            # projects has no organization_id (see app/core/db.py) — ownership
            # is user_id directly. Without this check, any caller passing an
            # arbitrary project_id would get that project's name/description
            # injected as "context" into their own AI request regardless of
            # who owns it (the same missing-ownership-JOIN bug class fixed
            # elsewhere in this codebase for conversations/tasks).
            row = await self._pool.fetchrow(   # type: ignore[union-attr]
                "SELECT name, description FROM projects WHERE id = $1 AND user_id = $2",
                project_id, user_id,
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


# ── Context budgeting (P0) ──────────────────────────────────────────────────
#
# chat.py::run_stream and agents.py::agent_chat_stream build their own
# `history: list[dict]` directly from the `messages`/`conversations` tables
# (distinct from this class's ai_conversations/ai_messages-backed
# ContextManager.build() — see chat.py's migration notes) and send the
# *entire* history to the LLM on every request with no token budget check.
# budget_history() is the fix: a pure function (no DB access, no new
# subsystem) those two routers call on their already-assembled history list
# right before constructing the provider request.

class ContextBudgetError(Exception):
    """Raised when the content a request cannot do without — the system
    prompt plus the current user turn — doesn't fit inside the model's
    context window even with zero prior history. Sending it would be
    guaranteed to fail at the provider, so it's rejected before any
    provider call is made, not after."""

    def __init__(self, message: str, *, required_tokens: int, context_window: int) -> None:
        super().__init__(message)
        self.required_tokens = required_tokens
        self.context_window = context_window


def _summarize_dropped_turns(dropped: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """One extractive bullet-point summary message standing in for a run
    of older turns — same style as ContextManager.compress_history()
    above, not a new summarization approach."""
    if not dropped:
        return None
    lines = [f"- [{m.get('role', 'user')}]: {str(m.get('content', ''))[:200]}" for m in dropped]
    return {"role": "user", "content": "Earlier conversation summary:\n" + "\n".join(lines)}


def budget_history(
    messages: list[dict[str, Any]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 2048,
    system: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Ensure `messages` (role/content dicts; the *last* element is always the
    current turn and is never dropped or summarized) fits inside `model`'s
    context window, trimming older turns deterministically when it doesn't.

    Fast path: if the estimated token count already fits, `messages` is
    returned completely unchanged — no summarization cost for the common
    case (requirement: no behavior change when already within budget).

    When it doesn't fit: the oldest prior turns are folded into a single
    extractive summary message (see `_summarize_dropped_turns`), keeping as
    many of the most-recent prior turns raw as still fit — trying
    progressively fewer raw prior turns until the remainder fits. This is
    deterministic: the same input always produces the same output, and no
    turn is ever silently dropped without either being kept verbatim or
    folded into the summary. If even a summary of every prior turn doesn't
    fit alongside `system` + the current turn, prior history is dropped
    entirely (summary included) rather than the current turn.

    Raises ContextBudgetError if `system` + the current turn *alone* (zero
    prior history) don't fit — that case has no smaller trim to fall back
    to, so failing closed here is the only option that doesn't risk a
    guaranteed-to-fail provider call.
    """
    if not messages:
        return messages

    info = catalog.get(model) if model else None
    context_window = info.context_window if info else _DEFAULT_CONTEXT_WINDOW

    system_tokens = estimate_tokens(system) if system else 0
    current = messages[-1]
    prior = messages[:-1]

    required_tokens = system_tokens + estimate_messages_tokens([current])
    if not fits_context(required_tokens, context_window=context_window, max_output=max_tokens):
        raise ContextBudgetError(
            f"Request content alone ({required_tokens} estimated tokens) exceeds "
            f"the context window ({context_window} tokens) for model "
            f"{model or '<default>'!r}, even with no prior history.",
            required_tokens=required_tokens, context_window=context_window,
        )

    total_tokens = system_tokens + estimate_messages_tokens(messages)
    if fits_context(total_tokens, context_window=context_window, max_output=max_tokens):
        return messages  # fast path — unchanged, no trimming performed

    for keep in range(len(prior), -1, -1):
        dropped = prior[: len(prior) - keep]
        kept    = prior[len(prior) - keep :]
        summary = _summarize_dropped_turns(dropped)
        candidate = ([summary] if summary else []) + kept + [current]
        candidate_tokens = system_tokens + estimate_messages_tokens(candidate)
        if fits_context(candidate_tokens, context_window=context_window, max_output=max_tokens):
            return candidate

    # Guaranteed to fit: required_tokens (system + current alone) already
    # passed the check above — this is reached only if even a summary of
    # *every* prior turn was too large on its own, so prior history is
    # dropped entirely rather than risk the current turn.
    return [current]
