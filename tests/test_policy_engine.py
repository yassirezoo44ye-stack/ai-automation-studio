"""
Tests for PolicyEngine.blocked_patterns (Phase 1A).
Covers: default-off, match raises, no-match passes, invalid regex skipped,
case-insensitive match, first-match-wins on multiple patterns.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.ai.policy.engine import PolicyConfig, PolicyEngine, PolicyViolationError


def _make_engine(**kwargs) -> PolicyEngine:
    """Build a PolicyEngine with a no-op async bus mock."""
    bus = MagicMock()
    bus.emit = AsyncMock()
    return PolicyEngine(bus, PolicyConfig(**kwargs))


def _req(prompt: str = "", **kwargs):
    req = MagicMock()
    req.prompt = prompt
    req.user_id = "u1"
    req.tools = []
    req.max_cost_usd = None
    req.provider_id = None
    for k, v in kwargs.items():
        setattr(req, k, v)
    return req


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestBlockedPatternsDefault(unittest.TestCase):
    def test_empty_patterns_no_violation(self):
        """Default config (no blocked_patterns) never raises for any prompt."""
        engine = _make_engine()
        run(engine.check(_req("drop table users"), "r1"))  # must not raise

    def test_default_is_empty_list(self):
        cfg = PolicyConfig()
        self.assertEqual(cfg.blocked_patterns, [])


class TestBlockedPatternsMatch(unittest.TestCase):
    def test_exact_word_raises(self):
        engine = _make_engine(blocked_patterns=[r"drop\s+table"])
        with self.assertRaises(PolicyViolationError) as cm:
            run(engine.check(_req("DROP TABLE users"), "r2"))
        self.assertEqual(cm.exception.policy, "content")
        self.assertEqual(cm.exception.rule, "blocked_pattern")

    def test_case_insensitive(self):
        engine = _make_engine(blocked_patterns=[r"confidential"])
        with self.assertRaises(PolicyViolationError):
            run(engine.check(_req("This is CONFIDENTIAL info"), "r3"))

    def test_no_match_passes(self):
        engine = _make_engine(blocked_patterns=[r"ssn:\s*\d{9}"])
        run(engine.check(_req("My name is Alice"), "r4"))  # must not raise

    def test_partial_match_in_long_prompt(self):
        engine = _make_engine(blocked_patterns=[r"secret"])
        with self.assertRaises(PolicyViolationError):
            run(engine.check(_req("Please keep this a big secret ok"), "r5"))

    def test_first_matching_pattern_raises(self):
        """Multiple patterns — engine raises on first match."""
        engine = _make_engine(blocked_patterns=[r"alpha", r"beta"])
        with self.assertRaises(PolicyViolationError) as cm:
            run(engine.check(_req("alpha content here"), "r6"))
        self.assertIn("alpha", cm.exception.value)

    def test_second_pattern_also_raises(self):
        engine = _make_engine(blocked_patterns=[r"alpha", r"beta"])
        with self.assertRaises(PolicyViolationError):
            run(engine.check(_req("only beta here"), "r7"))

    def test_no_pattern_matches_passes(self):
        engine = _make_engine(blocked_patterns=[r"alpha", r"beta"])
        run(engine.check(_req("nothing to see here"), "r8"))


class TestBlockedPatternsInvalidRegex(unittest.TestCase):
    def test_invalid_regex_is_skipped_not_raised(self):
        """Bad regex pattern must be skipped silently; valid patterns still run."""
        engine = _make_engine(blocked_patterns=[r"[invalid", r"secret"])
        with self.assertRaises(PolicyViolationError):
            run(engine.check(_req("this is a secret"), "r9"))

    def test_only_invalid_patterns_never_raises(self):
        engine = _make_engine(blocked_patterns=[r"[bad", r"(unclosed"])
        run(engine.check(_req("anything"), "r10"))  # must not raise


class TestBlockedPatternsWithOtherRules(unittest.TestCase):
    def test_prompt_length_checked_before_patterns(self):
        """max_prompt_chars check fires first; pattern check is secondary."""
        engine = _make_engine(max_prompt_chars=5, blocked_patterns=[r"secret"])
        with self.assertRaises(PolicyViolationError) as cm:
            run(engine.check(_req("this is too long and has secret"), "r11"))
        self.assertEqual(cm.exception.rule, "prompt_length")

    def test_empty_prompt_never_matches_non_empty_pattern(self):
        engine = _make_engine(blocked_patterns=[r"\w+"])
        with self.assertRaises(PolicyViolationError):
            run(engine.check(_req("hello"), "r12"))

    def test_empty_prompt_with_empty_word_boundary_pattern(self):
        engine = _make_engine(blocked_patterns=[r"^$"])
        with self.assertRaises(PolicyViolationError):
            run(engine.check(_req(""), "r13"))


if __name__ == "__main__":
    unittest.main()
