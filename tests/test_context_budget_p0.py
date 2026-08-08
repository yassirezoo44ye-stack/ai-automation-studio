"""
P0 — Context Budgeting Foundation.

app/core/ai/context/manager.py::budget_history()/ContextBudgetError, wired
into chat.py::run_stream and agents.py::agent_chat_stream — the two live
chat surfaces that previously sent the *entire*, unbounded conversation
history to the LLM on every request with no token budget check.

Re-implemented against current main's actual architecture (InferenceEngine-
based chat.py/agents.py, not the AIGateway/ContextManager.build() path —
see this file's own docstrings for why those are separate systems here),
using the already-existing app.core.ai.utils.tokens estimator and
app.core.ai.models.catalog model catalog. No new Context Compiler, no new
budgeting logic beyond this function, no router/schema/UI changes.

AIGateway._enrich() is explicitly OUT of scope here (P1, separate task) —
these tests import nothing from app.ai.gateway.
"""
from __future__ import annotations

import unittest
import unittest.mock
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.ai.context.manager import ContextBudgetError, budget_history
from app.core.ai.models.catalog import catalog

_MODEL = "claude-sonnet-4-6"
_WINDOW = catalog.get(_MODEL).context_window  # 200_000 at time of writing


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


class TestBudgetHistoryFastPath(unittest.TestCase):
    """Requirement 7/8: short/in-budget requests are returned unchanged —
    no unnecessary trimming cost, no behavior change."""

    def test_short_history_returned_unchanged_same_object(self):
        messages = [_msg("user", "hi"), _msg("assistant", "hello"), _msg("user", "how are you?")]
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        self.assertIs(result, messages)

    def test_empty_history_returned_unchanged(self):
        self.assertEqual(budget_history([], model=_MODEL), [])


class TestBudgetHistoryTrimsLongHistory(unittest.TestCase):
    """Requirements 1/2/4/5: overflow is trimmed deterministically, the
    context window is never exceeded, the current turn always survives,
    nothing is silently dropped without either being kept or summarized."""

    def _huge_history(self, n: int = 400) -> list[dict]:
        # ~400 turns * ~3000 chars ~= 300k estimated tokens, comfortably
        # over the ~178k budget a 200k-token window leaves after the 0.9
        # safety margin + max_tokens reservation fits_context() applies.
        history = []
        for i in range(n):
            history.append(_msg("user" if i % 2 == 0 else "assistant", f"turn {i}: " + ("x" * 3000)))
        history.append(_msg("user", "what's my final question?"))
        return history

    def test_long_history_is_trimmed_and_fits(self):
        from app.core.ai.utils.tokens import estimate_messages_tokens, fits_context

        history = self._huge_history()
        original_tokens = estimate_messages_tokens(history)
        self.assertFalse(
            fits_context(original_tokens, context_window=_WINDOW, max_output=2048),
            "test fixture must actually overflow the window to exercise trimming",
        )

        result = budget_history(history, model=_MODEL, max_tokens=2048)
        result_tokens = estimate_messages_tokens(result)
        self.assertTrue(fits_context(result_tokens, context_window=_WINDOW, max_output=2048))

    def test_current_turn_is_never_dropped_or_altered(self):
        history = self._huge_history()
        current = history[-1]
        result = budget_history(history, model=_MODEL, max_tokens=2048)
        self.assertEqual(result[-1], current)

    def test_trimming_is_deterministic(self):
        history = self._huge_history()
        result_a = budget_history(list(history), model=_MODEL, max_tokens=2048)
        result_b = budget_history(list(history), model=_MODEL, max_tokens=2048)
        self.assertEqual(result_a, result_b)

    def test_trimmed_result_is_shorter_than_original(self):
        history = self._huge_history()
        result = budget_history(history, model=_MODEL, max_tokens=2048)
        self.assertLess(len(result), len(history))


