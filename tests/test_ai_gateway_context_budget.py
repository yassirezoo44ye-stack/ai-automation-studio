"""
Context budgeting (P1) — app/ai/gateway.py::AIGateway._enrich() step 4.

Reuses budget_history() exactly as built in P0 (no new budgeting logic —
see docs/context-control-audit.md's P1 Decision Gate addendum). These
tests exercise _enrich() directly (no network/provider calls — _enrich()
never touches a provider, only DB-backed history/memory and now the
in-memory budget check), matching test_gateway_enrich_appends_framed_
context_to_system's existing pattern in
tests/security/test_prompt_injection.py.

Covers:
  1. short history/memory -> unchanged (fast path)
  2. long history -> budget_history() actually bounds it
  3. model-specific context window is respected (dynamic, not hardcoded)
  4. overflow -> ContextBudgetError propagates, no provider call
  5. the existing memory prompt-injection framing test is untouched
     (verified separately by re-running tests/security/test_prompt_injection.py)
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock

from app.ai.gateway import AIGateway
from app.ai.models import CompletionRequest, Message
from app.ai import memory as mem
from app.core.ai.context.manager import ContextBudgetError


def _long_history(n: int, msg_len: int = 8_000) -> list[Message]:
    return [
        Message(role="user" if i % 2 == 0 else "assistant", content=("h" * msg_len))
        for i in range(n)
    ]


class TestEnrichShortConversationUnchanged(unittest.IsolatedAsyncioTestCase):
    async def test_short_history_and_memory_pass_through_unchanged(self):
        gw = AIGateway(pool=object())
        req = CompletionRequest(
            messages=[Message(role="user", content="how are you?")],
            model="claude-sonnet-4-6",
            conversation_id="11111111-1111-1111-1111-111111111111",
            memory_enabled=True,
        )
        with unittest.mock.patch.object(
            mem, "load_history", new=AsyncMock(return_value=[
                Message(role="user", content="hello"),
                Message(role="assistant", content="hi there"),
            ]),
        ), unittest.mock.patch.object(
            mem, "recall", new=AsyncMock(return_value=["likes concise answers"]),
        ):
            enriched = await gw._enrich(req, user_id="u1")

        self.assertEqual(len(enriched.messages), 3)  # 2 history + current
        self.assertEqual(enriched.messages[-1].content, "how are you?")
        self.assertIn("likes concise answers", enriched.system)


class TestEnrichLongHistoryIsBounded(unittest.IsolatedAsyncioTestCase):
    async def test_long_history_triggers_compaction_not_unbounded_send(self):
        gw = AIGateway(pool=object())
        req = CompletionRequest(
            messages=[Message(role="user", content="what's the summary so far?")],
            model="claude-sonnet-4-6",
            conversation_id="11111111-1111-1111-1111-111111111111",
        )
        with unittest.mock.patch.object(
            mem, "load_history", new=AsyncMock(return_value=_long_history(120)),
        ):
            enriched = await gw._enrich(req, user_id="u1")

        # Never the full 120 history messages + current (121).
        self.assertLess(len(enriched.messages), 121)
        # Current input never lost.
        self.assertEqual(enriched.messages[-1].content, "what's the summary so far?")
        # Not silent — a summary message stands in for the dropped turns.
        self.assertIn("summary", str(enriched.messages[0].content).lower())


class TestEnrichRespectsPerModelContextWindow(unittest.IsolatedAsyncioTestCase):
    async def test_same_history_compacts_for_small_window_not_large_window(self):
        history = _long_history(30, msg_len=4_000)  # ~30K tokens

        async def _run(model: str):
            gw = AIGateway(pool=object())
            req = CompletionRequest(
                messages=[Message(role="user", content="go on")],
                model=model,
                conversation_id="11111111-1111-1111-1111-111111111111",
            )
            with unittest.mock.patch.object(
                mem, "load_history", new=AsyncMock(return_value=history),
            ):
                return await gw._enrich(req, user_id="u1")

        small_window = await _run("mistral-small")   # 32K window
        large_window = await _run("claude-sonnet-4-6")  # 200K window

        self.assertLess(len(small_window.messages), len(history) + 1)
        self.assertEqual(len(large_window.messages), len(history) + 1)


class TestEnrichOverflowFailsClosed(unittest.IsolatedAsyncioTestCase):
    async def test_context_budget_error_propagates_out_of_enrich(self):
        gw = AIGateway(pool=object())
        huge_current = "x" * 300_000  # ~75K tokens, alone exceeds a 32K window
        req = CompletionRequest(
            messages=[Message(role="user", content=huge_current)],
            model="mistral-small",
        )
        with self.assertRaises(ContextBudgetError):
            await gw._enrich(req, user_id="u1")

    async def test_overflow_never_reaches_the_provider_via_complete(self):
        """One level up: AIGateway.complete() must never call the provider
        registry when _enrich() fails closed."""
        gw = AIGateway(pool=object())
        huge_current = "x" * 300_000
        req = CompletionRequest(
            messages=[Message(role="user", content=huge_current)],
            model="mistral-small",
        )
        with unittest.mock.patch(
            "app.core.ai.registry.registry.platform_registry.complete_with_events",
        ) as mock_complete_with_events:
            with self.assertRaises(ContextBudgetError):
                await gw.complete(req, user_id="u1")
        mock_complete_with_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
