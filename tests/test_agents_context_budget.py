"""
Context budgeting (P0) — app/routers/agents.py::agent_chat_stream.

agents.py was NOT migrated to InferenceEngine (still calls the Anthropic
SDK directly via get_ai_client(), same as before this change) — these
tests exercise budget_history() wired into that exact live path, proving:
  - short conversations are unaffected
  - a long, unbounded-from-the-DB history is never forwarded verbatim to
    the provider
  - overflow fails before the provider is ever called, and does NOT trip
    the circuit breaker (ai_circuit_report(False)) since it isn't a
    provider failure
  - the agent's system_prompt is always passed through unchanged
  - the existing ownership check (foreign conversation_id -> 404) still
    runs before any of this and is completely unaffected

DB interaction is mocked throughout, matching
tests/test_ai_gateway_migration_chat_build.py's convention.
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException


def _fake_pool(agent_row: dict, *, owned: bool = True, history_rows: list[dict] | None = None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=agent_row)
    conn.fetchval = AsyncMock(return_value=owned)
    conn.fetch = AsyncMock(return_value=history_rows or [])
    conn.execute = AsyncMock(return_value="OK")

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = conn_cm
    return pool, conn


class _FakeAnthropicStream:
    """Sync context manager matching anthropic's `ai.messages.stream(...)`
    shape: sync-iterable .text_stream, .get_final_message()."""

    def __init__(self, text_chunks: list[str]) -> None:
        self.text_stream = iter(text_chunks)
        self._input_tokens = 10
        self._output_tokens = 5

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        msg = MagicMock()
        msg.usage.input_tokens = self._input_tokens
        msg.usage.output_tokens = self._output_tokens
        return msg


def _fake_ai_client(text_chunks: list[str]):
    ai = MagicMock()
    ai.messages.stream = MagicMock(return_value=_FakeAnthropicStream(text_chunks))
    return ai


_AGENT_ROW = {
    "id": uuid.uuid4(),
    "model": "claude-sonnet-4-6",
    "system_prompt": "You are a helpful support agent. Always be concise.",
}


class TestAgentChatStreamContextBudgeting(unittest.IsolatedAsyncioTestCase):
    async def _drive(self, agents_mod, req, agent_row, history_rows, text_chunks, owned=True):
        pool, conn = _fake_pool(agent_row, owned=owned, history_rows=history_rows)
        ai = _fake_ai_client(text_chunks)
        with unittest.mock.patch.object(
            agents_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            agents_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            agents_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            agents_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            agents_mod, "ensure_agents_table", AsyncMock(),
        ), unittest.mock.patch.object(
            agents_mod, "get_ai_client", return_value=ai,
        ), unittest.mock.patch.object(
            agents_mod, "record_org_tokens", AsyncMock(),
        ):
            resp = await agents_mod.agent_chat_stream(str(_AGENT_ROW["id"]), req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]
        return events, ai

    async def test_short_conversation_history_sent_unchanged(self):
        from app.routers import agents as agents_mod

        history_rows = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello!"}]
        req = agents_mod.AgentChatRequest(
            agent_id=str(_AGENT_ROW["id"]), prompt="what can you do?",
            conversation_id=str(uuid.uuid4()),
        )
        events, ai = await self._drive(agents_mod, req, _AGENT_ROW, history_rows, ["I can help."])

        _, kwargs = ai.messages.stream.call_args
        self.assertEqual(len(kwargs["messages"]), 3)  # 2 history rows + current prompt
        self.assertEqual(kwargs["messages"][-1]["content"], "what can you do?")
        self.assertEqual(kwargs["system"], _AGENT_ROW["system_prompt"])
        self.assertIn('"type": "delta"', "".join(events))

    async def test_long_conversation_is_bounded_not_sent_verbatim(self):
        from app.routers import agents as agents_mod

        history_rows = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": ("y" * 8_000)}
            for i in range(120)
        ]
        req = agents_mod.AgentChatRequest(
            agent_id=str(_AGENT_ROW["id"]), prompt="summarize everything",
            conversation_id=str(uuid.uuid4()),
        )
        events, ai = await self._drive(agents_mod, req, _AGENT_ROW, history_rows, ["done"])

        _, kwargs = ai.messages.stream.call_args
        self.assertLess(len(kwargs["messages"]), 121)
        # Current input never lost.
        self.assertEqual(kwargs["messages"][-1]["content"], "summarize everything")
        # System/agent instructions never dropped or altered by compaction.
        self.assertEqual(kwargs["system"], _AGENT_ROW["system_prompt"])
        # Not silent — dropped turns are represented by a summary message.
        self.assertIn("summary", str(kwargs["messages"][0]["content"]).lower())

    async def test_overflow_returns_error_without_calling_the_provider_or_tripping_circuit(self):
        from app.routers import agents as agents_mod
        from app.core.ai.context.manager import ContextBudgetError

        req = agents_mod.AgentChatRequest(
            agent_id=str(_AGENT_ROW["id"]), prompt="hello",
            conversation_id=str(uuid.uuid4()),
        )
        ai = _fake_ai_client(["should never be reached"])
        pool, conn = _fake_pool(_AGENT_ROW, owned=True, history_rows=[])

        with unittest.mock.patch.object(
            agents_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            agents_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            agents_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            agents_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            agents_mod, "ensure_agents_table", AsyncMock(),
        ), unittest.mock.patch.object(
            agents_mod, "get_ai_client", return_value=ai,
        ), unittest.mock.patch.object(
            agents_mod, "budget_history",
            side_effect=ContextBudgetError(
                "system prompt + current message alone exceed the context window",
                estimated_tokens=999_999, context_window=32_000,
            ),
        ), unittest.mock.patch("app.ai.circuit_breaker.circuit_breaker.record_failure") as mock_record_failure:
            resp = await agents_mod.agent_chat_stream(str(_AGENT_ROW["id"]), req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        ai.messages.stream.assert_not_called()
        joined = "".join(events)
        self.assertIn('"type": "error"', joined)
        self.assertIn("context window", joined)
        self.assertNotIn('"type": "done"', joined)
        # Not a provider failure — must not be recorded against the
        # Anthropic circuit breaker.
        mock_record_failure.assert_not_called()

    async def test_foreign_conversation_still_404s_before_any_budgeting(self):
        """Regression guard: ownership enforcement (the existing
        cross-user isolation) is completely unaffected by this change —
        it still runs, and still short-circuits, before budget_history()
        or the provider are ever touched."""
        from app.routers import agents as agents_mod

        pool, conn = _fake_pool(_AGENT_ROW, owned=False)  # ownership check fails
        with unittest.mock.patch.object(
            agents_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            agents_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            agents_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            agents_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            agents_mod, "ensure_agents_table", AsyncMock(),
        ), unittest.mock.patch.object(
            agents_mod, "get_ai_client", return_value=_fake_ai_client(["unused"]),
        ):
            req = agents_mod.AgentChatRequest(
                agent_id=str(_AGENT_ROW["id"]), prompt="hi", conversation_id=str(uuid.uuid4()),
            )
            with self.assertRaises(HTTPException) as ctx:
                await agents_mod.agent_chat_stream(str(_AGENT_ROW["id"]), req, MagicMock())

        self.assertEqual(ctx.exception.status_code, 404)
        conn.fetch.assert_not_called()  # history was never even loaded


if __name__ == "__main__":
    unittest.main()