class TestBudgetHistoryModelSpecificWindow(unittest.TestCase):
    """Requirement 3 (partial) + explicit ask: context window differs by
    request.model, resolved from the real model catalog — not hardcoded."""

    def test_small_window_model_trims_more_aggressively_than_large_window_model(self):
        # A history sized to fit a 200k-window model unchanged, but not a
        # much smaller one.
        history = [_msg("user", "x" * 4000) for _ in range(20)] + [_msg("user", "final")]

        big_model = "claude-sonnet-4-6"          # 200_000
        small_model_info = min(catalog.all(), key=lambda m: m.context_window)
        small_model = small_model_info.id
        self.assertLess(small_model_info.context_window, catalog.get(big_model).context_window)

        result_big = budget_history(history, model=big_model, max_tokens=1024)
        result_small = budget_history(history, model=small_model, max_tokens=1024)

        self.assertIs(result_big, history)  # fits the large window untouched
        self.assertLessEqual(len(result_small), len(result_big))

    def test_unknown_model_id_falls_back_to_conservative_default_without_crashing(self):
        result = budget_history([_msg("user", "hi")], model="some-model-not-in-catalog")
        self.assertEqual(result, [_msg("user", "hi")])


class TestBudgetHistorySystemContext(unittest.TestCase):
    """Requirement 3: system/prompt content is counted, not ignored."""

    def test_large_system_prompt_forces_trimming_that_would_not_otherwise_happen(self):
        from app.core.ai.utils.tokens import estimate_messages_tokens, fits_context

        history = [_msg("user", "x" * 500) for _ in range(50)] + [_msg("user", "final")]
        # Without a system prompt this history fits the 200k window
        # unchanged — confirms the fixture itself isn't already overflowing.
        self.assertTrue(fits_context(
            estimate_messages_tokens(history), context_window=_WINDOW, max_output=2048,
        ))
        self.assertIs(budget_history(history, model=_MODEL, max_tokens=2048), history)

        # A system prompt large enough to eat into the same budget must
        # force trimming of the otherwise-untouched history — proving
        # system content is actually counted, not ignored.
        large_system = "S" * 700_000
        result = budget_history(history, model=_MODEL, max_tokens=2048, system=large_system)
        self.assertLess(len(result), len(history))
        self.assertEqual(result[-1], history[-1])

    def test_system_plus_current_turn_that_overflows_raises(self):
        history = [_msg("user", "final question")]
        with self.assertRaises(ContextBudgetError):
            budget_history(history, model=_MODEL, max_tokens=2048, system="S" * 1_000_000)


class TestBudgetHistoryImpossibleOverflow(unittest.TestCase):
    """Requirement 6: unresolvable overflow (system + current turn alone
    don't fit) raises a deterministic ContextBudgetError, never a silent
    truncation of the current turn."""

    def test_oversized_current_turn_alone_raises(self):
        with self.assertRaises(ContextBudgetError) as cm:
            budget_history([_msg("user", "x" * 5_000_000)], model=_MODEL, max_tokens=2048)
        self.assertGreater(cm.exception.required_tokens, cm.exception.context_window)

    def test_oversized_system_alone_raises(self):
        with self.assertRaises(ContextBudgetError):
            budget_history(
                [_msg("user", "hi")], model=_MODEL, max_tokens=2048, system="S" * 5_000_000,
            )

    def test_error_message_is_informative(self):
        try:
            budget_history([_msg("user", "x" * 5_000_000)], model=_MODEL, max_tokens=2048)
            self.fail("expected ContextBudgetError")
        except ContextBudgetError as e:
            self.assertIn(_MODEL, str(e))
            self.assertIn("context window", str(e))


# ── Integration: chat.py / agents.py actually call budget_history() ────────

def _fake_pool():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=uuid.uuid4())
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="OK")
    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = conn_cm
    return pool, conn


class _StreamChunks:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            yield c


