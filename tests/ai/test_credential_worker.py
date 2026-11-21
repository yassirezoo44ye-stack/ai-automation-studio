import pytest
from app.ai import credential_worker as worker

@pytest.mark.asyncio
async def test_worker_skips_unavailable_scope(monkeypatch):
    async def no_claim(*a, **k): return None
    monkeypatch.setattr(worker, "claim_checkpoint", no_claim)
    assert await worker.rotate_and_verify_scope(object(), org_id="org", user_id="user") == {
        "claimed": False, "verified": False}

@pytest.mark.asyncio
async def test_worker_verifies_before_marking_success(monkeypatch):
    calls = []
    async def claim(*a, **k): calls.append("claim"); return "token"
    async def rotate(*a, **k): calls.append("rotate"); return {"scanned": 1, "rotated": 1}
    async def verify(*a, **k): calls.append("verify"); return {"scanned": 1, "complete": True}
    async def finish(*a, **k): calls.append("finish"); return True
    monkeypatch.setattr(worker, "claim_checkpoint", claim)
    monkeypatch.setattr(worker, "rotate_user_credentials", rotate)
    monkeypatch.setattr(worker, "verify_user_primary_key", verify)
    monkeypatch.setattr(worker, "finish_checkpoint", finish)
    assert (await worker.rotate_and_verify_scope(object(), org_id="org", user_id="user"))["verified"]
    assert calls == ["claim", "rotate", "verify", "finish"]

@pytest.mark.asyncio
@pytest.mark.parametrize("scanned,complete,verified_count", [(0, True, 0), (1, False, 1), (1, True, 0)])
async def test_worker_rejects_incomplete_verification(monkeypatch, scanned, complete, verified_count):
    async def claim(*a, **k): return "token"
    async def rotate(*a, **k): return {"scanned": scanned, "rotated": scanned}
    async def verify(*a, **k): return {"scanned": verified_count, "complete": complete}
    async def finish(*a, **k): raise AssertionError("must not finish")
    monkeypatch.setattr(worker, "claim_checkpoint", claim)
    monkeypatch.setattr(worker, "rotate_user_credentials", rotate)
    monkeypatch.setattr(worker, "verify_user_primary_key", verify)
    monkeypatch.setattr(worker, "finish_checkpoint", finish)
    with pytest.raises(RuntimeError, match="roll back"):
        await worker.rotate_and_verify_scope(object(), org_id="org", user_id="user")

@pytest.mark.asyncio
async def test_worker_entrypoint_owns_scoped_transaction(monkeypatch):
    from contextlib import asynccontextmanager
    calls = []
    @asynccontextmanager
    async def scope(conn, *, org_id, user_id):
        calls.append("begin")
        try:
            yield conn
        except Exception:
            calls.append("rollback")
            raise
        else:
            calls.append("commit")
    async def execute(conn, *, org_id, user_id):
        calls.append("execute")
        return {"claimed": True, "verified": True}
    monkeypatch.setattr(worker, "scoped_credential_transaction", scope)
    monkeypatch.setattr(worker, "rotate_and_verify_scope", execute)
    await worker.run_scoped_rotation(object(), org_id="org", user_id="user")
    assert calls == ["begin", "execute", "commit"]

@pytest.mark.asyncio
async def test_worker_entrypoint_propagates_failure_for_rollback(monkeypatch):
    from contextlib import asynccontextmanager
    calls = []
    @asynccontextmanager
    async def scope(conn, *, org_id, user_id):
        calls.append("begin")
        try:
            yield conn
        except RuntimeError:
            calls.append("rollback")
            raise
    async def execute(conn, *, org_id, user_id):
        raise RuntimeError("rotation failed")
    monkeypatch.setattr(worker, "scoped_credential_transaction", scope)
    monkeypatch.setattr(worker, "rotate_and_verify_scope", execute)
    with pytest.raises(RuntimeError, match="rotation failed"):
        await worker.run_scoped_rotation(object(), org_id="org", user_id="user")
    assert calls == ["begin", "rollback"]
