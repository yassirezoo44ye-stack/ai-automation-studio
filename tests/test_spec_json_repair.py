"""
Behavioral regression tests for SaaS Factory spec JSON parsing helpers.

Tests _try_extract_json and _looks_truncated in isolation — no DB, no network,
no AI calls.  The module-level heavy imports (asyncpg, app.core.db, …) are
patched out so only the two pure utility functions are exercised.
"""
from __future__ import annotations

import json
import os
import sys
import unittest.mock as mock

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

_MOCKS = {
    "asyncpg": mock.MagicMock(),
    "app.ai": mock.MagicMock(),
    "app.ai.gateway": mock.MagicMock(),
    "app.ai.models": mock.MagicMock(),
    "app.core": mock.MagicMock(),
    "app.core.db": mock.MagicMock(),
}

with mock.patch.dict(sys.modules, _MOCKS):
    from app.services.app_builder import _try_extract_json, _looks_truncated, _SPEC_SYSTEM


# ── _looks_truncated ──────────────────────────────────────────────────────────

def test_looks_truncated_empty():
    assert _looks_truncated("") is True


def test_looks_truncated_true_for_missing_close_brace():
    """Response cut off in the middle of an object."""
    assert _looks_truncated('{"name": "app", "entities": [') is True


def test_looks_truncated_true_for_unbalanced_braces():
    assert _looks_truncated('{"a": {"b": 1}') is True


def test_looks_truncated_true_for_unbalanced_arrays():
    """Unbalanced [ should be detected even when braces are balanced."""
    assert _looks_truncated('{"agents": [{"name": "X"}') is True


def test_looks_truncated_false_for_valid_json():
    """Complete, parseable JSON is not considered truncated."""
    s = '{"name": "app", "entities": [], "agents": []}'
    assert _looks_truncated(s) is False
    assert json.loads(s)  # sanity: actually valid


def test_looks_truncated_false_for_unescaped_quote_error():
    """
    Unescaped double-quote produces 'Expecting comma delimiter' but the
    braces ARE balanced — _looks_truncated must return False so the retry
    path (not the truncation path) is taken.
    """
    bad = '{"agents": [{"system_prompt": "Help find "the best" deals."}]}'
    assert _looks_truncated(bad) is False
    # Confirm it really does fail to parse
    with __import__("pytest").raises(json.JSONDecodeError, match="delimiter"):
        json.loads(bad)


def test_looks_truncated_false_for_bare_newline_error():
    """
    Bare newline inside a string value produces 'Invalid control character'
    but braces are balanced — retry path should run, not truncation path.
    """
    bad = '{"agents": [{"system_prompt": "Be helpful.\nBe kind."}]}'
    assert _looks_truncated(bad) is False
    with __import__("pytest").raises(json.JSONDecodeError):
        json.loads(bad)


def test_looks_truncated_true_when_last_char_is_not_brace_or_bracket():
    """Response ending mid-string should be detected as truncated."""
    assert _looks_truncated('{"name": "my_ap') is True


# ── _try_extract_json ─────────────────────────────────────────────────────────

def test_try_extract_json_bare_json():
    raw = '{"name": "app"}'
    assert _try_extract_json(raw) == raw


def test_try_extract_json_strips_markdown_fence():
    raw = '```json\n{"name": "app"}\n```'
    result = _try_extract_json(raw)
    assert result == '{"name": "app"}'
    assert json.loads(result)


def test_try_extract_json_strips_unlabelled_fence():
    raw = '```\n{"name": "app"}\n```'
    result = _try_extract_json(raw)
    assert json.loads(result)


def test_try_extract_json_extracts_from_surrounding_prose():
    raw = 'Here is your spec:\n{"name": "app"}\nHope that helps!'
    result = _try_extract_json(raw)
    assert result.startswith("{") and result.endswith("}")
    assert json.loads(result)


def test_try_extract_json_returns_input_when_no_braces():
    """No JSON in response — returns stripped input unchanged (caller handles error)."""
    raw = "I cannot generate a spec for this request."
    result = _try_extract_json(raw)
    assert result == raw.strip()


def test_try_extract_json_does_not_alter_valid_bare_json():
    """A bare valid JSON object is returned exactly as-is."""
    valid = '{"a": 1, "b": [1, 2], "c": {"d": true}}'
    assert _try_extract_json(valid) == valid
    assert json.loads(_try_extract_json(valid))


# ── _SPEC_SYSTEM runtime encoding correctness ─────────────────────────────────

def test_spec_system_encoding_rule_contains_literal_backslash_quote():
    """
    _SPEC_SYSTEM must contain the two-character sequence backslash+double-quote
    as a literal in the runtime string — not a bare double-quote that would
    result from Python interpreting \" inside a triple-quoted string.
    """
    idx = _SPEC_SYSTEM.find("JSON string encoding")
    assert idx != -1, "_SPEC_SYSTEM does not contain the encoding rule"
    rule_section = _SPEC_SYSTEM[idx : idx + 300]
    # The literal sequence \" (backslash + double-quote, 2 chars) must be present
    assert '\\"' in rule_section, (
        "_SPEC_SYSTEM encoding rule must contain the literal two-character sequence "
        r'\"  (backslash + double-quote) so the model is instructed to escape quotes; '
        "a bare double-quote means Python consumed the backslash as an escape"
    )


def test_spec_system_encoding_rule_contains_literal_backslash_n():
    """
    _SPEC_SYSTEM must contain the two-character sequence backslash+n as a
    literal in the runtime string — not a newline character that would result
    from Python interpreting \\n inside a triple-quoted string.
    """
    idx = _SPEC_SYSTEM.find("JSON string encoding")
    assert idx != -1, "_SPEC_SYSTEM does not contain the encoding rule"
    rule_section = _SPEC_SYSTEM[idx : idx + 300]
    # The literal sequence \n (backslash + n, 2 chars) must be present
    assert '\\n' in rule_section, (
        "_SPEC_SYSTEM encoding rule must contain the literal two-character sequence "
        r"\n  (backslash + n) so the model is instructed to escape newlines; "
        "a bare newline character means Python consumed the backslash"
    )


def test_spec_system_encoding_rule_line_is_not_split_by_newline():
    """
    The encoding rule line must not be broken by a literal newline in the
    middle of 'as \\n' — which would indicate the \\n was interpreted by
    Python as a line break rather than passed as the two-character sequence.
    """
    idx = _SPEC_SYSTEM.find("line break as ")
    assert idx != -1, "encoding rule phrase 'line break as' not found at runtime"
    # What immediately follows 'line break as ' must be backslash+n, not a newline
    after = _SPEC_SYSTEM[idx + len("line break as "):]
    assert after[0] == "\\", (
        "The character immediately after 'line break as ' must be a backslash, "
        "not a newline — indicating \\n was correctly preserved as a two-char literal"
    )
    assert after[1] == "n", (
        "The two characters after 'line break as ' must be backslash+n (\\\\n), "
        "not a backslash followed by something else"
    )
