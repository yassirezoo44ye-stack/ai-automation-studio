"""Real-PostgreSQL RLS coverage — `plugin_installations`, `sandbox_workers`,
`sandbox_events` (remaining gap, docs/testing-foundation-p0.md §12).

Real FK chain: marketplace_items -> plugin_installations -> sandbox_workers
-> sandbox_events. Every row below is inserted through that real chain
(not stubbed), same "no WHERE clause" RLS-proof rigor as every other
table in this package.
"""
from __future__ import annotations

import time
import uuid

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def marketplace_item(two_orgs):
    item_id = f"item-{uuid.uuid4().hex[:10]}"
    async with two_orgs["pool"].acquire() as conn:
        await conn.execute(
            "INSERT INTO marketplace_items (id, name, type, description, created_at, updated_at) "
            "VALUES ($1, $2, 'plugin', 'test item', $3, $3)",
            item_id, "Test Item", time.time(),
        )
    return item_id


async def _install_plugin(pool, marketplace_item: str, org_id: str) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO plugin_installations "
            "(organization_id, marketplace_item_id, plugin_id, version) "
            "VALUES ($1,$2,$3,'1.0.0') RETURNING id",
            uuid.UUID(org_id), marketplace_item, f"plugin-{uuid.uuid4().hex[:8]}",
        )
    return str(row["id"])


class TestPluginInstallationsTenantIsolation:
    async def test_plugin_installations_rls_backed_no_where_clause(self, two_orgs, marketplace_item):
        from app.core.db import acquire_scoped

        await _install_plugin(two_orgs["pool"], marketplace_item, two_orgs["org_a"])
        await _install_plugin(two_orgs["pool"], marketplace_item, two_orgs["org_b"])

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM plugin_installations WHERE marketplace_item_id=$1",
                marketplace_item,
            )
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen


class TestSandboxWorkersAndEventsTenantIsolation:
    async def test_sandbox_workers_rls_backed_no_where_clause(self, two_orgs, marketplace_item):
        from app.core.db import acquire_scoped

        install_a = await _install_plugin(two_orgs["pool"], marketplace_item, two_orgs["org_a"])
        install_b = await _install_plugin(two_orgs["pool"], marketplace_item, two_orgs["org_b"])
        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO sandbox_workers (organization_id, plugin_installation_id, backend) "
                "VALUES ($1,$2,'process')",
                uuid.UUID(two_orgs["org_a"]), uuid.UUID(install_a),
            )
            await conn.execute(
                "INSERT INTO sandbox_workers (organization_id, plugin_installation_id, backend) "
                "VALUES ($1,$2,'process')",
                uuid.UUID(two_orgs["org_b"]), uuid.UUID(install_b),
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM sandbox_workers "
                "WHERE plugin_installation_id = ANY($1::uuid[])",
                [uuid.UUID(install_a), uuid.UUID(install_b)],
            )
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_sandbox_events_rls_backed_no_where_clause(self, two_orgs, marketplace_item):
        from app.core.db import acquire_scoped

        install_a = await _install_plugin(two_orgs["pool"], marketplace_item, two_orgs["org_a"])
        install_b = await _install_plugin(two_orgs["pool"], marketplace_item, two_orgs["org_b"])
        async with two_orgs["pool"].acquire() as conn:
            worker_a = await conn.fetchval(
                "INSERT INTO sandbox_workers (organization_id, plugin_installation_id, backend) "
                "VALUES ($1,$2,'process') RETURNING id",
                uuid.UUID(two_orgs["org_a"]), uuid.UUID(install_a),
            )
            worker_b = await conn.fetchval(
                "INSERT INTO sandbox_workers (organization_id, plugin_installation_id, backend) "
                "VALUES ($1,$2,'process') RETURNING id",
                uuid.UUID(two_orgs["org_b"]), uuid.UUID(install_b),
            )
            await conn.execute(
                "INSERT INTO sandbox_events (worker_id, organization_id, event_type) "
                "VALUES ($1,$2,'lifecycle')", worker_a, uuid.UUID(two_orgs["org_a"]),
            )
            await conn.execute(
                "INSERT INTO sandbox_events (worker_id, organization_id, event_type) "
                "VALUES ($1,$2,'lifecycle')", worker_b, uuid.UUID(two_orgs["org_b"]),
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM sandbox_events WHERE worker_id = ANY($1::uuid[])",
                [worker_a, worker_b],
            )
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_sandbox_router_owned_worker_lookup_rejects_cross_tenant(self, two_orgs, marketplace_item):
        """app/routers/sandbox.py's own documented pattern (Security
        Boundary Sweep verdict: Safe) is _get_owned_worker(id, org_id) on
        every route -- verify the underlying query it relies on directly:
        a worker created for org A is not found when looked up scoped to
        org B, even with the real (guessable) worker id."""
        install_a = await _install_plugin(two_orgs["pool"], marketplace_item, two_orgs["org_a"])
        async with two_orgs["pool"].acquire() as conn:
            worker_a = await conn.fetchval(
                "INSERT INTO sandbox_workers (organization_id, plugin_installation_id, backend) "
                "VALUES ($1,$2,'process') RETURNING id",
                uuid.UUID(two_orgs["org_a"]), uuid.UUID(install_a),
            )

        from app.core.db import acquire_scoped
        async with acquire_scoped(two_orgs["org_b"]) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sandbox_workers WHERE id=$1 AND organization_id=$2",
                worker_a, uuid.UUID(two_orgs["org_b"]),
            )
        assert row is None
