"""
Lead classification parsing — shared by lead qualification
(app/core/leads/service.py, 1-10 score) and the automation "ai" step with
output="lead_classification" (app/core/workflow/automation_scheduler.py,
0-100 score).

A classification is {"tier": "hot" | "warm" | "cold", "score": int, "reason": str}.
Anything else raises ValueError: a malformed AI answer must never be stored
as if it were a real classification.
"""
from __future__ import annotations

import json

LEAD_TIERS = ("hot", "warm", "cold")


def extract_json_object(text: str) -> dict:
    """Parse the JSON object in an LLM response (bare or inside a code fence).
    Raises ValueError when no valid JSON object is present."""
    text = (text or "").strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("AI response contains no JSON object") from None
        parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON is not an object")
    return parsed


def validate_lead_classification(
    data: dict, *, score_min: int = 0, score_max: int = 100,
) -> dict:
    """Return {tier, score, reason} or raise ValueError."""
    tier = data.get("tier")
    if not isinstance(tier, str) or tier.strip().lower() not in LEAD_TIERS:
        raise ValueError(f"invalid lead tier: {tier!r}")
    score = data.get("score")
    # is_integer() is False for 90.5, NaN and Infinity alike.
    if isinstance(score, bool) or not (
        isinstance(score, int) or (isinstance(score, float) and score.is_integer())
    ):
        raise ValueError(f"invalid lead score: {score!r}")
    if not score_min <= int(score) <= score_max:
        raise ValueError(f"lead score out of range: {score!r}")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("lead classification reason is missing")
    return {"tier": tier.strip().lower(), "score": int(score), "reason": reason.strip()}
