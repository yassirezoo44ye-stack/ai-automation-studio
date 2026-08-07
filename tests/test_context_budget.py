"""
Context budgeting (P0) — unit tests for budget_history() and its
observability helpers, added alongside docs/context-control-audit.md.

Covers, directly against app.core.ai.context.manager (no router, no DB):
  - short conversations are unaffected (fast path, no compaction)
  - long conversations never get sent unbounded — compaction kicks in
  - overflow that can't be fixed by compaction fails BEFORE any provider
    call, with a diagnosable ContextBudgetError (not a guaranteed-to-fail
    request)
  - system prompt / current user input are never dropped or summarized
  - the budget is dynamic per model (provider-agnostic), not hardcoded to
    one context window — proven using two real catalog entries with very
    different context_window values
  - the existing MetricsRegistry hooks are used, not a new subsystem, and
    never raise
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.ai.context.manager import (
    ContextBudgetError,
    HistoryBudgetResult,
    budget_history,
    record_budget_metrics,
    record_budget_rejection,
)


def _history(n: int, msg_len: int = 200) -> list[dict]:
    """n user/assistant turns of msg_len chars each, oldest first, ending
    with the current user turn as the last element — same convention
    chat.py/agents.py already use before calling budget_history()."""
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"turn {i}: " + ("x" * msg_len)})
    return out


class TestShortConversationUnaffected(unittest.TestCase):
    """Requirement: short conversations must behave exactly as before."""

    def test_small_history_returned_unchanged(self):
        history = _history(4)
        result = budget_history(history, model="claude-sonnet-4-6", system="You are helpful.")
        self.assertEqual(result.messages, history)
        self.assertEqual(result.dropped_count, 0)
        self.assertFalse(result.compacted)
        self.assertFalse(result.truncated)

    def test_single_message_history_returned_unchanged(self):
        history = [{"role": "user", "content": "hi"}]
        result = budget_history(history, model="claude-sonnet-4-6", system="")
        self.assertEqual(result.messages, history)
        self.assertFalse(result.compacted)

    def test_empty_history_returns_empty(self):
        result = budget_history([], model="claude-sonnet-4-6", system="policy text")
        self.assertEqual(result.messages, [])
        self.assertFalse(result.compacted)


class TestCurrentInputAndSystemNeverLost(unittest.TestCase):
    """Requirements 4 and 5: current user input and system/agent
    instructions must never be silently dropped, even under heavy
    compaction."""

    def test_current_input_is_always_the_last_message_returned(self):
        history = _history(100, msg_len=8_000)  # large enough to force compaction
        current = history[-1]
        result = budget_history(history, model="claude-sonnet-4-6", system="policy")
        self.assertTrue(result.compacted or result.truncated)
        self.assertEqual(result.messages[-1], current)

    def test_current_input_survives_even_the_truncated_last_resort(self):
        # System text alone is small, but history is enormous — forces the
        # loop all the way to the "drop everything, keep current" branch
        # for a small-context-window model without making floor_tokens
        # itself exceed the budget (current message stays small).
        history = _history(400, msg_len=4_000) + [{"role": "user", "content": "what's next?"}]
        result = budget_history(history, model="mistral-small", system="short policy")
        self.assertEqual(result.messages[-1], {"role": "user", "content": "what's next?"})

    def test_system_prompt_text_is_never_injected_as_a_message(self):
        history = _history(50, msg_len=6_000)
        result = budget_history(history, model="claude-sonnet-4-6", system="SECRET_POLICY_MARKER")
        for m in result.messages:
            self.assertNotIn("SECRET_POLICY_MARKER", str(m.get("content", "")))


class TestLongConversationIsBounded(unittest.TestCase):
    """Requirements 1, 2, 6, 7: no unbounded history, real token estimation,
    compaction (not silent data loss) when it doesn't fit."""

    def test_long_history_triggers_compaction_not_unbounded_send(self):
        history = _history(120, msg_len=8_000)  # ~ far past claude-sonnet-4-6's budget
        result = budget_history(history, model="claude-sonnet-4-6", system="")
        self.assertTrue(result.compacted)
        self.assertGreater(result.dropped_count, 0)
        # Sent list must be strictly smaller than the original — never the
        # full unbounded history.
        self.assertLess(len(result.messages), len(history))
        # The dropped turns are not silently gone — a summary message
        # stands in for them (no silent data loss).
        self.assertEqual(result.messages[0]["role"], "user")
        self.assertIn("summary", str(result.messages[0]["content"]).lower())

    def test_estimated_tokens_fit_within_the_resolved_context_window(self):
        history = _history(120, msg_len=8_000)
        result = budget_history(history, model="claude-sonnet-4-6", system="")
        # Same safety-margin/output-reserve contract as fits_context() —
        # re-derive the ceiling exactly the way budget_history() does.
        from app.core.ai.models.catalog import catalog
        info = catalog.get("claude-sonnet-4-6")
        ceiling = int(info.context_window * 0.9) - info.output_limit
        self.assertLessEqual(result.estimated_tokens, ceiling)

    def test_moderately_long_history_fits_verbatim_under_a_large_window(self):
        """Sanity check the fast path really is a fast path: history that's
        long by everyday standards but nowhere near 200K tokens must NOT be
        compacted for a large-context model."""
        history = _history(30, msg_len=500)
        result = budget_history(history, model="claude-sonnet-4-6", system="")
        self.assertFalse(result.compacted)
        self.assertEqual(result.messages, history)


