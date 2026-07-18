"""
Cross-cutting helpers used by multiple routers.
"""
import uuid
from datetime import datetime
from typing import Optional

import anthropic
from fastapi import HTTPException

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

async def resolve_project_id(conn, project_id: Optional[str], user_id: uuid.UUID) -> uuid.UUID:
    """Resolve a frontend project_id to a UUID the caller actually owns.

    "demo"/None resolves to the caller's own personal demo project
    (found-or-created), never a shared global row — the previous fixed
    DEMO_PROJECT_ID sentinel made every user's default chat/build/design
    project the same database row, so anyone's "New Chat" surfaced every
    other user's conversation history. An explicit UUID is verified against
    projects.user_id and rejected with 404 if the caller doesn't own it.
    """
    if not project_id or project_id == "demo":
        pid = await conn.fetchval(
            "SELECT id FROM projects WHERE user_id=$1 AND name=$2 ORDER BY created_at LIMIT 1",
            user_id, "Demo Project",
        )
        if pid:
            return pid
        return await conn.fetchval(
            "INSERT INTO projects (user_id, name, description) VALUES ($1,$2,$3) RETURNING id",
            user_id, "Demo Project", "Default project for the chat UI",
        )
    pid = uuid.UUID(project_id)
    owned = await conn.fetchval("SELECT 1 FROM projects WHERE id=$1 AND user_id=$2", pid, user_id)
    if not owned:
        raise HTTPException(404, "Project not found")
    return pid


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
