"""
Real-PostgreSQL RLS edge cases — Testing Foundation P0-2 (continued).

Two angles not covered by test_tenancy_rls.py's core positive/negative
pairs:

  1. Session/transaction-local GUC leak across a pooled connection being
     reused for a different organization (or no organization at all) —
     the specific failure mode app/core/db.py::acquire_scoped()'s own
     docstring and app/tenancy/rls.py's nullif(...,'') comment are
     written to guard against, never previously exercised against a real
     connection pool.
  2. The full request/auth-context -> TenancyService -> DB -> RLS chain
     through app.tenancy.context.org_context() itself, not just
     TenancyService called directly — only the auth/JWT identity
     resolution step is mocked (a separate, already-covered concern —
     see tests/test_auth.py / tests/security/test_authentication.py);
     everything from org_context() onward, including the real RLS
     policy evaluation, is real.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

pytestmark = pytest.mark.asyncio


def _fake_request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http", "method": "GET", "path": "/",
        "headers": raw_headers, "query_string": b"",
    }
    return Request(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Session/connection GUC leak — pool reuse across orgs and unscoped callers
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionContextDoesNotLeakAcrossPooledConnections:
    async def test_guc_does_not_leak_from_scoped_to_unscoped_on_same_physical_connection(
        self, pg_test_database_url,
    ):
        """max_size=1 forces the pool to hand out the SAME physical
        connection for both acquisitions below — the only way to prove
        the tenant GUC really resets is to force reuse, not hope for it."""
        import asyncpg
        from app.core import db as db_module

        pool = await asyncpg.create_pool(pg_test_database_url, min_size=1, max_size=1)
        previous_pool = db_module._pool
        db_module.set_pool(pool)
        try:
            from app.core.db import acquire_scoped

            async with acquire_scoped(str(uuid.uuid4())) as conn:
                during = await conn.fetchval(
                    "SELECT current_setting('app.current_org_id', true)"
                )
            assert during  # a real org_id string was set during the scoped block

            # Next acquisition — guaranteed same physical connection (pool
            # size 1) — must NOT still see the previous org_id.
            async with pool.acquire() as conn:
                after = await conn.fetchval(
                    "SELECT current_setting('app.current_org_id', true)"
                )
            assert after in (None, ""), (
                f"tenant GUC leaked into an unscoped connection reuse: {after!r}"
            )
        finally:
            db_module.set_pool(previous_pool)
            await pool.close()

    async def test_guc_does_not_leak_between_two_different_orgs_on_same_connection(
        self, pg_test_database_url,
    ):
        import asyncpg
        from app.core import db as db_module

        pool = await asyncpg.create_pool(pg_test_database_url, min_size=1, max_size=1)
        previous_pool = db_module._pool
        db_module.set_pool(pool)
        try:
            from app.core.db import acquire_scoped

            org_a, org_b = str(uuid.uuid4()), str(uuid.uuid4())

            async with acquire_scoped(org_a) as conn:
                seen_a = await conn.fetchval("SELECT current_setting('app.current_org_id', true)")
            assert seen_a == org_a

            # Same physical connection (pool size 1), different org this time.
            async with acquire_scoped(org_b) as conn:
                seen_b = await conn.fetchval("SELECT current_setting('app.current_org_id', true)")
            assert seen_b == org_b
            assert seen_b != seen_a
        finally:
            db_module.set_pool(previous_pool)
            await pool.close()

    async def test_rls_policy_treats_reset_empty_string_same_as_unscoped(self, two_orgs):
        """The specific edge case app/tenancy/rls.py's policy comment
        calls out: a pooled connection that has EVER run acquire_scoped()
        resets the GUC to '' (not NULL) once its transaction ends. A
        plain SELECT on that same connection afterward, with no
        acquire_scoped() wrapping it, must not start erroring or start
        seeing zero rows — nullif(...,'') IS NULL must treat '' the same
        as truly-never-set."""
        from app.core.db import acquire_scoped

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            pass  # touch the GUC, then let the transaction end and reset it

        async with two_orgs["pool"].acquire() as conn:
            # Same connection object is not guaranteed here (pool may be
            # larger than 1), but across repeated acquisitions on a small
            # pool it very likely is — either way this must succeed and
            # see both orgs (unscoped = defense-in-depth no-op, by design).
            rows = await conn.fetch("SELECT organization_id FROM organization_members")
        seen = {str(r["organization_id"]) for r in rows}
        assert {two_orgs["org_a"], two_orgs["org_b"]} <= seen


# ═══════════════════════════════════════════════════════════════════════════════
# Full chain: request/auth context -> org_context() -> TenancyService -> DB -> RLS
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrgContextFullChainRealDB:
    async def test_org_context_resolves_real_membership_for_own_org(self, two_orgs):
        from app.tenancy.context import org_context

        request = _fake_request({"X-Organization-Id": two_orgs["org_a"]})
        with patch(
            "app.tenancy.context.get_current_user",
            return_value={"id": two_orgs["user_a"], "email": "a@example.com"},
        ):
            ctx = await org_context(request, user={"id": two_orgs["user_a"], "email": "a@example.com"})

        assert ctx.org_id == two_orgs["org_a"]
        assert ctx.role == "owner"

    async def test_org_context_404s_for_non_member_not_403(self, two_orgs):
        """Matches the convention verified throughout the tenant-boundary
        sweep: a non-member gets 404, not 403, so they can't distinguish
        'wrong org' from 'doesn't exist' -- this is org_context() itself
        enforcing it, backed by a real DB row (or lack of one)."""
        from app.tenancy.context import org_context

        request = _fake_request({"X-Organization-Id": two_orgs["org_b"]})
        with pytest.raises(HTTPException) as exc_info:
            await org_context(request, user={"id": two_orgs["user_a"], "email": "a@example.com"})
        assert exc_info.value.status_code == 404

    async def test_org_context_missing_header_is_400(self, two_orgs):
        from app.tenancy.context import org_context

        request = _fake_request({})
        with pytest.raises(HTTPException) as exc_info:
            await org_context(request, user={"id": two_orgs["user_a"], "email": "a@example.com"})
        assert exc_info.value.status_code == 400

    async def test_require_permission_denies_viewer_role_for_manage_action(self, two_orgs):
        """A second real member, added with a low-privilege role, must be
        denied a 'manage' action by the real role_permissions table --
        not a mocked permission set."""
        from app.tenancy.context import require_permission

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO organization_members (organization_id, user_id, role) "
                "VALUES ($1,$2,'viewer')",
                uuid.UUID(two_orgs["org_a"]), uuid.UUID(two_orgs["user_b"]),
            )

        dep = require_permission("billing", "manage")
        from app.tenancy.context import OrgContext
        viewer_ctx = OrgContext(
            org_id=two_orgs["org_a"], user_id=two_orgs["user_b"],
            user_email="b@example.com", role="viewer",
        )
        with pytest.raises(HTTPException) as exc_info:
            await dep(ctx=viewer_ctx)
        assert exc_info.value.status_code == 403