class TestContextOverflowFailsBeforeProviderCall(unittest.TestCase):
    """Requirement 8: if no valid context can be built, fail clearly and
    diagnosably instead of sending a request guaranteed to be rejected."""

    def test_current_message_alone_too_large_raises_context_budget_error(self):
        huge_current = {"role": "user", "content": "x" * 300_000}  # ~75K tokens
        history = [huge_current]
        with self.assertRaises(ContextBudgetError) as ctx:
            budget_history(history, model="mistral-small", system="")  # 32K window
        exc = ctx.exception
        self.assertGreater(exc.estimated_tokens, exc.context_window)
        self.assertEqual(exc.context_window, 32_000)

    def test_system_plus_current_too_large_raises_before_any_history_work(self):
        history = [{"role": "user", "content": "short question"}]
        huge_system = "policy " * 50_000  # ~87.5K tokens of system text alone
        with self.assertRaises(ContextBudgetError):
            budget_history(history, model="mistral-small", system=huge_system)

    def test_rejection_error_message_is_diagnosable(self):
        huge_current = {"role": "user", "content": "x" * 300_000}
        try:
            budget_history([huge_current], model="mistral-small", system="")
            self.fail("expected ContextBudgetError")
        except ContextBudgetError as exc:
            msg = str(exc)
            self.assertIn("mistral-small", msg)
            self.assertIn("context window", msg)


class TestBudgetIsDynamicPerModelNotHardcoded(unittest.TestCase):
    """The policy must be provider-agnostic: the same history compacts
    under a small-context model but not under a large-context one, purely
    because catalog.get(model).context_window differs — nothing about
    budget_history() itself is Claude-specific."""

    def test_same_history_compacts_for_small_window_but_not_large_window(self):
        history = _history(30, msg_len=4_000)  # ~30K tokens total

        small_window_result = budget_history(history, model="mistral-small", system="")  # 32K window
        large_window_result = budget_history(history, model="claude-sonnet-4-6", system="")  # 200K window

        self.assertTrue(small_window_result.compacted)
        self.assertFalse(large_window_result.compacted)

    def test_unknown_model_falls_back_to_a_safe_default_window(self):
        history = _history(4)
        result = budget_history(history, model="some-future-model-not-in-catalog", system="")
        self.assertEqual(result.context_window, 200_000)  # _DEFAULT_CONTEXT_WINDOW
        self.assertFalse(result.compacted)

    def test_none_model_also_falls_back_safely(self):
        history = _history(4)
        result = budget_history(history, model=None, system="")
        self.assertFalse(result.compacted)


class TestObservabilityHooksNeverBreakARequest(unittest.TestCase):
    """Uses the existing MetricsRegistry (app.core.observability.metrics) —
    must never raise even if metrics internals misbehave."""

    def test_record_budget_metrics_does_not_raise_on_normal_result(self):
        result = HistoryBudgetResult(
            messages=[{"role": "user", "content": "hi"}],
            estimated_tokens=10, context_window=200_000,
        )
        record_budget_metrics(result)  # must not raise

    def test_record_budget_metrics_reflects_in_the_real_metrics_registry(self):
        from app.core.observability.metrics import get_metrics
        result = HistoryBudgetResult(
            messages=[{"role": "user", "content": "hi"}],
            estimated_tokens=1234, context_window=200_000,
            dropped_count=3, compacted=True,
        )
        record_budget_metrics(result)
        snap = get_metrics().snapshot()
        self.assertIn("context_history_compaction_total", snap["counters"])
        self.assertGreaterEqual(snap["counters"]["context_history_compaction_total"], 1)
        self.assertIn("context_estimated_tokens", snap["histograms"])

    def test_record_budget_rejection_does_not_raise_and_increments_counter(self):
        from app.core.observability.metrics import get_metrics
        exc = ContextBudgetError("too big", estimated_tokens=999_999, context_window=32_000)
        record_budget_rejection(exc)  # must not raise
        snap = get_metrics().snapshot()
        self.assertIn("context_overflow_rejected_total", snap["counters"])
        self.assertGreaterEqual(snap["counters"]["context_overflow_rejected_total"], 1)


if __name__ == "__main__":
    unittest.main()
