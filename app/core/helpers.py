"""
Cross-cutting helpers used by multiple routers.
"""
import uuid
from datetime import datetime
from typing import Optional

import anthropic
from fastapi import HTTPException

from app.core.config import DEMO_PROJECT_ID
import os


# ── AI client factory ─────────────────────────────────────────────────────────

def get_ai_client() -> anthropic.Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")
    return anthropic.Anthropic(api_key=key)


def get_async_ai_client() -> anthropic.AsyncAnthropic:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")
    return anthropic.AsyncAnthropic(api_key=key)


# ── Project ID resolution ─────────────────────────────────────────────────────

def resolve_project_id(project_id: Optional[str]) -> uuid.UUID:
    """Map the frontend's "demo" pseudo-project to a fixed seeded UUID.
    Anything else must be a valid UUID string.
    """
    if not project_id or project_id == "demo":
        return DEMO_PROJECT_ID
    return uuid.UUID(project_id)


# ── Anthropic error normalisation ─────────────────────────────────────────────

def anthropic_error_message(e: anthropic.BadRequestError) -> str:
    """Extract the user-facing message from an Anthropic 400 error body."""
    body = e.body if hasattr(e, "body") and e.body else {}
    return body.get("error", {}).get("message", str(e)) if isinstance(body, dict) else str(e)


# ── Markdown fence stripper ───────────────────────────────────────────────────

def strip_fences(text: str) -> str:
    """Remove ``` fences that Claude sometimes wraps raw content in."""
    t = text.strip()
    if t.startswith("```"):
        t = "\n".join(t.split("\n")[1:])
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


# ── App-name sanitiser ────────────────────────────────────────────────────────

import re as _re

def sanitize_name(name: str) -> str:
    """Replace characters that are unsafe in filenames/directory names with underscores."""
    return _re.sub(r"[^A-Za-z0-9_\-]", "_", name) or "App"


# ── Task scheduling ───────────────────────────────────────────────────────────

def next_due_date(due: Optional[datetime], recurrence: str) -> Optional[datetime]:
    """Return the next due date for a recurring task, or None if non-recurring."""
    if not due or recurrence == "none":
        return None
    from datetime import timedelta
    if recurrence == "daily":
        return due + timedelta(days=1)
    if recurrence == "weekly":
        return due + timedelta(weeks=1)
    if recurrence == "monthly":
        month = due.month + 1
        year  = due.year + (1 if month > 12 else 0)
        month = month if month <= 12 else 1
        day   = min(due.day, 28)
        return due.replace(year=year, month=month, day=day)
    return None