class TestChatRunStreamUsesBudgetHistory(unittest.IsolatedAsyncioTestCase):
    async def test_long_stored_history_is_trimmed_before_reaching_the_engine(self):
        """Integration proof budget_history() is actually wired into
        run_stream's request construction: RunRequest.prompt is capped at
        4000 chars (Field max_length), so the current turn alone can never
        trigger ContextBudgetError through this router — the real overflow
        scenario here is a long *stored* conversation history, loaded from
        the messages table via conversation_id. The engine must still be
        called (request succeeds), but with a trimmed message list, not
        the full 300-row history."""
        from app.routers import chat as chat_mod

        pool, conn = _fake_pool()
        conv_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=1)  # ownership check: owned
        conn.fetch = AsyncMock(return_value=[
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}: " + ("x" * 3000)}
            for i in range(300)
        ])
        req = chat_mod.RunRequest(project_id="demo", prompt="what's my final question?",
                                   conversation_id=str(conv_id))
        chunks = [{"type": "delta", "text": "answer"}, {"type": "done"}]
        with unittest.mock.patch.object(
            chat_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks(chunks),
        ) as mock_stream:
            resp = await chat_mod.run_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"type": "done"', joined)
        self.assertNotIn('"type": "error"', joined)
        mock_stream.assert_called_once()
        sent_messages = mock_stream.call_args.args[0].messages
        # 300 history rows + 1 current turn = 301 raw; must be trimmed.
        self.assertLess(len(sent_messages), 301)
        self.assertEqual(sent_messages[-1].content, "what's my final question?")

    async def test_short_prompt_still_calls_engine_with_unmodified_history(self):
        """The fast path must not change existing short-conversation
        behavior: the same 'delta'/'done' SSE sequence as before this
        change, engine.stream() still called."""
        from app.routers import chat as chat_mod

        pool, conn = _fake_pool()
        req = chat_mod.RunRequest(project_id="demo", prompt="hi")
        chunks = [{"type": "delta", "text": "hello"}, {"type": "done"}]
        with unittest.mock.patch.object(
            chat_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks(chunks),
        ) as mock_stream:
            resp = await chat_mod.run_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"type": "delta", "text": "hello"', joined)
        self.assertIn('"type": "done"', joined)
        mock_stream.assert_called_once()


