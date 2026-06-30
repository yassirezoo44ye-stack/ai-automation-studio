"""
Cross-cutting helpers used by multiple routers.
"""
import uuid
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
