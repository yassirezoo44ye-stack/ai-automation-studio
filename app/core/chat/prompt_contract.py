"""Shared, lossless prompt budget contract for Flow chat requests.

This module deliberately validates the original string without trimming,
normalizing line endings, or truncating it. Callers must preserve the value
when presenting a rejection so users can revise or split it themselves.
"""
from __future__ import annotations

from dataclasses import dataclass

# Keep this aligned with RunRequest and the frontend composer. A character
# budget is used rather than a token estimate: it is deterministic and can be
# shown before submission. Provider context budgeting remains a separate check.
MAX_PROMPT_CHARACTERS = 32_000


@dataclass(frozen=True)
class PromptBudget:
    characters: int
    maximum: int
    accepted: bool
    remaining: int


def measure_prompt(text: str, *, maximum: int = MAX_PROMPT_CHARACTERS) -> PromptBudget:
    """Measure the exact prompt string without changing a single character."""
    if not isinstance(text, str):
        raise TypeError("prompt must be a string")
    if maximum < 1:
        raise ValueError("maximum must be positive")
    length = len(text)
    return PromptBudget(
        characters=length,
        maximum=maximum,
        accepted=length <= maximum,
        remaining=max(0, maximum - length),
    )


def prompt_limit_message(budget: PromptBudget) -> str:
    """Return an actionable message; never imply that input was shortened."""
    return (
        f"This prompt contains {budget.characters:,} characters; "
        f"the limit is {budget.maximum:,}. Your text has not been changed. "
        "Please attach the reference as a file or split the request into "
        "linked parts, keeping the relevant context."
    )
