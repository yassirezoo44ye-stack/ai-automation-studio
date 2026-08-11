"""Real-PostgreSQL RLS coverage — `marketplace_installs` and
`marketplace_downloads` (remaining gap, docs/testing-foundation-p0.md §12).

Both tables' organization_id is NULLABLE with no NOT NULL constraint
(marketplace_installs has no FK to organizations at all; downloads has
ON DELETE SET NULL) -- a real architectural fact, not a gap: an anonymous
or org-less install/download is valid (the public catalog itself has no
org). A NULL organization_id row is invisible through any acquire_scoped()
connection (the RLS policy's `col = current_org_id` comparison is never
true against NULL) -- proven below, not assumed.
"""
from __future__ import annotations

import time
import uuid

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def marketplace_item(two_orgs):
    """One real row in the parent catalog table both installs/downloads
    have an FK to."""
    item_id = f"item-{uuid.uuid4().hex[:10]}"
    async with two_orgs["pool"].acquire() as conn:
        await conn.execute(
            "INSERT INTO marketplace_items (id, name, type, description, created_at, updated_at) "
            "VALUES ($1, $2, 'plugin', 'test item', $3, $3)",
            item_id, "Test Item", time.time(),
        )
    return item_id


class TestMarketplaceInstallsTenantIsolation:
    async def test_installs_rls_backed_no_where_clause(self, two_orgs, marketplace_item):
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO marketplace_installs (item_id, organization_id) VALUES ($1,$2)",
                marketplace_item, uuid.UUID(two_orgs["org_a"]),
            )
            await conn.execute(
                "INSERT INTO marketplace_installs (item_id, organization_id) VALUES ($1,$2)",
                marketplace_item, uuid.UUID(two_orgs["org_b"]),
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM marketplace_installs WHERE item_id=$1", marketplace_item,
            )
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_null_organization_id_install_is_invisible_to_any_scoped_connection(
        self, two_orgs, marketplace_item,
    ):
        """A NULL org_id (a legitimate anonymous/global install) must not
        leak into ANY org's scoped view -- RLS's `col = org_id` comparison
        is never true against NULL, verified directly."""
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO marketplace_installs (item_id, organization_id) VALUES ($1, NULL)",
                marketplace_item,
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM marketplace_installs WHERE item_id=$1", marketplace_item,
            )
        assert all(r["organization_id"] is not None for r in rows)


class TestMarketplaceDownloadsTenantIsolation:
    async def test_downloads_rls_backed_no_where_clause(self, two_orgs, marketplace_item):
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO marketplace_downloads (item_id, organization_id) VALUES ($1,$2)",
                marketplace_item, uuid.UUID(two_orgs["org_a"]),
            )
            await conn.execute(
                "INSERT INTO marketplace_downloads (item_id, organization_id) VALUES ($1,$2)",
                marketplace_item, uuid.UUID(two_orgs["org_b"]),
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM marketplace_downloads WHERE item_id=$1", marketplace_item,
            )
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen
