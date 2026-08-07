"""
Real-PostgreSQL tenant-boundary tests — Testing Foundation P0-1/P0-2.

Every test here runs against a real, ephemeral Postgres database (see
conftest.py) — no asyncpg mocking. Two independent verification angles,
both required per docs/testing-foundation-p0.md:

  1. Application-layer correctness through TenancyService (does the right
     SQL get written/read for the right org).
  2. Database-layer enforcement through Row Level Security itself (does
     Postgres refuse to return/modify another org's row even when a
     query has no organization_id filter at all) — this is the layer
     every purely-mocked test in the rest of the suite cannot reach.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════════════════════
# Harness sanity — prove the harness itself talks to real PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════════

class TestHarnessIsReal:
    async def test_pool_is_a_real_asyncpg_connection(self, pg_pool):
        import asyncpg
        assert isinstance(pg_pool, asyncpg.Pool)
        async with pg_pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
        assert "PostgreSQL" in version

    async def test_app_role_is_not_superuser(self, pg_pool):
        """The whole point of this harness is that RLS is meaningfully
        enforced — that's only true if the connecting role is not a
        superuser (Postgres superusers bypass RLS unconditionally)."""
        async with pg_pool.acquire() as conn:
            is_super = await conn.fetchval(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            )
        assert is_super is False

    async def test_schema_and_rls_were_really_applied(self, pg_pool):
        async with pg_pool.acquire() as conn:
            tables = {
                r["table_name"] for r in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'"
                )
            }
            rls_enabled = await conn.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE relname='organization_members'"
            )
            rls_forced = await conn.fetchval(
                "SELECT relforcerowsecurity FROM pg_class WHERE relname='organization_members'"
            )
        assert {"users", "organizations", "organization_members", "role_permissions"} <= tables
        assert rls_enabled is True
        assert rls_forced is True


# ═══════════════════════════════════════════════════════════════════════════════
# TenancyService through the real DB — own-org success, cross-org denial
# ═══════════════════════════════════════════════════════════════════════════════

class TestTenancyServiceRealDB:
    async def test_owner_has_own_org_role(self, two_orgs):
        role = await two_orgs["svc"].get_member_role(two_orgs["org_a"], two_orgs["user_a"])
        assert role == "owner"

    async def test_user_a_is_not_a_member_of_org_b(self, two_orgs):
        role = await two_orgs["svc"].get_member_role(two_orgs["org_b"], two_orgs["user_a"])
        assert role is None

    async def test_has_permission_uses_real_role_permissions_table(self, two_orgs):
        """owner has ("*","*") seeded by init_tenancy_schema -- real row,
        not a mock return value."""
        allowed = await two_orgs["svc"].has_permission(
            two_orgs["org_a"], two_orgs["user_a"], resource="billing", action="manage",
        )
        assert allowed is True

    async def test_has_permission_denies_non_member(self, two_orgs):
        allowed = await two_orgs["svc"].has_permission(
            two_orgs["org_b"], two_orgs["user_a"], resource="billing", action="manage",
        )
        assert allowed is False

    async def test_unknown_org_id_returns_no_role_not_an_error(self, two_orgs):
        role = await two_orgs["svc"].get_member_role(str(uuid.uuid4()), two_orgs["user_a"])
        assert role is None


# ═══════════════════════════════════════════════════════════════════════════════
# Row Level Security itself — cross-tenant denial with NO application-layer
# WHERE clause at all. This is the layer no mocked test can reach.
# ═══════════════════════════════════════════════════════════════════════════════

class TestRowLevelSecurityEnforcement:
    async def test_scoped_connection_cannot_read_other_orgs_row_with_no_where_clause(self, two_orgs):
        """The strongest possible RLS proof: an unqualified SELECT with NO
        organization_id filter at all, run through a connection scoped to
        org A via acquire_scoped(), must still only return org A's rows —
        proving the database itself enforces the boundary, independent of
        whether the calling Python code remembered to add a WHERE clause."""
        from app.core.db import acquire_scoped

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM organization_members")

        seen_orgs = {str(r["organization_id"]) for r in rows}
        assert seen_orgs == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen_orgs

    async def test_scoped_connection_cannot_read_other_orgs_row_reverse(self, two_orgs):
        from app.core.db import acquire_scoped

        async with acquire_scoped(two_orgs["org_b"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM organization_members")

        seen_orgs = {str(r["organization_id"]) for r in rows}
        assert seen_orgs == {two_orgs["org_b"]}
        assert two_orgs["org_a"] not in seen_orgs

    async def test_scoped_connection_cannot_update_other_orgs_row(self, two_orgs):
        """UPDATE targeting org B's member row while scoped to org A must
        affect zero rows -- RLS's USING clause hides the row from the
        UPDATE's own WHERE matching before it ever runs."""
        from app.core.db import acquire_scoped

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            result = await conn.execute(
                "UPDATE organization_members SET role='owner' "
                "WHERE organization_id=$1", uuid.UUID(two_orgs["org_b"]),
            )
        assert result == "UPDATE 0"

        # Confirm org B's row is genuinely untouched (scoped to B this time).
        async with acquire_scoped(two_orgs["org_b"]) as conn:
            role = await conn.fetchval(
                "SELECT role FROM organization_members WHERE organization_id=$1 AND user_id=$2",
                uuid.UUID(two_orgs["org_b"]), uuid.UUID(two_orgs["user_b"]),
            )
        assert role == "owner"  # unchanged from creation — not overwritten twice

    async def test_scoped_connection_cannot_delete_other_orgs_row(self, two_orgs):
        from app.core.db import acquire_scoped

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            result = await conn.execute(
                "DELETE FROM organization_members WHERE organization_id=$1",
                uuid.UUID(two_orgs["org_b"]),
            )
        assert result == "DELETE 0"

        async with acquire_scoped(two_orgs["org_b"]) as conn:
            still_there = await conn.fetchval(
                "SELECT 1 FROM organization_members WHERE organization_id=$1 AND user_id=$2",
                uuid.UUID(two_orgs["org_b"]), uuid.UUID(two_orgs["user_b"]),
            )
        assert still_there == 1

    async def test_own_org_write_still_succeeds(self, two_orgs):
        """Negative-only test coverage would be incomplete — confirm RLS
        doesn't accidentally block legitimate same-org writes too."""
        from app.core.db import acquire_scoped

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            result = await conn.execute(
                "UPDATE organizations SET plan='pro' WHERE id=$1",
                uuid.UUID(two_orgs["org_a"]),
            )
        assert result == "UPDATE 1"

    async def test_unscoped_connection_sees_everything_by_design(self, two_orgs):
        """RLS here is additive defense-in-depth, not the primary access
        control (see app/tenancy/rls.py's own docstring) — a plain,
        never-scoped connection is intentionally NOT restricted. This
        test documents that design choice as a real, verified behavior
        rather than an assumption."""
        async with two_orgs["pool"].acquire() as conn:
            rows = await conn.fetch("SELECT organization_id FROM organization_members")
        seen_orgs = {str(r["organization_id"]) for r in rows}
        assert {two_orgs["org_a"], two_orgs["org_b"]} <= seen_orgs
