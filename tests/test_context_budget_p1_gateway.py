"""
P1 — Context Budgeting in AIGateway._enrich().

Wires the same budget_history() built for P0 (chat.py/agents.py, see
tests/test_context_budget_p0.py) into app/ai/gateway.py::AIGateway._enrich()
— the entry point InferenceEngine.complete()/stream() call directly (see
app/core/ai/inference/engine.py), and therefore every consumer that
delegates to InferenceEngine: /api/ai/complete, /api/ai/stream
(app/routers/inference.py), and — verified against current main, not
assumed — chat.py/agents.py themselves (which already pre-budget in P0;
this is a redundant, harmless second fast-path check for them, not a new
behavior).

No new budgeting algorithm here — budget_history()/ContextBudgetError are
unchanged from P0. This file tests the *integration* (the Message<->dict
adapter, the Decision Gate's propagation-without-new-handling), not the
algorithm itself (already covered by test_context_budget_p0.py).

The pinned regression test (test_gateway_enrich_appends_framed_context_to_system,
tests/security/test_prompt_injection.py) is run alongside this file's
suite in CI/verification but intentionally not duplicated here — it
already proves _enrich()'s existing behavior is undisturbed.
"""
from __future__ import annotations

import unittest
import unittest.mock
from unittest.mock import AsyncMock, patch

from app.ai.gateway import AIGateway
from app.ai.models import CompletionRequest, Message
from app.core.ai.context.manager import ContextBudgetError
from app.core.ai.models.catalog import catalog

_MODEL = "claude-sonnet-4-6"
_WINDOW = catalog.get(_MODEL).context_window


def _gw() -> AIGateway:
    return AIGateway(pool=object())


class TestEnrichShortHistoryUnchanged(unittest.IsolatedAsyncioTestCase):
    """1/2: short history through _enrich() -> fast path, no trimming."""

    async def test_short_messages_pass_through_unchanged(self):
        gw = _gw()
        req = CompletionRequest(
            messages=[Message(role="user", content="hi"), Message(role="assistant", content="hello")],
            model=_MODEL,
        )
        enriched = await gw._enrich(req, user_id=None)

        self.assertEqual(len(enriched.messages), 2)
        self.assertEqual(enriched.messages[0].content, "hi")
        self.assertEqual(enriched.messages[1].content, "hello")

    async def test_fast_path_does_no_trimming_for_a_realistic_conversation(self):
        gw = _gw()
        messages = [
            Message(role="user" if i % 2 == 0 else "assistant", content=f"message {i}")
            for i in range(60)
        ]
        req = CompletionRequest(messages=messages, model=_MODEL)
        enriched = await gw._enrich(req, user_id=None)

        self.assertEqual(len(enriched.messages), 60)
        self.assertEqual(enriched.messages[-1].content, "message 59")


class TestEnrichLongHistoryIsBudgeted(unittest.IsolatedAsyncioTestCase):
    """3: a long message list is actually trimmed by _enrich()."""

    async def test_long_history_is_trimmed_and_fits(self):
        from app.core.ai.utils.tokens import estimate_messages_tokens, fits_context

        gw = _gw()
        messages = [Message(role="user", content=f"turn {i}: " + ("x" * 3000)) for i in range(400)]
        messages.append(Message(role="user", content="final question"))
        req = CompletionRequest(messages=messages, model=_MODEL, max_tokens=2048)

        enriched = await gw._enrich(req, user_id=None)

        self.assertLess(len(enriched.messages), len(messages))
        result_dicts = [{"role": m.role, "content": m.content} for m in enriched.messages]
        tokens = estimate_messages_tokens(result_dicts)
        self.assertTrue(fits_context(tokens, context_window=_WINDOW, max_output=2048))


class TestEnrichCurrentMessagePreserved(unittest.IsolatedAsyncioTestCase):
    """4: the current (last) message survives every trim path."""

    async def test_current_message_preserved_under_trimming(self):
        gw = _gw()
        messages = [Message(role="user", content=f"turn {i}: " + ("x" * 3000)) for i in range(400)]
        messages.append(Message(role="user", content="the actual question"))
        req = CompletionRequest(messages=messages, model=_MODEL, max_tokens=2048)

        enriched = await gw._enrich(req, user_id=None)

        self.assertEqual(enriched.messages[-1].content, "the actual question")


class TestEnrichSystemContextCounted(unittest.IsolatedAsyncioTestCase):
    """5: system content (including memory-injected content from step 3
    of _enrich(), not just the caller's own request.system) is counted."""

    async def test_large_system_forces_trimming_of_otherwise_untouched_history(self):
        gw = _gw()
        messages = [Message(role="user", content="x" * 500) for _ in range(50)]
        messages.append(Message(role="user", content="final"))
        req = CompletionRequest(
            messages=messages, model=_MODEL, max_tokens=2048, system="S" * 700_000,
        )

        enriched = await gw._enrich(req, user_id=None)

        self.assertLess(len(enriched.messages), len(messages))
        self.assertEqual(enriched.messages[-1].content, "final")

    async def test_memory_injected_system_content_is_also_counted(self):
        """Step 3 (long-term memory injection) runs BEFORE step 4
        (budgeting) inside _enrich() — memory-injected system content
        must count toward the same budget, not bypass it."""
        from app.ai import memory as mem

        gw = _gw()
        messages = [Message(role="user", content="x" * 500) for _ in range(50)]
        messages.append(Message(role="user", content="final"))
        req = CompletionRequest(
            messages=messages, model=_MODEL, max_tokens=2048, memory_enabled=True,
        )
        with patch.object(mem, "load_history", new=AsyncMock(return_value=[])), \
             patch.object(mem, "recall", new=AsyncMock(return_value=["x" * 700_000])):
            enriched = await gw._enrich(req, user_id="u1")

        self.assertLess(len(enriched.messages), len(messages))
        self.assertEqual(enriched.messages[-1].content, "final")