class TestAgentsChatStreamUsesBudgetHistory(unittest.IsolatedAsyncioTestCase):
    async def test_context_budget_error_surfaces_as_clean_sse_error(self):
        from app.routers import agents as agents_mod

        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=uuid.uuid4())
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value="OK")
        conn.fetchrow = AsyncMock(return_value={
            "id": uuid.uuid4(), "model": "claude-sonnet-4-6", "system_prompt": "S" * 5_000_000,
        })
        conn_cm = MagicMock()
        conn_cm.__aenter__ = AsyncMock(return_value=conn)
        conn_cm.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = conn_cm

        req = agents_mod.AgentChatRequest(agent_id="agent-1", project_id="demo", prompt="hi")
        with unittest.mock.patch.object(
            agents_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            agents_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            agents_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            agents_mod, "ensure_agents_table", AsyncMock(),
        ), unittest.mock.patch.object(
            agents_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            agents_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
        ) as mock_stream:
            resp = await agents_mod.agent_chat_stream(str(uuid.uuid4()), req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"type": "error"', joined)
        # SSE error shape must stay identical to the pre-existing
        # provider-error contract (same frame prefix/suffix, same keys) —
        # no new HTTP/SSE behavior invented for this failure mode.
        self.assertTrue(joined.startswith('data: {"type": "conv_id"'))
        self.assertIn('data: {"type": "error", "message":', joined)
        self.assertTrue(joined.rstrip().endswith("}"))
        mock_stream.assert_not_called()


# ── Explicit invariant verification (post-P0-implementation review) ────────
#
# fits_context(tokens, context_window=..., max_output=...) == True must hold
# for budget_history()'s result in every *solvable* case; every unsolvable
# case must raise ContextBudgetError before any provider call.

def _result_tokens(result: list[dict], system: "str | None") -> int:
    from app.core.ai.utils.tokens import estimate_messages_tokens, estimate_tokens
    return (estimate_tokens(system) if system else 0) + estimate_messages_tokens(result)


def _assert_fits(test: unittest.TestCase, result, *, system, context_window, max_tokens):
    from app.core.ai.utils.tokens import fits_context
    tokens = _result_tokens(result, system)
    test.assertTrue(
        fits_context(tokens, context_window=context_window, max_output=max_tokens),
        f"budget_history() result ({tokens} tokens) does not fit context_window="
        f"{context_window} with max_output={max_tokens}",
    )


class TestContextBudgetInvariant(unittest.TestCase):
    """budget_history()'s core invariant, exercised across every scenario
    class named in the review request. Each case that doesn't raise must
    leave a result that provably fits; each impossible case must raise
    ContextBudgetError and never return a result at all."""

    def _small_and_large_models(self):
        small = min(catalog.all(), key=lambda m: m.context_window)
        large = catalog.get(_MODEL)
        return small, large

    def test_short_history(self):
        messages = [_msg("user", "hi"), _msg("assistant", "hello"), _msg("user", "how are you?")]
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        _assert_fits(self, result, system=None, context_window=_WINDOW, max_tokens=2048)

    def test_long_history(self):
        messages = [_msg("user", f"turn {i}: " + ("x" * 3000)) for i in range(400)]
        messages.append(_msg("user", "final"))
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        _assert_fits(self, result, system=None, context_window=_WINDOW, max_tokens=2048)

    def test_long_system_prompt(self):
        messages = [_msg("user", "hi"), _msg("user", "final")]
        system = "S" * 300_000
        result = budget_history(messages, model=_MODEL, max_tokens=2048, system=system)
        _assert_fits(self, result, system=system, context_window=_WINDOW, max_tokens=2048)

    def test_long_current_message_alone_still_fits(self):
        # Large but not impossible: comfortably under the window on its own.
        messages = [_msg("user", "x" * 400_000)]
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        _assert_fits(self, result, system=None, context_window=_WINDOW, max_tokens=2048)

    def test_long_history_plus_system_plus_current(self):
        messages = [_msg("user", f"turn {i}: " + ("x" * 2000)) for i in range(200)]
        messages.append(_msg("user", "x" * 50_000))  # long current message too
        system = "S" * 150_000
        result = budget_history(messages, model=_MODEL, max_tokens=2048, system=system)
        _assert_fits(self, result, system=system, context_window=_WINDOW, max_tokens=2048)
        self.assertEqual(result[-1], messages[-1])

    def test_small_context_window_model(self):
        small, _ = self._small_and_large_models()
        messages = [_msg("user", f"turn {i}: " + ("x" * 1000)) for i in range(100)]
        messages.append(_msg("user", "final"))
        result = budget_history(messages, model=small.id, max_tokens=512)
        _assert_fits(self, result, system=None, context_window=small.context_window, max_tokens=512)

    def test_large_context_window_model(self):
        _, large = self._small_and_large_models()
        messages = [_msg("user", f"turn {i}: " + ("x" * 3000)) for i in range(400)]
        messages.append(_msg("user", "final"))
        result = budget_history(messages, model=large.id, max_tokens=2048)
        _assert_fits(self, result, system=None, context_window=large.context_window, max_tokens=2048)

    def test_history_needing_severe_trimming(self):
        messages = [_msg("user", f"turn {i}: " + ("x" * 4000)) for i in range(600)]
        messages.append(_msg("user", "final"))
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        _assert_fits(self, result, system=None, context_window=_WINDOW, max_tokens=2048)
        self.assertLess(len(result), len(messages) // 2, "this fixture should trim severely")
        self.assertEqual(result[-1], messages[-1])

    def test_history_needing_fallback_to_current_message_only(self):
        # A history with enough *messages* that even the fully-summarized
        # version (capped at ~200 chars/message, so message *count* drives
        # summary size here, not per-message length) doesn't fit in the
        # small headroom left after a very large system prompt — forces
        # the [current]-only fallback.
        messages = [_msg("user", f"turn {i}") for i in range(2000)]
        messages.append(_msg("user", "final question"))
        system = "S" * 700_000
        result = budget_history(messages, model=_MODEL, max_tokens=2048, system=system)
        _assert_fits(self, result, system=system, context_window=_WINDOW, max_tokens=2048)
        self.assertEqual(result, [messages[-1]])

    def test_impossible_case_raises_and_returns_nothing(self):
        """system + current message + required output cannot fit at all —
        must raise, and the caller must never see a return value."""
        messages = [_msg("user", "final")]
        system = "S" * 5_000_000
        with self.assertRaises(ContextBudgetError):
            budget_history(messages, model=_MODEL, max_tokens=2048, system=system)


class TestMaxTokensConsistency(unittest.TestCase):
    """The max_tokens passed into budget_history() must be the exact same
    value later sent to InferenceEngine — a silent mismatch would mean the
    budget check reserves a different output allowance than what's
    actually requested from the provider."""

    def test_chat_py_budget_and_request_max_tokens_match(self):
        import inspect
        from app.routers import chat as chat_mod
        src = inspect.getsource(chat_mod.run_stream)
        # Both call sites in the same function body — extract the literal
        # max_tokens= arguments and compare them directly.
        import re
        values = re.findall(r"max_tokens=(\d+)", src)
        self.assertGreaterEqual(len(values), 2, "expected budget_history() and CompletionRequest() calls")
        self.assertEqual(values[0], values[1],
                          f"budget_history() used max_tokens={values[0]} but CompletionRequest used {values[1]}")

    def test_agents_py_budget_and_request_max_tokens_match(self):
        import inspect
        import re
        from app.routers import agents as agents_mod
        src = inspect.getsource(agents_mod.agent_chat_stream)
        values = re.findall(r"max_tokens=(\d+)", src)
        self.assertGreaterEqual(len(values), 2)
        self.assertEqual(values[0], values[1],
                          f"budget_history() used max_tokens={values[0]} but CompletionRequest used {values[1]}")


class TestCurrentMessagePreservationUnderEveryTrimPath(unittest.TestCase):
    """The current (last) message must survive unchanged, whether the
    result is: unchanged (fast path), lightly trimmed, severely trimmed,
    or the full [current]-only fallback."""

    def test_preserved_in_fast_path(self):
        messages = [_msg("user", "hi"), _msg("user", "final")]
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        self.assertEqual(result[-1], messages[-1])

    def test_preserved_under_light_trimming(self):
        messages = [_msg("user", f"turn {i}: " + ("x" * 3000)) for i in range(350)]
        messages.append(_msg("user", "final"))
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        self.assertEqual(result[-1], messages[-1])

    def test_preserved_under_severe_trimming(self):
        messages = [_msg("user", f"turn {i}: " + ("x" * 4000)) for i in range(600)]
        messages.append(_msg("user", "final"))
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        self.assertEqual(result[-1], messages[-1])

    def test_preserved_when_falling_back_to_current_only(self):
        messages = [_msg("user", f"turn {i}") for i in range(2000)]
        messages.append(_msg("user", "final question"))
        result = budget_history(messages, model=_MODEL, max_tokens=2048, system="S" * 700_000)
        self.assertEqual(result, [messages[-1]])


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_produce_identical_output_across_two_calls(self):
        messages = [_msg("user", f"turn {i}: " + ("x" * 3000)) for i in range(350)]
        messages.append(_msg("user", "final"))
        system = "S" * 10_000

        result_a = budget_history(list(messages), model=_MODEL, max_tokens=2048, system=system)
        result_b = budget_history(list(messages), model=_MODEL, max_tokens=2048, system=system)

        self.assertEqual(result_a, result_b)
        self.assertEqual([m["content"] for m in result_a], [m["content"] for m in result_b])


class TestPerformanceSanity(unittest.TestCase):
    """No benchmark framework — just confirm the two documented cost
    properties: the fast path performs zero trimming work (proven by
    object identity, not timing), and a normal-sized conversation
    (40-100 turns) stays on the fast path rather than paying any
    summarization cost."""

    def test_fast_path_does_no_trimming_work_proven_by_identity(self):
        messages = [_msg("user", "hi"), _msg("assistant", "hello")]
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        self.assertIs(result, messages)

    def test_normal_sized_conversation_stays_on_fast_path(self):
        # 80 short, realistic-length turns - well within a 200k window.
        messages = [_msg("user" if i % 2 == 0 else "assistant", f"message number {i}") for i in range(80)]
        result = budget_history(messages, model=_MODEL, max_tokens=2048)
        self.assertIs(result, messages)


if __name__ == "__main__":
    unittest.main()
