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

import pytest

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
            req          = MagicMock()
            req.headers  = {}
            req.client   = MagicMock()
            req.client.host = "127.0.0.1"
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_id",
                       new=AsyncMock(return_value=user_record)), \
                 patch("app.routers.auth_users.verify_password", return_value=verify_ok), \
                 patch("app.routers.auth_users.hash_password",   return_value="hashed-new-pw"), \
                 patch("app.routers.auth_users.write_audit",     new=AsyncMock()), \
                 patch("app.routers.auth_users.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                from app.routers.auth_users import change_password, ChangePasswordRequest
                body    = ChangePasswordRequest(
                    current_password="old-pass",
                    new_password="NewPass123",          # ≥8 chars → passes validator
                )
                current = {"id": str(uid), "email": "alice@example.com"}
                try:
                    result = await change_password(body, current, req)
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
            req          = MagicMock()
            req.headers  = {}
            req.client   = MagicMock()
            req.client.host = "127.0.0.1"
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_id",
                       new=AsyncMock(return_value={
                           "id": uid, "password_hash": "hp",
                           "email_verified": True,
                       })), \
                 patch("app.routers.auth_users.verify_password", return_value=True), \
                 patch("app.routers.auth_users.hash_password",   return_value="new-hp"), \
                 patch("app.routers.auth_users.write_audit",     new=AsyncMock()), \
                 patch("app.routers.auth_users.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                from app.routers.auth_users import change_password, ChangePasswordRequest
                body    = ChangePasswordRequest(
                    current_password="old-pass",
                    new_password="NewPass123",
                )
                current = {"id": str(uid), "email": "alice@example.com"}
                await change_password(body, current, req)

        asyncio.run(_go())

        assert pool.acquire.call_count == 1, (
            "UPDATE and DELETE must share a single connection. "
            f"pool.acquire() was called {pool.acquire.call_count} time(s); "
            "expected exactly 1."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# H4: access-token revocation (logout_all / change_password)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccessTokenRevocation:
    """
    Regression: before this fix, calling logout_all() or change_password()
    deleted refresh tokens from user_sessions but left outstanding JWT access
    tokens valid until their natural 5-minute expiry.  An attacker who stole
    an access token retained API access for up to 5 minutes after the victim
    logged out everywhere or changed their password.

    Expected behaviour after the fix:
      • logout_all()     → revoke_user_tokens(user_id) called (in-process store updated)
      • change_password()→ revoke_user_tokens(user_id) called
      • decode_access_token() on a token issued BEFORE revocation → ExpiredSignatureError
      • decode_access_token() on a token issued AFTER  revocation → succeeds
    """

    _USER_ID = str(uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"))
    _EMAIL   = "bob@example.com"

    def _make_token_at(self, offset_seconds: float = 0.0) -> str:
        """Issue a JWT whose iat is (now + offset_seconds)."""
        import datetime as _dt
        from app.core.jwt_utils import _SECRET, _ALGO
        import jwt as _jwt
        now = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=offset_seconds)
        return _jwt.encode(
            {"sub": self._USER_ID, "email": self._EMAIL, "type": "access",
             "iat": now, "exp": now + _dt.timedelta(minutes=5)},
            _SECRET, algorithm=_ALGO,
        )

    # ── change_password revokes tokens ───────────────────────────────────────

    def test_change_password_revokes_access_tokens(self):
        """
        A token minted BEFORE change_password() must be rejected by
        decode_access_token() immediately after the call completes.
        """
        import jwt as _jwt
        from app.core.jwt_utils import decode_access_token, _revoked_before

        uid  = uuid.UUID(self._USER_ID)
        conn = _make_conn(uid)
        pool = _make_pool(conn)

        old_token = self._make_token_at(-1)  # issued 1s ago

        async def _go():
            with patch("app.routers.auth_users.get_pool",   return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_id",
                       new=AsyncMock(return_value={
                           "id": uid, "password_hash": "hp", "email_verified": True,
                       })), \
                 patch("app.routers.auth_users.verify_password", return_value=True), \
                 patch("app.routers.auth_users.hash_password",   return_value="new-hp"), \
                 patch("app.routers.auth_users.write_audit",     new=AsyncMock()), \
                 patch("app.routers.auth_users.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                req = MagicMock()
                req.headers = {}
                req.client   = MagicMock()
                req.client.host = "127.0.0.1"
                from app.routers.auth_users import change_password, ChangePasswordRequest
                body    = ChangePasswordRequest(current_password="old", new_password="NewPass123")
                current = {"id": str(uid), "email": self._EMAIL}
                await change_password(body, current, req)

        asyncio.run(_go())

        with pytest.raises(_jwt.ExpiredSignatureError):
            decode_access_token(old_token)

    # ── logout_all revokes tokens ─────────────────────────────────────────────

    def test_logout_all_revokes_access_tokens(self):
        """
        A token minted BEFORE logout_all() must be rejected by
        decode_access_token() immediately after the call completes.
        """
        import jwt as _jwt
        from app.core.jwt_utils import decode_access_token

        uid  = uuid.UUID(self._USER_ID)
        conn = _make_conn(uid)
        pool = _make_pool(conn)

        old_token = self._make_token_at(-1)  # issued 1s ago

        async def _go():
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users.write_audit", new=AsyncMock()), \
                 patch("app.routers.auth_users.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                req = MagicMock()
                req.headers = {}
                req.client   = MagicMock()
                req.client.host = "127.0.0.1"
                current = {"id": str(uid), "email": self._EMAIL}
                from app.routers.auth_users import logout_all
                await logout_all(current, req)

        asyncio.run(_go())

        with pytest.raises(_jwt.ExpiredSignatureError):
            decode_access_token(old_token)

    # ── new tokens issued after revocation are valid ──────────────────────────

    def test_token_issued_after_revocation_is_valid(self):
        """
        A token minted AFTER logout_all() must still pass decode_access_token()
        — only the pre-revocation tokens are invalidated.
        """
        import jwt as _jwt
        from app.core.jwt_utils import decode_access_token

        uid  = uuid.UUID(self._USER_ID)
        conn = _make_conn(uid)
        pool = _make_pool(conn)

        async def _go():
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users.write_audit", new=AsyncMock()), \
                 patch("app.routers.auth_users.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                req = MagicMock()
                req.headers = {}
                req.client   = MagicMock()
                req.client.host = "127.0.0.1"
                current = {"id": str(uid), "email": self._EMAIL}
                from app.routers.auth_users import logout_all
                await logout_all(current, req)

        asyncio.run(_go())

        # Token issued AFTER logout_all must be accepted
        new_token = self._make_token_at(+1)  # issued 1s from now
        payload   = decode_access_token(new_token)
        assert payload["sub"] == self._USER_ID


# ═══════════════════════════════════════════════════════════════════════════════
# H5: audit log completeness
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditLogCompleteness:
    """
    Regression: before this fix, logout_all() and change_password() silently
    omitted security-event audit records even though login/register/MFA already
    wrote them.  A stolen-session or password-change incident produced no trace
    in audit_logs that a user or operator could inspect.

    Expected behaviour after the fix:
      • logout_all()     → write_audit called with action "logout_all"
      • change_password()→ write_audit called with action "password.changed"
    """

    _USER_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
    _EMAIL   = "carol@example.com"

    def _make_req(self) -> MagicMock:
        req = MagicMock()
        req.headers = {}
        req.client  = MagicMock()
        req.client.host = "10.0.0.1"
        return req

    def test_logout_all_writes_audit(self):
        conn = _make_conn(self._USER_ID)
        pool = _make_pool(conn)
        audit_mock = AsyncMock()

        async def _go():
            with patch("app.routers.auth_users.get_pool",    return_value=pool), \
                 patch("app.routers.auth_users.write_audit",  audit_mock), \
                 patch("app.routers.auth_users.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock(side_effect=lambda coro: coro)
                current = {"id": str(self._USER_ID), "email": self._EMAIL}
                from app.routers.auth_users import logout_all
                await logout_all(current, self._make_req())

        asyncio.run(_go())

        audit_mock.assert_called_once()
        call_args = audit_mock.call_args
        assert call_args.args[1] == "logout_all", (
            f"write_audit action must be 'logout_all'; got {call_args.args[1]!r}"
        )

    def test_change_password_writes_audit(self):
        conn = _make_conn(self._USER_ID)
        pool = _make_pool(conn)
        audit_mock = AsyncMock()

        async def _go():
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_id",
                       new=AsyncMock(return_value={
                           "id": self._USER_ID, "password_hash": "hp",
                           "email_verified": True,
                       })), \
                 patch("app.routers.auth_users.verify_password", return_value=True), \
                 patch("app.routers.auth_users.hash_password",   return_value="new-hp"), \
                 patch("app.routers.auth_users.write_audit",  audit_mock), \
                 patch("app.routers.auth_users.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock(side_effect=lambda coro: coro)
                from app.routers.auth_users import change_password, ChangePasswordRequest
                body    = ChangePasswordRequest(current_password="old", new_password="NewPass123")
                current = {"id": str(self._USER_ID), "email": self._EMAIL}
                await change_password(body, current, self._make_req())

        asyncio.run(_go())

        audit_mock.assert_called_once()
        call_args = audit_mock.call_args
        assert call_args.args[1] == "password.changed", (
            f"write_audit action must be 'password.changed'; got {call_args.args[1]!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# H6: per-email login lockout
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoginLockout:
    """
    Regression: before this fix, an attacker could try unlimited passwords
    against any account — only the per-IP global rate limit (300/min) applied,
    which is far too permissive for a credential-stuffing or brute-force attack.

    Expected behaviour after the fix:
      • Failed logins increment a per-email counter (window = 15 min).
      • After 5 failures the endpoint returns 429 immediately, before any DB
        query, so the attacker cannot enumerate whether the account exists.
      • A successful login resets the counter so legitimate users aren't
        permanently blocked.
    """

    _EMAIL = "dave@example.com"

    def _make_req(self) -> MagicMock:
        req = MagicMock()
        req.headers = {}
        req.client  = MagicMock()
        req.client.host = "1.2.3.4"
        return req

    def _make_login_body(self, password: str = "wrong"):
        from app.routers.auth_users import LoginRequest
        return LoginRequest(email=self._EMAIL, password=password)

    # ── counter increments on bad password ───────────────────────────────────

    def test_failed_login_increments_counter(self):
        """
        record_login_failure_async must be called when the password is wrong.
        """
        from app.core.rate_limit import rl_store

        key = f"login_fail:{self._EMAIL}"
        rl_store.pop(key, None)  # clean slate

        user_row = {
            "id": uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
            "password_hash": "hp",
            "email_verified": True,
        }
        conn = _make_conn(user_row["id"])
        pool = _make_pool(conn)

        async def _go():
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_email",
                       new=AsyncMock(return_value=user_row)), \
                 patch("app.routers.auth_users.verify_password", return_value=False), \
                 patch("app.routers.auth_users.check_login_locked_async",
                       new=AsyncMock(return_value=False)), \
                 patch("app.routers.auth_users.record_login_failure_async") as rec_mock:
                rec_mock_async = AsyncMock()
                rec_mock.side_effect = rec_mock_async
                req = self._make_req()
                from app.routers.auth_users import login
                try:
                    await login(self._make_login_body("wrong"), req)
                except Exception:
                    pass
                rec_mock.assert_called_once()
                call_email = rec_mock.call_args.args[0]
                assert call_email.lower() == self._EMAIL.lower()

        asyncio.run(_go())

    # ── locked after 5 failures ───────────────────────────────────────────────

    def test_account_locked_after_five_failures(self):
        """
        After 5 failed attempts check_login_locked_async returns True and the
        endpoint raises 429 before touching the DB.
        """
        conn = _make_conn(uuid.UUID("dddddddd-0000-0000-0000-000000000004"))
        pool = _make_pool(conn)

        async def _go():
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users.check_login_locked_async",
                       new=AsyncMock(return_value=True)):
                req = self._make_req()
                from fastapi import HTTPException as _HTTPException
                from app.routers.auth_users import login
                try:
                    await login(self._make_login_body(), req)
                    assert False, "Expected HTTPException(429)"
                except _HTTPException as exc:
                    assert exc.status_code == 429, f"Expected 429, got {exc.status_code}"
                    # DB must NOT have been queried
                    pool.acquire.assert_not_called()

        asyncio.run(_go())

    # ── successful login clears counter ──────────────────────────────────────

    def test_successful_login_clears_counter(self):
        """
        clear_login_failures_async must be called after a correct password.
        """
        from app.core.rate_limit import rl_store

        key = f"login_fail:{self._EMAIL}"
        rl_store[key] = [__import__("time").time()]  # seed one failure

        user_id = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
        user_row = {
            "id": user_id,
            "password_hash": "hp",
            "email_verified": True,
            "email": self._EMAIL,
            "full_name": "Dave",
            "avatar_url": None,
            "provider": None,
            "mfa_enabled": False,
            "created_at": __import__("datetime").datetime.utcnow(),
        }
        conn = _make_conn(user_id)
        pool = _make_pool(conn)

        mfa_row = None

        async def _mock_fetchrow(sql, *args):
            if "mfa_secrets" in sql:
                return mfa_row
            if "user_sessions" in sql.lower() or "INSERT" in sql:
                return {"id": uuid.uuid4(), "token": "rt", "expires_at":
                        __import__("datetime").datetime.utcnow()}
            return None

        conn.fetchrow = AsyncMock(side_effect=_mock_fetchrow)

        async def _go():
            with patch("app.routers.auth_users.get_pool", return_value=pool), \
                 patch("app.routers.auth_users._get_user_by_email",
                       new=AsyncMock(return_value=user_row)), \
                 patch("app.routers.auth_users.verify_password", return_value=True), \
                 patch("app.routers.auth_users.check_login_locked_async",
                       new=AsyncMock(return_value=False)), \
                 patch("app.routers.auth_users.clear_login_failures_async") as clr_mock, \
                 patch("app.routers.auth_users._finish_login",
                       new=AsyncMock(return_value={"access_token": "tok"})):
                clr_mock_async = AsyncMock()
                clr_mock.side_effect = clr_mock_async
                req = self._make_req()
                from app.routers.auth_users import login
                await login(self._make_login_body("correct"), req)
                clr_mock.assert_called_once()
                call_email = clr_mock.call_args.args[0]
                assert call_email.lower() == self._EMAIL.lower()

        asyncio.run(_go())
