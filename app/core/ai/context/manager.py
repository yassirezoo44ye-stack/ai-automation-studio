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


# ═════════════════════════════════════════════════════════════════════════════
# Context budgeting for live chat (P0 — see docs/context-control-audit.md §6/§18)
# ═════════════════════════════════════════════════════════════════════════════
#
# The functions below are the "ContextBudgeter" piece from that audit's
# proposed design, scoped to exactly what P0 asked for: bound the message
# list a live chat request sends to the provider, using the token estimator
# that already exists (app/core/ai/utils/tokens.py) and the per-model context
# windows that already exist (app/core/ai/models/catalog.py) — neither of
# which had any caller before this. This is intentionally NOT the full
# Context Compiler proposed for a later phase: no Policy/Task/Memory/Tool
# sections, no new persistence, no new pipeline. It only answers "does this
# message list fit, and if not, what is the smallest, most diagnosable
# change that makes it fit without losing the system prompt or the current
# user turn?" — synchronous and DB-free by design, so it can run in-process
# against whatever history a router has already loaded (chat.py/agents.py's
# own `messages` table reads), without touching persistence or schema.

_DEFAULT_CONTEXT_WINDOW = 200_000   # fallback when the model isn't in catalog (matches Claude Sonnet/Opus's real window)
_DEFAULT_OUTPUT_RESERVE = 4_096     # fallback max_output reserve when the model isn't in catalog


class ContextBudgetError(RuntimeError):
    """Raised when no valid request can be built for this model's context
    window — i.e. the system prompt plus the current user message alone
    already exceed it. Callers must catch this and surface a clear,
    diagnosable failure (an SSE error / HTTP error) instead of sending a
    request to the provider that is guaranteed to be rejected."""

    def __init__(self, message: str, *, estimated_tokens: int, context_window: int) -> None:
        super().__init__(message)
        self.estimated_tokens = estimated_tokens
        self.context_window = context_window


@dataclass
class HistoryBudgetResult:
    """Outcome of budget_history() — the (possibly trimmed) message list to
    actually send, plus enough detail to log/diagnose what happened."""
    messages:        list[dict]
    estimated_tokens: int
    context_window:  int
    dropped_count:   int  = 0      # number of original prior-turn messages removed from the list sent
    compacted:       bool = False  # True if a summary message replaced the dropped ones
    truncated:       bool = False  # True if messages were dropped with no summary substitute (last resort)


def _summarize_dropped(messages: list[dict]) -> str:
    """Extractive, deterministic summary of messages being dropped from the
    live request — same bullet-point/100-char-preview style as
    ContextManager.compress_history() above, applied to an in-memory list
    instead of an `ai_messages` DB query (chat.py/agents.py's history lives
    in the older `messages` table — see docs/context-control-audit.md §2.3/
    F4 — so the DB-querying compress_history() can't be called directly
    here; this reuses its exact formatting convention rather than
    inventing a new one)."""
    lines = [f"- [{m.get('role', '?')}]: {str(m.get('content', ''))[:100]}" for m in messages]
    return (
        "Earlier conversation summary (older turns condensed to fit this "
        "model's context window):\n" + "\n".join(lines)
    )


