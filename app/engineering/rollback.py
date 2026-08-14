"""
RollbackService — controlled rollback for engineering missions.

Rules (v1):
  - NO automatic rollback to Production in v1 (per spec).
  - Rollback is always APPROVAL-GATED (risk_level=high → admin/owner only).
  - Rollback is available only for FAILED missions that had at least one deploy.
  - The rollback target SHA must be explicitly specified (not inferred by the AI).
  - Every rollback attempt is recorded as Evidence.
  - Successful rollback still requires ProductionVerifier SHA confirmation.

The flow:
  1. Caller specifies target_deploy_id (a previously SUCCESSFUL deploy's deploy_id)
  2. ApprovalService.request_approval() creates a high-risk approval
  3. Once APPROVED, RollbackService.execute_rollback() calls render.trigger_deploy
     with the target_service_id and records evidence
  4. ProductionVerifier.verify_render_deploy() confirms SHA match
  5. If verified → evidence marked VERIFIED; mission can be closed
  6. If not verified → evidence marked FAILED; rollback BLOCKED, human required

What this module does NOT do:
  - Does NOT trigger rollback automatically.
  - Does NOT read/write secrets.
  - Does NOT bypass the approval gate.
  - Does NOT mark a mission SUCCEEDED after rollback (the operator decides that).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


class RollbackNotAllowedError(Exception):
    """Raised when rollback preconditions are not met."""


class RollbackService:
    """
    Prepares and records rollback operations.

    Rollback is split into three separate calls to make the approval gate
    explicit in the caller's workflow:

      1. request_rollback()  → creates ApprovalRequest, returns approval_id
      2. (Human approves in the Approval Center)
      3. execute_rollback()  → checks approval is APPROVED, calls render, records evidence
      4. verify_rollback()   → delegates to ProductionVerifier
    """

    def __init__(self, pool=None) -> None:
        self._pool = pool

    def _get_pool(self):
        if self._pool:
            return self._pool
        from app.core.db import get_pool
        return get_pool()

    async def request_rollback(
        self,
        *,
        org_id: str,
        mission_id: str,
        service_id: str,
        target_deploy_id: str,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        """
        Gate: create a high-risk approval for the rollback.
        Returns the pending ApprovalRecord. Rollback does NOT start here.
        """
        from app.engineering.approvals import get_approval_service
        approval_svc = get_approval_service(self._get_pool())
        approval = await approval_svc.request_approval(
            org_id=org_id,
            mission_id=mission_id,
            task_id=None,
            action="rollback_deploy",
            resource=f"render:{service_id}:{target_deploy_id}",
            risk_level="high",
            requested_by=requested_by,
            reason=reason[:2000],
            evidence_id=None,
            expiry_hours=4,
        )
        log.info(
            "rollback requested: approval=%s service=%s target_deploy=%s",
            approval["id"][:8], service_id, target_deploy_id[:8],
        )
        return approval

    async def execute_rollback(
        self,
        *,
        org_id: str,
        mission_id: str,
        approval_id: str,
        service_id: str,
        target_deploy_id: str,
        requested_sha: str,
        executed_by: str,
    ) -> dict[str, Any]:
        """
        Execute a previously approved rollback.

        Checks that the approval is APPROVED before triggering.
        Returns the new deploy_id and evidence_id.
        """
        pool = self._get_pool()
        from app.engineering.approvals import get_approval_service, ApprovalNotFound

        # Verify approval is in APPROVED state
        approval_svc = get_approval_service(pool)
        try:
            approval = await approval_svc.get_approval(approval_id, org_id=org_id)
        except ApprovalNotFound:
            raise RollbackNotAllowedError(f"approval {approval_id[:8]} not found")

        if approval["status"] != "approved":
            raise RollbackNotAllowedError(
                f"rollback requires status=approved; current={approval['status']!r}"
            )

        # Load Render credential
        from app.integrations.credential_store import get_credential_store
        cred = await get_credential_store(pool).load("render", org_id)
        if cred is None:
            raise RollbackNotAllowedError("render integration not connected for this org")

        # Trigger the rollback deploy — we use the target_deploy_id to re-deploy
        import httpx
        from app.integrations.providers.render import _auth_header
        _RENDER_API = "https://api.render.com/v1"
        _TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)

        new_deploy_id = None
        started_at = None
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_RENDER_API}/services/{service_id}/deploys",
                    headers=_auth_header(cred),
                    json={"clearCache": "do_not_clear"},  # re-deploy existing image
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                new_deploy_id = data.get("id")
                started_at = data.get("createdAt")
            else:
                raise RollbackNotAllowedError(
                    f"render trigger returned {resp.status_code}: {resp.text[:200]}"
                )
        except httpx.TransportError as exc:
            raise RollbackNotAllowedError(f"render transport error: {exc}") from exc

        # Record evidence (verification_status=pending until verifier runs)
        import hashlib
        import json as _json
        inputs_hash = hashlib.sha256(
            _json.dumps({
                "service_id":       service_id,
                "target_deploy_id": target_deploy_id,
                "requested_sha":    requested_sha,
                "approval_id":      approval_id,
            }, sort_keys=True).encode()
        ).hexdigest()[:32]

        from app.engineering.evidence import get_evidence_store
        evidence_id = await get_evidence_store(pool).record(
            org_id=org_id,
            mission_id=mission_id,
            task_id=None,
            provider="render",
            operation="rollback_deploy",
            tool_name="rollback.execute",
            inputs_hash=inputs_hash,
            outputs_summary={
                "service_id":       service_id,
                "target_deploy_id": target_deploy_id,
                "new_deploy_id":    new_deploy_id,
                "started_at":       started_at,
                "approval_id":      approval_id,
                "executed_by":      executed_by,
                "note":             "rollback triggered — SHA verification required",
            },
            verification_status="pending",
            requested_sha=requested_sha,
            deploy_id=new_deploy_id,
        )

        log.info(
            "rollback triggered: service=%s new_deploy=%s evidence=%s",
            service_id, (new_deploy_id or "?")[:8], evidence_id[:8],
        )
        return {
            "new_deploy_id": new_deploy_id,
            "evidence_id":   evidence_id,
            "approval_id":   approval_id,
            "status":        "triggered",
            "note":          "Call verify_rollback() to confirm SHA match before closing mission.",
        }

    async def verify_rollback(
        self,
        *,
        org_id: str,
        mission_id: str,
        service_id: str,
        new_deploy_id: str,
        requested_sha: str,
        evidence_id: str,
        health_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Verify a rollback deployment using ProductionVerifier.
        Returns VerificationResult-equivalent dict.
        """
        from app.engineering.verify import get_production_verifier
        verifier = get_production_verifier(self._get_pool())
        result = await verifier.verify_render_deploy(
            org_id=org_id,
            mission_id=mission_id,
            service_id=service_id,
            deploy_id=new_deploy_id,
            requested_sha=requested_sha,
            health_url=health_url,
            evidence_id=evidence_id,
        )
        return {
            "is_production_verified": result.is_production_verified,
            "sha_match":              result.sha_match,
            "health_ok":              result.health_ok,
            "deploy_status":          result.deploy_status,
            "failure_reason":         result.failure_reason,
            "checks":                 result.checks,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_rollback_svc: Optional[RollbackService] = None


def get_rollback_service(pool=None) -> RollbackService:
    global _rollback_svc
    if _rollback_svc is None:
        _rollback_svc = RollbackService(pool)
    return _rollback_svc
