"""
EvidenceStore — immutable records produced by every external tool call.

Rules:
  - Evidence is WRITE-ONCE. Records are inserted, never updated.
    (verification_status is a separate UPDATE because it happens after the fact.)
  - Evidence never contains secrets or raw credentials.
  - A Mission cannot be marked SUCCEEDED without at least one verified Evidence
    record for every DEPLOY tool call it made.
  - The VerifyEngine updates verification_status after confirming SHA match.

Evidence is also used in the Approval Center: before approving a high-risk
action, the approver can see the Evidence record from the dry-run (if any).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)


class EvidenceStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(
        self,
        *,
        org_id: str,
        mission_id: str,
        task_id: Optional[str],
        provider: str,
        operation: str,
        tool_name: str,
        inputs_hash: str,
        outputs_summary: dict[str, Any],
        verification_status: str = "unverified",
        requested_sha: Optional[str] = None,
        observed_sha: Optional[str] = None,
        deploy_id: Optional[str] = None,
    ) -> str:
        """Insert a new Evidence record. Returns evidence_id."""
        evidence_id = str(uuid.uuid4())
        sha_match = None
        if requested_sha and observed_sha:
            sha_match = requested_sha == observed_sha
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO eng_evidence
                   (id, organization_id, mission_id, task_id,
                    provider, operation, tool_name,
                    inputs_hash, outputs_summary, verification_status,
                    requested_sha, observed_sha, deploy_id, sha_match)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                uuid.UUID(evidence_id),
                uuid.UUID(org_id),
                uuid.UUID(mission_id),
                uuid.UUID(task_id) if task_id else None,
                provider,
                operation,
                tool_name,
                inputs_hash,
                json.dumps(outputs_summary),
                verification_status,
                requested_sha,
                observed_sha,
                deploy_id,
                sha_match,
            )
        log.debug("evidence recorded: %s (tool=%s, status=%s)", evidence_id[:8], tool_name, verification_status)
        return evidence_id

    async def mark_verified(self, evidence_id: str, *, org_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE eng_evidence
                   SET verification_status='verified', verified_at=NOW()
                   WHERE id=$1 AND organization_id=$2""",
                uuid.UUID(evidence_id), uuid.UUID(org_id),
            )

    async def mark_failed(self, evidence_id: str, *, org_id: str, reason: str = "") -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE eng_evidence
                   SET verification_status='failed', verified_at=NOW(),
                       outputs_summary = outputs_summary || $3::jsonb
                   WHERE id=$1 AND organization_id=$2""",
                uuid.UUID(evidence_id),
                uuid.UUID(org_id),
                json.dumps({"failure_reason": reason[:500]}),
            )

    async def update_sha(
        self,
        evidence_id: str,
        *,
        org_id: str,
        observed_sha: str,
        requested_sha: Optional[str] = None,
    ) -> bool:
        """Update observed SHA and compute sha_match. Returns sha_match result."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT requested_sha FROM eng_evidence WHERE id=$1 AND organization_id=$2",
                uuid.UUID(evidence_id), uuid.UUID(org_id),
            )
            if row is None:
                return False
            req_sha = requested_sha or row["requested_sha"]
            sha_match = (req_sha == observed_sha) if req_sha else False
            await conn.execute(
                """UPDATE eng_evidence
                   SET observed_sha=$2, sha_match=$3,
                       verification_status = CASE WHEN $3 THEN 'verified' ELSE 'failed' END,
                       verified_at = NOW()
                   WHERE id=$1""",
                uuid.UUID(evidence_id), observed_sha, sha_match,
            )
        return sha_match

    async def get(self, evidence_id: str, *, org_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, organization_id, mission_id, task_id,
                          provider, operation, tool_name,
                          inputs_hash, outputs_summary, verification_status,
                          requested_sha, observed_sha, deploy_id, sha_match,
                          verified_at, created_at
                   FROM eng_evidence
                   WHERE id=$1 AND organization_id=$2""",
                uuid.UUID(evidence_id), uuid.UUID(org_id),
            )
        if row is None:
            return None
        return _ev_row(row)

    async def list_for_mission(
        self, mission_id: str, *, org_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, provider, operation, tool_name,
                          verification_status, sha_match,
                          requested_sha, observed_sha, deploy_id,
                          verified_at, created_at
                   FROM eng_evidence
                   WHERE mission_id=$1 AND organization_id=$2
                   ORDER BY created_at DESC
                   LIMIT $3""",
                uuid.UUID(mission_id), uuid.UUID(org_id), limit,
            )
        return [_ev_summary(r) for r in rows]

    async def has_verified_deploy(self, mission_id: str, *, org_id: str) -> bool:
        """Check whether all DEPLOY tool calls in this mission have a verified
        Evidence record with sha_match=True. Required before marking SUCCEEDED."""
        async with self._pool.acquire() as conn:
            # Count deploy-class tool calls
            deploy_count = await conn.fetchval(
                """SELECT count(*) FROM eng_evidence
                   WHERE mission_id=$1 AND organization_id=$2
                     AND operation LIKE '%deploy%'""",
                uuid.UUID(mission_id), uuid.UUID(org_id),
            )
            if deploy_count == 0:
                # No deploys in this mission — no verification needed
                return True
            # All deploys must be verified with SHA match
            unverified = await conn.fetchval(
                """SELECT count(*) FROM eng_evidence
                   WHERE mission_id=$1 AND organization_id=$2
                     AND operation LIKE '%deploy%'
                     AND (verification_status != 'verified' OR sha_match IS NOT TRUE)""",
                uuid.UUID(mission_id), uuid.UUID(org_id),
            )
        return unverified == 0


def _ev_row(row) -> dict[str, Any]:
    d = dict(row)
    d["id"]              = str(d["id"])
    d["organization_id"] = str(d["organization_id"])
    d["mission_id"]      = str(d["mission_id"])
    d["task_id"]         = str(d["task_id"]) if d["task_id"] else None
    if isinstance(d.get("outputs_summary"), str):
        import json
        try:
            d["outputs_summary"] = json.loads(d["outputs_summary"])
        except Exception:
            pass
    return d


def _ev_summary(row) -> dict[str, Any]:
    return {
        "id":                  str(row["id"]),
        "provider":            row["provider"],
        "operation":           row["operation"],
        "tool_name":           row["tool_name"],
        "verification_status": row["verification_status"],
        "sha_match":           row["sha_match"],
        "requested_sha":       row["requested_sha"],
        "observed_sha":        row["observed_sha"],
        "deploy_id":           row["deploy_id"],
        "verified_at":         row["verified_at"].isoformat() if row["verified_at"] else None,
        "created_at":          row["created_at"].isoformat() if row["created_at"] else None,
    }


# ── Singleton ─────────────────────────────────────────────────────────────────

_store: Optional[EvidenceStore] = None


def get_evidence_store(pool=None) -> EvidenceStore:
    global _store
    if _store is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _store = EvidenceStore(pool)
    return _store