class TestEnrichModelSpecificWindow(unittest.IsolatedAsyncioTestCase):
    """6: context window comes from the real model catalog via
    request.model, not a hardcoded value."""

    async def test_small_window_model_trims_more_than_large_window_model(self):
        small = min(catalog.all(), key=lambda m: m.context_window)
        messages = [Message(role="user", content="x" * 4000) for _ in range(20)]
        messages.append(Message(role="user", content="final"))

        req_big = CompletionRequest(messages=list(messages), model=_MODEL, max_tokens=1024)
        req_small = CompletionRequest(messages=list(messages), model=small.id, max_tokens=1024)

        enriched_big = await _gw()._enrich(req_big, user_id=None)
        enriched_small = await _gw()._enrich(req_small, user_id=None)

        self.assertEqual(len(enriched_big.messages), len(messages))  # fits the 200k window
        self.assertLessEqual(len(enriched_small.messages), len(enriched_big.messages))


class TestEnrichImpossibleOverflowRaises(unittest.IsolatedAsyncioTestCase):
    """7: unresolvable overflow raises ContextBudgetError out of _enrich()."""

    async def test_oversized_current_message_raises(self):
        gw = _gw()
        req = CompletionRequest(
            messages=[Message(role="user", content="x" * 5_000_000)], model=_MODEL, max_tokens=2048,
        )
        with self.assertRaises(ContextBudgetError):
            await gw._enrich(req, user_id=None)

    async def test_oversized_system_raises(self):
        gw = _gw()
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")], model=_MODEL, max_tokens=2048,
            system="S" * 5_000_000,
        )
        with self.assertRaises(ContextBudgetError):
            await gw._enrich(req, user_id=None)


class TestNoProviderCallOnOverflow(unittest.IsolatedAsyncioTestCase):
    """8: overflow must never reach the provider, through both
    AIGateway.complete() and .stream() (the two real entry points that
    call _enrich() before doing any provider work)."""

    async def test_complete_raises_before_any_provider_call(self):
        gw = _gw()
        req = CompletionRequest(
            messages=[Message(role="user", content="x" * 5_000_000)], model=_MODEL, max_tokens=2048,
        )
        with unittest.mock.patch(
            "app.core.ai.registry.registry.platform_registry.complete_with_events",
        ) as mock_complete:
            with self.assertRaises(ContextBudgetError):
                await gw.complete(req)
        mock_complete.assert_not_called()

    async def test_stream_raises_before_any_provider_call(self):
        gw = _gw()
        req = CompletionRequest(
            messages=[Message(role="user", content="x" * 5_000_000)], model=_MODEL, max_tokens=2048,
        )
        with unittest.mock.patch(
            "app.core.ai.registry.registry.platform_registry.stream_with_events",
        ) as mock_stream:
            with self.assertRaises(ContextBudgetError):
                async for _ in gw.stream(req):
                    pass
        mock_stream.assert_not_called()


class TestEnrichDeterministic(unittest.IsolatedAsyncioTestCase):
    """10: same inputs -> same output across two calls."""

    async def test_same_request_enriched_identically_twice(self):
        messages = [Message(role="user", content=f"turn {i}: " + ("x" * 3000)) for i in range(350)]
        messages.append(Message(role="user", content="final"))

        req_a = CompletionRequest(messages=list(messages), model=_MODEL, max_tokens=2048, system="S" * 10_000)
        req_b = CompletionRequest(messages=list(messages), model=_MODEL, max_tokens=2048, system="S" * 10_000)

        enriched_a = await _gw()._enrich(req_a, user_id=None)
        enriched_b = await _gw()._enrich(req_b, user_id=None)

        self.assertEqual(
            [m.content for m in enriched_a.messages],
            [m.content for m in enriched_b.messages],
        )


class TestMultimodalContentRoundTrips(unittest.IsolatedAsyncioTestCase):
    """The Message<->dict adapter (_message_to_dict/_dict_to_message in
    gateway.py) must not corrupt non-string content that survives
    unchanged through the fast path."""

    async def test_image_part_content_survives_fast_path_unchanged(self):
        from app.ai.models import TextPart, ImagePart

        gw = _gw()
        req = CompletionRequest(
            messages=[Message(role="user", content=[
                TextPart(text="what is this?"), ImagePart(url="https://example.com/x.png"),
            ])],
            model=_MODEL,
        )
        enriched = await gw._enrich(req, user_id=None)

        self.assertEqual(len(enriched.messages), 1)
        parts = enriched.messages[0].content
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].type, "text")
        self.assertEqual(parts[0].text, "what is this?")
        self.assertEqual(parts[1].type, "image_url")
        self.assertEqual(parts[1].url, "https://example.com/x.png")


if __name__ == "__main__":
    unittest.main()
