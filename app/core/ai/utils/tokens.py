"""
Token estimation utilities.

Exact token counts require calling the provider API.
These estimators are good enough for budget/context-window checks before a call.

Rule of thumb: 1 token ≈ 4 characters (English text).
For code: 1 token ≈ 3 characters.
"""
from __future__ import annotations

import re
from typing import Any

_CHARS_PER_TOKEN_TEXT = 4.0
_CHARS_PER_TOKEN_CODE = 3.0

_CODE_RE = re.compile(r"```[\s\S]*?```|`[^`]+`")


def estimate_tokens(text: str) -> int:
    """Rough token count for a plain-text string."""
    if not text:
        return 0
    code_chars  = sum(len(m.group()) for m in _CODE_RE.finditer(text))
    plain_chars = len(text) - code_chars
    return max(1, round(
        plain_chars / _CHARS_PER_TOKEN_TEXT
        + code_chars / _CHARS_PER_TOKEN_CODE
    ))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate tokens for a list of message dicts with 'content' keys."""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content) + 4  # per-message overhead
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += estimate_tokens(part["text"])
            total += 4
    return total + 2  # reply primer overhead


def fits_context(
    messages_tokens: int,
    *,
    context_window: int,
    max_output: int = 2048,
    safety_margin: float = 0.9,
) -> bool:
    """Return True if the messages + output budget fits inside the context window."""
    budget = int(context_window * safety_margin) - max_output
    return messages_tokens <= budget
