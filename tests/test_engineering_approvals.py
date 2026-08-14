"""
Tests: ApprovalService — role enforcement, expiry, FSM lifecycle,
risk level gates.
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_ORG_ID     = "00000000-0000-0000-0000-000000000001"
_MISSION_ID = "00000000-0000-0000-0000-000000000002"
_USER_ID    = "00000000-0000-0000-0000-000000000010"
_APPROVAL_ID = str(uuid.uuid4())


def _make_approval_row(
    status="pending",
    risk_level="high",
    expires_at=None,
    decision=None,
):
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
    return {
        "id":              uuid.UUID(_APPROVAL_ID),
        "organization_id": uuid.UUID(_ORG_ID),
        "mission_id":      uuid.UUID(_MISSION_ID),
        "task_id":         None,
        "action":          "merge_pull_request",
        "resource":        "github:owner/repo:pr:42",
        "risk_level":      risk_level,
        "requested_by":    uuid.UUID(_USER_ID),
        "decided_by":      None,
        "decision":        decision,
        "reason":          "merge PR42",
        "evidence_id":     None,
        "expires_at":      expires_at,
        "created_at":      datetime.now(timezone.utc),
        "decided_at":      None,
        "status":          status,
    }


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    return pool


# ── request_approval ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_approval_inserts_pending():
    from app.engineering.approvals import ApprovalService

    conn = AsyncMock()
    approval_row = _make_approval_row()
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=approval_row)
    pool = _fake_pool(conn)

    svc = ApprovalService(pool)
    result = await svc.request_approval(
        org_id=_ORG_ID,
        mission_id=_MISSION_ID,
        task_id=None,
        action="merge_pull_request",
        resource="github:owner/repo:pr:42",
        risk_level="high",
        requested_by=_USER_ID,
        reason="merge PR42",
    )
    assert result["status"] == "pending"
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "INSERT INTO eng_approvals" in sql


# ── decide — role enforcement ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decide_rejects_insufficient_role():
    from app.engineering.approvals import ApprovalService, ApprovalPermissionError

    row = _make_approval_row(risk_level="critical")  # critical → owner only

    conn = AsyncMock()
    # Simulate FOR UPDATE lock returning the row
    conn.fetchrow = AsyncMock(return_value=row)
    conn.execute = AsyncMock(return_value=None)

    trans = AsyncMock()
    trans.__aenter__ = AsyncMock(return_value=None)
    trans.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=trans)

    pool = _fake_pool(conn)
    svc = ApprovalService(pool)

    with pytest.raises(ApprovalPermissionError):
        await svc.decide(
            _APPROVAL_ID,
            org_id=_ORG_ID,
            decided_by=_USER_ID,
            decision="approved",
            decider_role="manager",  # not owner
        )


@pytest.mark.asyncio
async def test_decide_allows_owner_for_critical():
    from app.engineering.approvals import ApprovalService

    row = _make_approval_row(risk_level="critical", status="pending")
    after_row = _make_approval_row(risk_level="critical", status="approved", decision="approved")

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[row, after_row])
    conn.execute = AsyncMock(return_value=None)

    trans = AsyncMock()
    trans.__aenter__ = AsyncMock(return_value=None)
    trans.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=trans)

    pool = _fake_pool(conn)
    svc = ApprovalService(pool)

    result = await svc.decide(
        _APPROVAL_ID,
        org_id=_ORG_ID,
        decided_by=_USER_ID,
        decision="approved",
        decider_role="owner",  # allowed
    )
    assert result["status"] == "approved"


@pytest.mark.asyncio
async def test_decide_rejects_expired_approval():
    from app.engineering.approvals import ApprovalService, ApprovalExpiredError

    expired = _make_approval_row(
        risk_level="high",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # expired
    )

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=expired)
    conn.execute = AsyncMock(return_value=None)

    trans = AsyncMock()
    trans.__aenter__ = AsyncMock(return_value=None)
    trans.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=trans)

    pool = _fake_pool(conn)
    svc = ApprovalService(pool)

    with pytest.raises(ApprovalExpiredError):
        await svc.decide(
            _APPROVAL_ID,
            org_id=_ORG_ID,
            decided_by=_USER_ID,
            decision="approved",
            decider_role="admin",
        )


@pytest.mark.asyncio
async def test_decide_rejects_invalid_decision():
    from app.engineering.approvals import ApprovalService

    conn = AsyncMock()
    pool = _fake_pool(conn)
    svc = ApprovalService(pool)

    with pytest.raises(ValueError, match="invalid decision"):
        await svc.decide(
            _APPROVAL_ID,
            org_id=_ORG_ID,
            decided_by=_USER_ID,
            decision="maybe",   # invalid
            decider_role="owner",
        )


# ── _APPROVE_ROLES coverage ───────────────────────────────────────────────────

def test_approve_roles_coverage():
    from app.engineering.approvals import _APPROVE_ROLES
    assert "owner" in _APPROVE_ROLES["critical"]
    assert len(_APPROVE_ROLES["critical"]) == 1
    assert "owner"  in _APPROVE_ROLES["high"]
    assert "admin"  in _APPROVE_ROLES["high"]
    assert "manager" not in _APPROVE_ROLES["high"]
    assert "manager" in _APPROVE_ROLES["medium"]
    assert "operator" in _APPROVE_ROLES["low"]
