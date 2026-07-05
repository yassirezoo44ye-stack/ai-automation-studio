"""
Prompt versioning.

Prompts are templates stored in `ai_prompts` + `ai_prompt_versions`.
The gateway can load a named prompt by ID and interpolate variables.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.ai.models import PromptVersion

log = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")  # matches {{ variable_name }}


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_active_version(pool, prompt_id: str) -> Optional[PromptVersion]:
    """Return the active version of a prompt."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT pv.id, pv.prompt_id, pv.version,
                       pv.system, pv.user_template, pv.variables,
                       pv.created_at, pv.is_active
                FROM ai_prompt_versions pv
                JOIN ai_prompts p ON p.id = pv.prompt_id
                WHERE (p.id::text = $1 OR p.slug = $1)
                  AND pv.is_active = true
                ORDER BY pv.version DESC
                LIMIT 1
                """,
                prompt_id,
            )
            if not row:
                return None
            return PromptVersion(
                id=str(row["id"]),
                prompt_id=str(row["prompt_id"]),
                version=row["version"],
                system=row["system"],
                user_template=row["user_template"],
                variables=row["variables"] or [],
                created_at=row["created_at"].isoformat(),
                is_active=row["is_active"],
            )
    except Exception as exc:
        log.error("prompt_store.get_active_version failed: %s", exc)
        return None


async def render(
    version: PromptVersion,
    variables: dict[str, str],
) -> tuple[Optional[str], Optional[str]]:
    """
    Substitute variables into system and user_template.
    Returns (system, user_template) with all {{ var }} replaced.
    """
    def sub(text: Optional[str]) -> Optional[str]:
        if not text:
            return text
        def replace(m: re.Match) -> str:
            key = m.group(1)
            return variables.get(key, m.group(0))  # leave unreplaced if missing
        return _VAR_RE.sub(replace, text)

    return sub(version.system), sub(version.user_template)


# ── Write ─────────────────────────────────────────────────────────────────────

async def create_prompt(
    pool,
    *,
    name: str,
    slug: str,
    description: str = "",
    system: Optional[str] = None,
    user_template: Optional[str] = None,
    variables: Optional[list[str]] = None,
    user_id: Optional[str] = None,
) -> str:
    """Create a new prompt with version 1. Returns the prompt ID."""
    uid = uuid.UUID(user_id) if user_id else None
    vars_ = variables or _extract_variables(system, user_template)

    async with pool.acquire() as conn:
        async with conn.transaction():
            pid = await conn.fetchval(
                """
                INSERT INTO ai_prompts (name, slug, description, user_id, created_at)
                VALUES ($1,$2,$3,$4,$5) RETURNING id
                """,
                name, slug, description, uid, datetime.now(timezone.utc),
            )
            await conn.execute(
                """
                INSERT INTO ai_prompt_versions
                  (prompt_id, version, system, user_template, variables, is_active, created_at)
                VALUES ($1,1,$2,$3,$4,true,$5)
                """,
                pid, system, user_template, vars_, datetime.now(timezone.utc),
            )
    return str(pid)


async def publish_version(
    pool,
    prompt_id: str,
    *,
    system: Optional[str] = None,
    user_template: Optional[str] = None,
    variables: Optional[list[str]] = None,
) -> int:
    """Add a new version and activate it; deactivate previous versions. Returns new version number."""
    vars_ = variables or _extract_variables(system, user_template)
    pid   = uuid.UUID(prompt_id)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE ai_prompt_versions SET is_active=false WHERE prompt_id=$1",
                pid,
            )
            next_v = (await conn.fetchval(
                "SELECT COALESCE(MAX(version),0)+1 FROM ai_prompt_versions WHERE prompt_id=$1",
                pid,
            ))
            await conn.execute(
                """
                INSERT INTO ai_prompt_versions
                  (prompt_id, version, system, user_template, variables, is_active, created_at)
                VALUES ($1,$2,$3,$4,$5,true,$6)
                """,
                pid, next_v, system, user_template, vars_, datetime.now(timezone.utc),
            )
    return next_v


async def list_versions(pool, prompt_id: str) -> list[PromptVersion]:
    """List all versions of a prompt, newest first."""
    try:
        pid = uuid.UUID(prompt_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, prompt_id, version, system, user_template,
                       variables, created_at, is_active
                FROM ai_prompt_versions WHERE prompt_id=$1
                ORDER BY version DESC
                """,
                pid,
            )
        return [
            PromptVersion(
                id=str(r["id"]),
                prompt_id=str(r["prompt_id"]),
                version=r["version"],
                system=r["system"],
                user_template=r["user_template"],
                variables=r["variables"] or [],
                created_at=r["created_at"].isoformat(),
                is_active=r["is_active"],
            )
            for r in rows
        ]
    except Exception as exc:
        log.error("prompt_store.list_versions failed: %s", exc)
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_variables(*texts: Optional[str]) -> list[str]:
    """Extract unique {{ variable }} names from one or more template strings."""
    seen: list[str] = []
    for text in texts:
        if text:
            for m in _VAR_RE.finditer(text):
                key = m.group(1)
                if key not in seen:
                    seen.append(key)
    return seen
