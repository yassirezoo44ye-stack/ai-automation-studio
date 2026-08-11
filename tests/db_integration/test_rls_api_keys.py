"""Real-PostgreSQL RLS coverage — `api_keys` (remaining gap,
docs/testing-foundation-p0.md §12).

lookup_key() (app/core/api_keys.py) deliberately runs on the plain,
unscoped pool — not acquire_scoped() — same asymmetric-but-documented
pattern as credits.grant()/payment_methods.sync_for_org(), and for a
structural reason specific to this table: API-key authentication happens
BEFORE any org context exists (the key's own organization_id row is what
*establishes* which org a request is scoped to downstream in
require_api_key()), so there is no org_id to scope by yet at lookup time.
Not a demonstrated vulnerability — lookup is by key_hash (effectively a
unique credential), not by an attacker-suppliable org_id.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


class TestApiKeysTenantIsolation:
    async def test_api_keys_rls_backed_no_where_clause(self, two_orgs):
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, name, organization_id) "
                "VALUES ($1,$2,'Org A key',$3)",
                uuid.uuid4().hex[:32], uuid.uuid4().hex, uuid.UUID(two_orgs["org_a"]),
            )
            await conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, name, organization_id) "
                "VALUES ($1,$2,'Org B key',$3)",
                uuid.uuid4().hex[:32], uuid.uuid4().hex, uuid.UUID(two_orgs["org_b"]),
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM api_keys")
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_null_organization_id_key_is_invisible_to_any_scoped_connection(self, two_orgs):
        """A NULL organization_id is a legitimate system/cross-org admin key
        (see app/routers/usage_api.py's admin-scoped routes) -- must not
        leak into any single org's scoped view."""
        from app.core.db import acquire_scoped

        key_id = uuid.uuid4().hex[:32]
        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, name, organization_id) "
                "VALUES ($1,$2,'System key',NULL)", key_id, uuid.uuid4().hex,
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            row = await conn.fetchrow("SELECT * FROM api_keys WHERE key_id=$1", key_id)
        assert row is None

    async def test_lookup_key_resolves_the_correct_orgs_key_by_hash(self, two_orgs):
        """lookup_key() is unscoped by design (see module docstring) -- prove
        it still round-trips the right organization_id for the key
        presented, which is what require_api_key() then trusts for
        downstream org-scoped authorization."""
        from app.core.api_keys import lookup_key, _hash, _PREFIX

        raw_key = f"{_PREFIX}{uuid.uuid4().hex}"
        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, name, organization_id, scopes) "
                "VALUES ($1,$2,'Org A key',$3,$4)",
                raw_key[:32], _hash(raw_key), uuid.UUID(two_orgs["org_a"]), ["read"],
            )

        record = await lookup_key(raw_key)
        assert record is not None
        assert record.organization_id == two_orgs["org_a"]

    async def test_lookup_key_ignores_soft_deleted_keys(self, two_orgs):
        from app.core.api_keys import lookup_key, _hash, _PREFIX

        raw_key = f"{_PREFIX}{uuid.uuid4().hex}"
        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, name, organization_id, deleted_at) "
                "VALUES ($1,$2,'Revoked key',$3,NOW())",
                raw_key[:32], _hash(raw_key), uuid.UUID(two_orgs["org_a"]),
            )

        record = await lookup_key(raw_key)
        assert record is None
