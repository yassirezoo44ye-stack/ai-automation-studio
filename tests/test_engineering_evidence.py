"""
Tests: EvidenceStore — write-once records, SHA match, verify/fail lifecycle,
has_verified_deploy gate.

Uses a lightweight fake pool to avoid a live database.
"""
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_pool(fetchrow_return=None, fetchval_return=None):
    """Return a minimal pool mock that supports acquire() as async context."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetchval = AsyncMock(return_value=fetchval_return)
    conn.fetch = AsyncMock(return_value=[])

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    pool._conn = conn
    return pool


# ── record() ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_inserts_row():
    from app.engineering.evidence import EvidenceStore
    pool = _fake_pool()
    store = EvidenceStore(pool)
    ev_id = await store.record(
        org_id="00000000-0000-0000-0000-000000000001",
        mission_id="00000000-0000-0000-0000-000000000002",
        task_id=None,
        provider="render",
        operation="trigger_deploy",
        tool_name="render.trigger_deploy",
        inputs_hash="abc123",
        outputs_summary={"deploy_id": "dep-xyz"},
        verification_status="unverified",
    )
    assert len(ev_id) == 36  # UUID format
    pool._conn.execute.assert_called_once()
    call_sql = pool._conn.execute.call_args[0][0]
    assert "INSERT INTO eng_evidence" in call_sql


@pytest.mark.asyncio
async def test_record_computes_sha_match_when_both_present():
    from app.engineering.evidence import EvidenceStore
    pool = _fake_pool()
    store = EvidenceStore(pool)
    # Same SHA → sha_match=True
    await store.record(
        org_id="00000000-0000-0000-0000-000000000001",
        mission_id="00000000-0000-0000-0000-000000000002",
        task_id=None,
        provider="render",
        operation="verify_deploy",
        tool_name="render.verify_deploy",
        inputs_hash="abc",
        outputs_summary={},
        requested_sha="abc123def",
        observed_sha="abc123def",
    )
    # The sha_match=True should be passed as the 14th positional arg
    args = pool._conn.execute.call_args[0]
    # sha_match is the last positional arg
    assert args[-1] is True


@pytest.mark.asyncio
async def test_record_sha_mismatch():
    from app.engineering.evidence import EvidenceStore
    pool = _fake_pool()
    store = EvidenceStore(pool)
    await store.record(
        org_id="00000000-0000-0000-0000-000000000001",
        mission_id="00000000-0000-0000-0000-000000000002",
        task_id=None,
        provider="render",
        operation="verify_deploy",
        tool_name="render.verify_deploy",
        inputs_hash="abc",
        outputs_summary={},
        requested_sha="requested_sha_xxx",
        observed_sha="different_sha_yyy",
    )
    args = pool._conn.execute.call_args[0]
    assert args[-1] is False   # sha_match=False


# ── has_verified_deploy() ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_has_verified_deploy_true_when_no_deploys():
    from app.engineering.evidence import EvidenceStore

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=0)  # deploy_count = 0
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    store = EvidenceStore(pool)
    result = await store.has_verified_deploy(
        "00000000-0000-0000-0000-000000000002",
        org_id="00000000-0000-0000-0000-000000000001",
    )
    assert result is True


@pytest.mark.asyncio
async def test_has_verified_deploy_false_when_unverified():
    from app.engineering.evidence import EvidenceStore

    call_count = 0
    async def _fetchval(sql, *args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 1   # deploy_count = 1
        return 1       # unverified_count = 1

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=_fetchval)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    store = EvidenceStore(pool)
    result = await store.has_verified_deploy(
        "00000000-0000-0000-0000-000000000002",
        org_id="00000000-0000-0000-0000-000000000001",
    )
    assert result is False


@pytest.mark.asyncio
async def test_has_verified_deploy_true_when_all_verified():
    from app.engineering.evidence import EvidenceStore

    call_count = 0
    async def _fetchval(sql, *args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 2   # 2 deploys
        return 0       # 0 unverified → all verified

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=_fetchval)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    store = EvidenceStore(pool)
    result = await store.has_verified_deploy(
        "00000000-0000-0000-0000-000000000002",
        org_id="00000000-0000-0000-0000-000000000001",
    )
    assert result is True
