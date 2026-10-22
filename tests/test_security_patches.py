"""
Security patch regression tests — Phase 2.

Covers two targeted fixes applied in this batch:

  H1-ownership  job_ws() must reject a cross-org WebSocket connection (4403)
                even after the identity check passes.  An authenticated user
                from org-A must never receive data from a job owned by org-B.

  H3            change_password() must DELETE FROM user_sessions after
                updating the password, matching reset_password()'s behaviour.
                A stolen refresh token must not remain valid after the owner
                changes their password.

Design notes
------------
* All tests run without a live database; every DB/network call is mocked.
* os.environ.setdefault() is called at module level, before any app import,
  so DATABASE_URL / SESSION_SECRET are always present when the app loads.
* asyncio.run() is used instead of pytest-asyncio so the suite is portable
  and consistent with the existing tests/security/ conventions.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


# ── shared test fixtures ─────────────────────────────────────────────────────

def _make_ws() -> MagicMock:
    """Minimal WebSocket mock (close is async)."""
    ws       = MagicMock()
    ws.close = AsyncMock()
    return ws


def _make_job(org_id: str | None, status: str = "running") -> MagicMock:
    """Return a mock Job object with the given org and terminal/non-terminal status."""
    job              = MagicMock()
    job.payload      = {"organization_id": org_id} if org_id else {}
    job.status       = MagicMock()
    job.status.value = status
    job.progress     = 0
    job.log_lines    = []
    job.result       = None
    job.error        = None
    job.to_dict      = MagicMock(return_value={"status": status})
    return job


def _make_conn(user_id: uuid.UUID, password_hash: str = "hashed-old-pw") -> MagicMock:
    """Async-capable DB connection mock."""
    conn          = MagicMock()
    conn.execute  = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "id": user_id, "email": "alice@example.com",
        "name": "Alice", "password_hash": password_hash,
        "email_verified": True, "avatar_url": None, "created_at": None,
    })
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    """Pool whose .acquire() is a working async context manager."""
    ctx             = MagicMock()
    ctx.__aenter__  = AsyncMock(return_value=conn)
    ctx.__aexit__   = AsyncMock(return_value=False)
    pool            = MagicMock()
    pool.acquire    = MagicMock(return_value=ctx)
    return pool


# ═══════════════════════════════════════════════════════════════════════════════
# H1-ownership: job_ws cross-org rejection
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobWsCrossOrgRejection:
    """
    Regression: before this fix job_ws() authenticated the caller but never
    verified that the job belongs to the caller's organisation. Any logged-in
    user who guessed a job_id UUID could subscribe to any job's progress
    stream regardless of ownership.

    Expected behaviour after the fix:
      • org mismatch → ws.close(code=4403, reason="not authorized for this job")
      • job data (snapshot / progress frames) is never sent to the requester
      • same-org callers and jobs without an org_id are not affected
    """

    def _run(
        self,
        *,
        user_id: str,
        job_id: str,
        job: MagicMock,
        member_role: str | None,
    ) -> MagicMock:
        """
        Invoke job_ws() with fully mocked I/O; return the WebSocket mock so
        the caller can assert on close calls and data frames.
        """
        ws = _make_ws()

        mock_svc             = MagicMock()
        mock_svc.get_member_role = AsyncMock(return_value=member_role)

        mock_queue     = MagicMock()
        mock_queue.get = AsyncMock(return_value=job)

        async def _go():
            with patch("app.routers.ws._user_id_from_ws_params", return_value=user_id), \
                 patch("app.routers.ws.manager") as mgr, \
                 patch("app.core.jobs.get_job_queue", return_value=mock_queue), \
                 patch("app.tenancy.service.get_tenancy_service", return_value=mock_svc), \
                 patch("app.routers.ws._heartbeat", new=AsyncMock()):
                mgr.connect    = AsyncMock()
                mgr.send       = AsyncMock()
                mgr.disconnect = MagicMock()
                from app.routers.ws import job_ws
                await job_ws(ws, job_id)

        asyncio.run(_go())
        return ws

    # ── core regression ───────────────────────────────────────────────────────

    def test_job_ws_cross_org_rejection(self):
        """
        Org-A user connecting to an org-B job must be rejected with 4403
        and must never receive any job data.
        """
        job = _make_job(org_id="org-b", status="running")
        ws  = self._run(user_id="user-a", job_id="job-owned-by-b",
                        job=job, member_role=None)

        ws.close.assert_called_once_with(
            code=4403, reason="not authorized for this job",
        )

    def test_cross_org_rejected_before_snapshot_is_sent(self):
        """
        The 4403 rejection must happen before job.to_dict() data leaves the
        server — snapshot must NOT be sent to the unauthorised caller.
        """
        job = _make_job(org_id="org-b", status="running")
        ws  = self._run(user_id="user-a", job_id="job-owned-by-b",
                        job=job, member_role=None)

        # to_dict() must never have been called (data never prepared for send)
        job.to_dict.assert_not_called()

    # ── authorised access remains intact ──────────────────────────────────────

    def test_same_org_member_is_not_rejected(self):
        """
        An authenticated member of the same org must not receive a 4403
        close frame.
        """
        job = _make_job(org_id="org-a", status="completed")
        ws  = self._run(user_id="user-a", job_id="job-owned-by-a",
                        job=job, member_role="member")

        for c in ws.close.call_args_list:
            assert c.kwargs.get("code") != 4403, (
                "A legitimate org member was wrongly rejected with 4403"
            )

    def test_job_without_org_id_skips_ownership_check(self):
        """
        Jobs that carry no organization_id in their payload (internal /
        legacy jobs) must remain accessible to any authenticated caller —
        the ownership check must be skipped when job_org is falsy.
        """
        job = _make_job(org_id=None, status="completed")
        ws  = self._run(user_id="user-x", job_id="internal-job",
                        job=job, member_role=None)

        for c in ws.close.call_args_list:
            assert c.kwargs.get("code") != 4403

    # ── unauthenticated access still blocked ──────────────────────────────────

    def test_unauthenticated_connection_still_rejected_4401(self):
        """
        No ticket / expired token → 4401.  The first auth gate must still fire
        even after the ownership check was added.
        """
        ws = _make_ws()

        async def _go():
            # No other mocks needed — the function returns before any DB call
            with patch("app.routers.ws._user_id_from_ws_params", return_value=None):
                from app.routers.ws import job_ws
                await job_ws(ws, "any-job-id")

        asyncio.run(_go())
        ws.close.assert_called_once_with(code=4401, reason="unauthorized")


# ═══════════════════════════════════════════════════════════════════════════════
# H3: change_password() session invalidation
# ═══════════════════════════════════════════════════════════════════════════════

class TestChangePasswordClearsSessions:
    """
    Regression: before this fix change_password() only updated the
    password_hash row and returned.  An attacker who obtained a valid refresh
    token (e.g. via session hijacking or a leaked cookie) could continue to
    refresh access tokens indefinitely even after the account holder changed
    their password.

    reset_password() already deleted all sessions.  This fix brings
    change_password() into parity.

    Expected behaviour after the fix:
      • successful password change → UPDATE users + DELETE user_sessions
      • both operations share a single DB connection (no gap between them)
      • wrong current password → no DB writes at all
    """

    _USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

    def _run(
        self,
        *,
        verify_ok: bool = True,
        user_exists: bool = True,
    ) -> tuple[MagicMock, dict | None]:
        """
        Invoke change_password() with mocked DB and crypto helpers.
        Returns (conn, result) where result is None if an exception was raised.
        """
        from fastapi import HTTPException

        uid  = self._USER_ID
        conn = _make_conn(uid) if user_exists else MagicMock(execute=AsyncMock(),
                                                              fetchrow=AsyncMock())
        pool = _make_pool(conn)

        user_record = (
            {"id": uid, "password_hash": "hashed-old-pw", "email_verified": True}
            if user_exists else None
        )

        result: dict | None = None

        async def _go():
            nonlocal result
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_id",
                       new=AsyncMock(return_value=user_record)), \
                 patch("app.routers.auth_users.verify_password", return_value=verify_ok), \
                 patch("app.routers.auth_users.hash_password",
                       return_value="hashed-new-pw"):
                from app.routers.auth_users import change_password, ChangePasswordRequest
                body    = ChangePasswordRequest(
                    current_password="old-pass",
                    new_password="NewPass123",          # ≥8 chars → passes validator
                )
                current = {"id": str(uid), "email": "alice@example.com"}
                try:
                    result = await change_password(body, current)
                except HTTPException:
                    pass

        asyncio.run(_go())
        return conn, result

    # ── core regression ───────────────────────────────────────────────────────

    def test_change_password_clears_sessions(self):
        """
        A successful password change must trigger exactly two execute() calls:
        1. UPDATE users SET password_hash=…
        2. DELETE FROM user_sessions WHERE user_id=…
        """
        conn, result = self._run(verify_ok=True)

        assert result == {"message": "Password changed successfully"}
        assert conn.execute.await_count == 2, (
            f"Expected 2 execute() calls (UPDATE + DELETE), "
            f"got {conn.execute.await_count}. "
            "change_password() must DELETE FROM user_sessions after the "
            "password update — stolen refresh tokens must not stay valid."
        )

    def test_session_delete_targets_correct_user(self):
        """
        The DELETE statement must reference the authenticated user's UUID,
        not a literal, a different user's id, or a string.
        """
        conn, _ = self._run(verify_ok=True)

        calls  = conn.execute.await_args_list
        assert len(calls) >= 2, "Expected at least 2 execute() calls"

        delete_call = calls[1]
        sql         = delete_call.args[0] if delete_call.args else ""
        param       = delete_call.args[1] if len(delete_call.args) > 1 else None

        assert "DELETE" in sql.upper() and "user_sessions" in sql, (
            f"Second execute() must be DELETE FROM user_sessions; got: {sql!r}"
        )
        assert param == self._USER_ID, (
            f"DELETE must target user {self._USER_ID}, got {param!r}"
        )

    def test_session_delete_follows_password_update(self):
        """
        The UPDATE must precede the DELETE — sessions must not be wiped
        before the new password is committed.
        """
        conn, _ = self._run(verify_ok=True)
        calls   = conn.execute.await_args_list

        update_sql = calls[0].args[0] if calls[0].args else ""
        delete_sql = calls[1].args[0] if len(calls) > 1 and calls[1].args else ""

        assert "UPDATE" in update_sql.upper() and "users" in update_sql, (
            f"First execute() must be UPDATE users; got: {update_sql!r}"
        )
        assert "DELETE" in delete_sql.upper() and "user_sessions" in delete_sql, (
            f"Second execute() must be DELETE user_sessions; got: {delete_sql!r}"
        )

    # ── wrong-password guard ──────────────────────────────────────────────────

    def test_wrong_current_password_does_not_clear_sessions(self):
        """
        If verify_password() fails, the handler raises 400 before any DB
        write — neither the UPDATE nor the DELETE must execute.
        """
        conn, result = self._run(verify_ok=False)
        assert result is None, "Expected an HTTPException to have been raised"
        conn.execute.assert_not_called()

    # ── transactional integrity ───────────────────────────────────────────────

    def test_update_and_delete_share_one_connection(self):
        """
        Both the UPDATE and the DELETE must run on the same DB connection
        (inside one `async with conn` block).  Using two separate connections
        leaves a window where a refresh succeeds after the password update
        but before the sessions are deleted.
        """
        uid  = self._USER_ID
        conn = _make_conn(uid)
        pool = _make_pool(conn)

        async def _go():
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_id",
                       new=AsyncMock(return_value={
                           "id": uid, "password_hash": "hp",
                           "email_verified": True,
                       })), \
                 patch("app.routers.auth_users.verify_password", return_value=True), \
                 patch("app.routers.auth_users.hash_password", return_value="new-hp"):
                from app.routers.auth_users import change_password, ChangePasswordRequest
                body    = ChangePasswordRequest(
                    current_password="old-pass",
                    new_password="NewPass123",
                )
                current = {"id": str(uid), "email": "alice@example.com"}
                await change_password(body, current)

        asyncio.run(_go())

        assert pool.acquire.call_count == 1, (
            "UPDATE and DELETE must share a single connection. "
            f"pool.acquire() was called {pool.acquire.call_count} time(s); "
            "expected exactly 1."
        )