def budget_history(
    history: list[dict],
    *,
    model: Optional[str],
    system: str = "",
    max_output: Optional[int] = None,
) -> HistoryBudgetResult:
    """
    Bound `history` (oldest → newest, with the current user turn already
    appended as the LAST element — chat.py/agents.py's existing convention)
    so it fits inside `model`'s real context window alongside `system`.

    Guarantees:
      - `system` and the last message in `history` (the current user input)
        are NEVER dropped or summarized — if the two of them alone don't
        fit, this raises ContextBudgetError instead of silently sending a
        doomed or truncated-current-input request.
      - When the full history already fits, it is returned unchanged (no
        behavior change for short conversations).
      - When it doesn't fit, the oldest prior turns are replaced by a single
        extractive summary message (see _summarize_dropped) — never
        silently dropped with no trace — until the remainder fits.
      - Only as a last resort (the summary itself doesn't leave enough
        room) history is truncated to just the current input, which is
        always guaranteed to fit by the floor check above.

    Uses estimate_tokens()/estimate_messages_tokens()/fits_context() from
    app/core/ai/utils/tokens.py as-is — this function only adds the
    selection policy (what to keep/drop/summarize) on top of them.
    """
    info = catalog.get(model) if model else None
    context_window = info.context_window if info else _DEFAULT_CONTEXT_WINDOW
    reserved_output = max_output if max_output is not None else (
        info.output_limit if info else _DEFAULT_OUTPUT_RESERVE
    )

    system_tokens = estimate_tokens(system) if system else 0

    if not history:
        return HistoryBudgetResult(
            messages=[], estimated_tokens=system_tokens, context_window=context_window,
        )

    current = history[-1]
    rest = history[:-1]
    current_tokens = estimate_messages_tokens([current])

    # Non-negotiable floor: system + current input must fit on their own,
    # with zero history, or no request built from this input can ever
    # succeed against this model.
    floor_tokens = system_tokens + current_tokens
    if not fits_context(floor_tokens, context_window=context_window, max_output=reserved_output):
        raise ContextBudgetError(
            f"system prompt + current message alone (~{floor_tokens} estimated tokens) "
            f"exceed the context window for model {model!r} "
            f"(window={context_window}, output_reserve={reserved_output}) — "
            "no valid request can be built for this input.",
            estimated_tokens=floor_tokens, context_window=context_window,
        )

    # Fast path: the full conversation fits verbatim — no compaction needed,
    # identical behavior to before this function existed.
    full_tokens = system_tokens + estimate_messages_tokens(rest) + current_tokens
    if fits_context(full_tokens, context_window=context_window, max_output=reserved_output):
        return HistoryBudgetResult(
            messages=history, estimated_tokens=full_tokens, context_window=context_window,
        )

    # Doesn't fit — drop the oldest prior turns one at a time, replacing them
    # with a single extractive summary message, until the remainder fits.
    # `rest` is bounded by what the caller already loaded from the DB for
    # this request, so this loop's worst case is proportional to one
    # conversation's history, not global state.
    for drop_n in range(1, len(rest) + 1):
        dropped = rest[:drop_n]
        kept = rest[drop_n:]
        summary = {"role": "user", "content": _summarize_dropped(dropped)}
        msgs = [summary] + kept + [current]
        tokens = system_tokens + estimate_messages_tokens(msgs)
        if fits_context(tokens, context_window=context_window, max_output=reserved_output):
            return HistoryBudgetResult(
                messages=msgs, estimated_tokens=tokens, context_window=context_window,
                dropped_count=drop_n, compacted=True,
            )

    # Every prior turn was summarized away and it still doesn't fit (the
    # summary text itself was too large) — drop the summary too. `current`
    # alone is guaranteed to fit by the floor check above, so this is a
    # guaranteed-safe last resort, not a silent failure: dropped_count and
    # truncated=True make exactly what happened visible to the caller/logs.
    tokens = system_tokens + current_tokens
    return HistoryBudgetResult(
        messages=[current], estimated_tokens=tokens, context_window=context_window,
        dropped_count=len(rest), compacted=False, truncated=True,
    )


def record_budget_metrics(result: HistoryBudgetResult) -> None:
    """Emit the existing MetricsRegistry hooks (app/core/observability/
    metrics.py — same API every other AI code path already uses, e.g.
    InferenceEngine's ai_request_latency_ms) for a successful budget_history()
    call. Not a new observability subsystem — just named counters/gauges/
    histograms through the mechanism that already exists. Never raises:
    observability must never break a chat request."""
    try:
        from app.core.observability.metrics import get_metrics
        m = get_metrics()
        m.histogram(
            "context_estimated_tokens",
            "Estimated input tokens for a compiled live-chat context",
        ).observe(result.estimated_tokens)
        m.gauge(
            "context_history_messages_selected",
            "Number of history messages included in the last live-chat context sent to the provider",
        ).set(len(result.messages))
        if result.compacted or result.truncated:
            m.counter(
                "context_history_compaction_total",
                "Times live-chat conversation history was compacted or truncated to fit the model's context window",
            ).inc()
    except Exception:
        pass


def record_budget_rejection(exc: ContextBudgetError) -> None:
    """Same non-breaking observability contract as record_budget_metrics(),
    for the case where no valid context could be built at all (the request
    never reaches the provider)."""
    try:
        from app.core.observability.metrics import get_metrics
        get_metrics().counter(
            "context_overflow_rejected_total",
            "Live-chat requests rejected before calling the provider because no valid context fit the model's window",
        ).inc()
    except Exception:
        pass
