"""
ApprovalService — persistent, time-bounded approval gates for high-risk actions.

Unlike the WorkflowEngine's in-memory ApprovalRegistry (which is lost on
restart), this service persists approval records in eng_approvals so they
survive process restarts and can be shown in the UI.

Approval lifecycle:
  PENDING → APPROVED | REJECTED | EXPIRED

An approval EXPIRES if not decided within expires_at. The MissionRunner
checks expiry before executing DEPLOY/DESTRUCTIVE tools.

Permission to approve:
  risk_level=low|medium  → operator or higher
  risk_level=high        → admin or owner
  risk_level=critical    → owner only

The DESTRUCTIVE and DEPLOY tool categories require an active APPROVED record.
The gateway calls ApprovalService to check. When no approval exists, it raises
ToolApprovalRequired, and the MissionRunner creates an approval request and
transitions the mission to WAITING_APPROVAL.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

# Default expiry windows per risk level
_DEFAULT_EXPIRY_HOURS: dict[str, int] = {
    "low":      24,
    "medium":   8,
    "high":     4,
    "critical": 2,
}

# Minimum roles allowed to approve per risk level
_APPROVE_ROLES: dict[str, set[str]] = {
    "low":      {"operator", "manager", "admin", "owner"},
    "medium":   {"manager", "admin", "owner"},
    "high":     {"admin", "owner"},
    "critical": {"owner"},
}


class ApprovalNotFound(Exception):
    pass


class ApprovalExpiredError(Exception):
    pass


class ApprovalPermissionError(Exception):
    pass


class ApprovalService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def request_approval(
        self,
        *,
        org_id: str,
        mission_id: str,
        task_id: Optional[str],
        action: str,
        resource: str,
        risk_level: str,
        requested_by: str,
        reason: str,
        evidence_id: Optional[str] = None,
        expiry_hours: Optional[int] = None,
    ) -> dict[str, Any]:
        """Create a new pending approval request. Returns the approval record."""
        approval_id = str(uuid.uuid4())
        hours = expiry_hours or _DEFAULT_EXPIRY_HOURS.get(risk_level, 4)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO eng_approvals
                   (id, organization_id, mission_id, task_id,
                    action, resource, risk_level,
                    requested_by, reason, evidence_id,
                    expires_at, status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'pending')""",
                uuid.UUID(approval_id),
                uuid.UUID(org_id),
                uuid.UUID(mission_id),
                uuid.UUID(task_id) if task_id else None,
                action,
                resource,
                risk_level,
                uuid.UUID(requested_by),
                reason[:2000],
                uuid.UUID(evidence_id) if evidence_id else None,
                expires_at,
            )
        log.info(
            "approval requested: %s for action=%r mission=%s (risk=%s)",
            approval_id[:8], action, mission_id[:8], risk_level,
        )
        return await self.get_approval(approval_id, org_id=org_id)

    async def get_approval(self, approval_id: str, *, org_id: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, organization_id, mission_id, task_id,
                          action, resource, risk_level,
                          requested_by, decided_by, decision,
                          reason, evidence_id, expires_at,
                          created_at, decided_at, status
                   FROM eng_approvals
                   WHERE id=$1 AND organization_id=$2""",
                uuid.UUID(approval_id), uuid.UUID(org_id),
            )
        if row is None:
            raise ApprovalNotFound(approval_id)
        return _approval_row(row)

    async def list_pending(
        self, *, org_id: str, mission_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List pending (not yet decided, not expired) approvals."""
        # First expire stale records
        await self._expire_stale(org_id)
        extra = ""
        params: list[Any] = [uuid.UUID(org_id)]
        if mission_id:
            extra = f" AND mission_id=${len(params)+1}"
            params.append(uuid.UUID(mission_id))
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT id, organization_id, mission_id, action, resource,
                           risk_level, requested_by, reason, expires_at,
                           created_at, status
                    FROM eng_approvals
                    WHERE organization_id=$1 AND status='pending'{extra}
                    ORDER BY created_at ASC""",
                *params,
            )
        return [_approval_summary(r) for r in rows]

    async def decide(
        self,
        approval_id: str,
        *,
        org_id: str,
        decided_by: str,
        decision: str,       # 'approved' or 'rejected'
        decider_role: str,
    ) -> dict[str, Any]:
        """Approve or reject a pending approval. Enforces role permission."""
        if decision not in ("approved", "rejected"):
            raise ValueError(f"invalid decision {decision!r}")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT status, risk_level, expires_at FROM eng_approvals "
                    "WHERE id=$1 AND organization_id=$2 FOR UPDATE",
                    uuid.UUID(approval_id), uuid.UUID(org_id),
                )
                if row is None:
                    raise ApprovalNotFound(approval_id)
                if row["status"] != "pending":
                    raise ValueError(f"approval is already {row['status']}")
                if datetime.now(timezone.utc) >= row["expires_at"]:
                    await conn.execute(
                        "UPDATE eng_approvals SET status='expired' WHERE id=$1",
                        uuid.UUID(approval_id),
                    )
                    raise ApprovalExpiredError(f"approval {approval_id[:8]} has expired")
                # Role check
                allowed = _APPROVE_ROLES.get(row["risk_level"], set())
                if decider_role not in allowed:
                    raise ApprovalPermissionError(
                        f"risk_level={row['risk_level']} requires role in {allowed}; "
                        f"caller has {decider_role!r}"
                    )
                await conn.execute(
                    """UPDATE eng_approvals
                       SET status=$2, decision=$2, decided_by=$3, decided_at=NOW()
                       WHERE id=$1""",
                    uuid.UUID(approval_id), decision, uuid.UUID(decided_by),
                )
        log.info(
            "approval %s: %s by %s (role=%s)",
            approval_id[:8], decision, decided_by[:8], decider_role,
        )
        return await self.get_approval(approval_id, org_id=org_id)

    async def _expire_stale(self, org_id: str) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """UPDATE eng_approvals SET status='expired'
                       WHERE organization_id=$1 AND status='pending'
                         AND expires_at < NOW()""",
                    uuid.UUID(org_id),
                )
        except Exception:
            log.warning("approval expiry check failed (continuing)", exc_info=True)

    async def list_for_mission(
        self, mission_id: str, *, org_id: str
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, action, resource, risk_level, status,
                          decision, requested_by, decided_by,
                          reason, expires_at, created_at, decided_at
                   FROM eng_approvals
                   WHERE mission_id=$1 AND organization_id=$2
                   ORDER BY created_at DESC""",
                uuid.UUID(mission_id), uuid.UUID(org_id),
            )
        return [_approval_summary(r) for r in rows]


