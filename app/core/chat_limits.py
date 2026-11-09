"""Single source of truth for chat prompt limits.

The frontend reads these through GET /api/chat/limits so the counter shown
before sending and the server-side check can never drift apart.

Lengths are counted in Unicode code points (Python ``len(str)``); the
frontend counts with ``[...text].length``, which matches for every
character, including Arabic and emoji.
"""
from __future__ import annotations

from fastapi import HTTPException

# ~8–16k tokens depending on language. Large enough for a long Arabic brief
# with pasted reference text and code; anything bigger should be attached as
# a file or split, which the UI offers instead of truncating.
MAX_PROMPT_CHARS = 32_000

# Warn in the UI once the draft passes this share of the limit.
WARN_RATIO = 0.85


def limits_payload() -> dict:
    return {
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "warn_at_chars": int(MAX_PROMPT_CHARS * WARN_RATIO),
        "unit": "unicode_code_points",
    }


def validate_prompt(text: str | None, *, field: str = "prompt") -> None:
    """Reject empty or oversized prompts with a structured, explainable error.

    Raises 422 for empty input and 413 for oversized input. The ``detail``
    is a dict (not a bare string) so the client can show the exact numbers
    and keep the user's text in the composer.
    """
    if text is None or not text.strip():
        raise HTTPException(422, {
            "code": "prompt_empty",
            "field": field,
            "message": "The message is empty.",
            "message_ar": "الرسالة فارغة.",
        })
    length = len(text)
    if length > MAX_PROMPT_CHARS:
        raise HTTPException(413, {
            "code": "prompt_too_long",
            "field": field,
            "length": length,
            "limit": MAX_PROMPT_CHARS,
            "message": (
                f"The message is {length:,} characters; the limit is "
                f"{MAX_PROMPT_CHARS:,}. Attach the long part as a file or split it."
            ),
            "message_ar": (
                f"طول الرسالة {length:,} حرفًا والحد {MAX_PROMPT_CHARS:,}. "
                "أرفق الجزء الطويل كملف أو قسّم الرسالة."
            ),
        })
