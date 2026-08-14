"""
EngineeringMemory — mission-scoped persistent facts for the AI planner.

Wraps the existing ai_memory_items table to store engineering-specific
knowledge: past deployment SHAs, test failure patterns, CI flakiness,
known-good configs, etc.

Rules:
  - All reads/writes are org-scoped (RLS enforced at DB).
  - Memory keys are namespaced: "eng:{mission_id}:{key}"
  - Contents are NEVER put in LLM context directly; they are injected as
    a structured system context summary by the MissionRunner.
  - Secrets and credentials are NEVER stored in memory.

Stored fact types:
  - "last_known_good_sha"     — the last SHA that was PRODUCTION VERIFIED
  - "ci_failure_patterns"    — list of patterns seen in CI failures
  - "deploy_history"         — [{deploy_id, sha, status, timestamp}]
  - "task_outcomes"          — [{task_name, success, duration_ms}]
  - "mission_notes"          — free-form notes from the AI planner
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

_MAX_VALUE_BYTES = 16_384  # 16 KB cap per fact


class EngineeringMemory:
    """
    Stores and retrieves mission-scoped facts.

    Backed by a simple key-value pattern in ai_memory_items, with the
    key format: "eng:{mission_id}:{fact_type}".

    If ai_memory_items does not exist (older installs), falls back gracefully
    to no-op and logs a warning.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def _key(self, mission_id: str, fact_type: str) -> str:
        return f"eng:{mission_id}:{fact_type}"

    async def store(
        self,
        *,
        org_id: str,
        mission_id: str,
        fact_type: str,
        value: Any,
        append: bool = False,
    ) -> None:
        """
        Upsert a fact for this mission.

        If append=True and the existing value is a list, the new value is
        appended rather than replacing. Lists are capped at 100 entries.
        """
        key = self._key(mission_id, fact_type)
        serialized = json.dumps(value, default=str)
        if len(serialized.encode()) > _MAX_VALUE_BYTES:
            log.warning("engineering memory: value too large for key %s (truncated)", key)
            serialized = serialized[:_MAX_VALUE_BYTES]

        try:
            async with self._pool.acquire() as conn:
                if append:
                    existing_raw = await conn.fetchval(
                        "SELECT content FROM ai_memory_items WHERE user_id=$1 AND key=$2",
                        uuid.UUID(org_id), key,
                    )
                    if existing_raw:
                        try:
                            existing = json.loads(existing_raw)
                        except Exception:
                            existing = []
                        if isinstance(existing, list):
                            new_value = existing[-99:] + [value]
                            serialized = json.dumps(new_value, default=str)[:_MAX_VALUE_BYTES]

                await conn.execute(
                    """INSERT INTO ai_memory_items (id, user_id, key, content, created_at, updated_at)
                       VALUES ($1, $2, $3, $4, NOW(), NOW())
                       ON CONFLICT (user_id, key)
                       DO UPDATE SET content=$4, updated_at=NOW()""",
                    uuid.uuid4(), uuid.UUID(org_id), key, serialized,
                )
        except asyncpg.UndefinedTableError:
            log.warning("engineering memory: ai_memory_items table not found — skipping store")
        except Exception as exc:
            log.warning("engineering memory store failed: %s", exc)

    async def retrieve(
        self,
        *,
        org_id: str,
        mission_id: str,
        fact_type: str,
    ) -> Optional[Any]:
        """Return a stored fact, or None if not found."""
        key = self._key(mission_id, fact_type)
        try:
            async with self._pool.acquire() as conn:
                raw = await conn.fetchval(
                    "SELECT content FROM ai_memory_items WHERE user_id=$1 AND key=$2",
                    uuid.UUID(org_id), key,
                )
            if raw is None:
                return None
            return json.loads(raw)
        except asyncpg.UndefinedTableError:
            return None
        except Exception as exc:
            log.warning("engineering memory retrieve failed: %s", exc)
            return None

    async def retrieve_all(
        self,
        *,
        org_id: str,
        mission_id: str,
    ) -> dict[str, Any]:
        """Return all stored facts for a mission as {fact_type: value}."""
        prefix = self._key(mission_id, "")
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT key, content FROM ai_memory_items
                       WHERE user_id=$1 AND key LIKE $2
                       ORDER BY updated_at DESC""",
                    uuid.UUID(org_id), f"{prefix}%",
                )
            result = {}
            for row in rows:
                fact_type = row["key"][len(prefix):]
                try:
                    result[fact_type] = json.loads(row["content"])
                except Exception:
                    result[fact_type] = row["content"]
            return result
        except asyncpg.UndefinedTableError:
            return {}
        except Exception as exc:
            log.warning("engineering memory retrieve_all failed: %s", exc)
            return {}

    async def delete(
        self,
        *,
        org_id: str,
        mission_id: str,
        fact_type: str,
    ) -> None:
        key = self._key(mission_id, fact_type)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM ai_memory_items WHERE user_id=$1 AND key=$2",
                    uuid.UUID(org_id), key,
                )
        except Exception as exc:
            log.warning("engineering memory delete failed: %s", exc)

    async def record_deployment(
        self,
        *,
        org_id: str,
        mission_id: str,
        deploy_id: str,
        sha: str,
        status: str,  # "verified" | "failed" | "unverified"
    ) -> None:
        """Convenience: append one deployment record to deploy_history."""
        await self.store(
            org_id=org_id,
            mission_id=mission_id,
            fact_type="deploy_history",
            value={
                "deploy_id": deploy_id,
                "sha":       sha,
                "status":    status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            append=True,
        )
        if status == "verified":
            await self.store(
                org_id=org_id,
                mission_id=mission_id,
                fact_type="last_known_good_sha",
                value=sha,
            )

    async def build_planner_context(
        self,
        *,
        org_id: str,
        mission_id: str,
    ) -> str:
        """
        Return a concise text summary of stored engineering facts, safe
        to inject as a system context prefix for the AI planner.

        Credentials are NEVER included here.
        """
        facts = await self.retrieve_all(org_id=org_id, mission_id=mission_id)
        if not facts:
            return ""
        lines = ["[Engineering Memory]"]
        if "last_known_good_sha" in facts:
            lines.append(f"• Last verified production SHA: {facts['last_known_good_sha']}")
        if "deploy_history" in facts:
            history = facts["deploy_history"]
            if isinstance(history, list):
                recent = history[-5:]
                lines.append(f"• Recent deploys ({len(recent)} shown):")
                for d in recent:
                    lines.append(
                        f"    – {d.get('sha', '?')[:8]} "
                        f"status={d.get('status', '?')} "
                        f"at {d.get('timestamp', '?')[:19]}"
                    )
        if "ci_failure_patterns" in facts:
            patterns = facts["ci_failure_patterns"]
            if isinstance(patterns, list) and patterns:
                lines.append(f"• Known CI failure patterns: {', '.join(str(p) for p in patterns[:5])}")
        if "mission_notes" in facts:
            notes = facts["mission_notes"]
            if notes:
                lines.append(f"• Notes: {str(notes)[:500]}")
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────

_mem: Optional[EngineeringMemory] = None


def get_engineering_memory(pool=None) -> EngineeringMemory:
    global _mem
    if _mem is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _mem = EngineeringMemory(pool)
    return _mem