def _approval_row(row) -> dict[str, Any]:
    return {
        "id":            str(row["id"]),
        "org_id":        str(row["organization_id"]),
        "mission_id":    str(row["mission_id"]),
        "task_id":       str(row["task_id"]) if row["task_id"] else None,
        "action":        row["action"],
        "resource":      row["resource"],
        "risk_level":    row["risk_level"],
        "requested_by":  str(row["requested_by"]),
        "decided_by":    str(row["decided_by"]) if row["decided_by"] else None,
        "decision":      row["decision"],
        "reason":        row["reason"],
        "evidence_id":   str(row["evidence_id"]) if row["evidence_id"] else None,
        "expires_at":    row["expires_at"].isoformat() if row["expires_at"] else None,
        "created_at":    row["created_at"].isoformat() if row["created_at"] else None,
        "decided_at":    row["decided_at"].isoformat() if row["decided_at"] else None,
        "status":        row["status"],
    }


def _approval_summary(row) -> dict[str, Any]:
    return {
        "id":          str(row["id"]),
        "action":      row["action"],
        "resource":    row["resource"],
        "risk_level":  row["risk_level"],
        "status":      row["status"],
        "decision":    row.get("decision"),
        "reason":      (row.get("reason") or "")[:300],
        "expires_at":  row["expires_at"].isoformat() if row.get("expires_at") else None,
        "created_at":  row["created_at"].isoformat() if row.get("created_at") else None,
        "decided_at":  row["decided_at"].isoformat() if row.get("decided_at") else None,
    }


# ── Singleton ─────────────────────────────────────────────────────────────────

_svc: Optional[ApprovalService] = None


def get_approval_service(pool=None) -> ApprovalService:
    global _svc
    if _svc is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _svc = ApprovalService(pool)
    return _svc
