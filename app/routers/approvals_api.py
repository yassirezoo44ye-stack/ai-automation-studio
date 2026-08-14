"""
Engineering Approvals API.

Endpoints:
  GET    /api/engineering/approvals         — list pending approvals for org
  GET    /api/engineering/approvals/{id}    — get approval detail
  POST   /api/engineering/approvals/{id}/decide — approve or reject
  GET    /api/engineering/missions/{id}/approvals — approvals for a mission

Security:
  - org_id always from OrgContext.
  - Deciding requires role sufficient for the approval's risk_level
    (enforced by ApprovalService.decide(), not only here).
  - Approval content never reveals credentials or secrets.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.tenancy.context import OrgContext, require_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engineering", tags=["engineering"])


class DecideApprovalRequest(BaseModel):
    decision: str = Field(..., pattern=r"^(approved|rejected)$")
    reason:   Optional[str] = Field(None, max_length=2000)


@router.get("/approvals")
async def list_pending_approvals(
    mission_id: Optional[str] = Query(None),
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """List pending approvals for the org (optionally filtered to one mission)."""
    from app.engineering.approvals import get_approval_service
    svc = get_approval_service()
    approvals = await svc.list_pending(org_id=ctx.org_id, mission_id=mission_id)
    return {"approvals": approvals, "count": len(approvals)}


@router.get("/approvals/{approval_id}")
async def get_approval(
    approval_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    from app.engineering.approvals import get_approval_service, ApprovalNotFound
    svc = get_approval_service()
    try:
        return await svc.get_approval(approval_id, org_id=ctx.org_id)
    except ApprovalNotFound:
        raise HTTPException(404, "approval not found")


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    body: DecideApprovalRequest,
    ctx: OrgContext = Depends(require_permission("engineering", "approve")),
) -> dict[str, Any]:
    """
    Approve or reject a pending approval.

    Role enforcement is re-validated in ApprovalService.decide() against
    the approval's risk_level — the permission check here is a first gate.
    """
    from app.engineering.approvals import (
        get_approval_service, ApprovalNotFound,
        ApprovalExpiredError, ApprovalPermissionError,
    )
    svc = get_approval_service()
    try:
        result = await svc.decide(
            approval_id,
            org_id=ctx.org_id,
            decided_by=ctx.user_id,
            decision=body.decision,
            decider_role=ctx.role,
        )
    except ApprovalNotFound:
        raise HTTPException(404, "approval not found")
    except ApprovalExpiredError as exc:
        raise HTTPException(410, f"approval expired: {exc}")
    except ApprovalPermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    log.info(
        "approval %s decided=%s by user=%s role=%s",
        approval_id[:8], body.decision, ctx.user_id[:8], ctx.role,
    )
    return result


@router.get("/missions/{mission_id}/approvals")
async def list_mission_approvals(
    mission_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """Return full approval history for a mission."""
    from app.engineering.approvals import get_approval_service
    svc = get_approval_service()
    approvals = await svc.list_for_mission(mission_id, org_id=ctx.org_id)
    return {"approvals": approvals, "count": len(approvals)}
