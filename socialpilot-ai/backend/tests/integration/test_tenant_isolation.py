"""Cross-tenant access must be impossible, not merely discouraged.

Every one of these asserts that a user who is not a member of an organization
gets the exact same response (404) as if the organization didn't exist at all
— no distinguishable "403 forbidden, but I confirmed it exists" leak (IDOR
hardening), and no data from org A ever appears in a response scoped to org B.
"""
from __future__ import annotations

import pytest

from tests.conftest import unique_email

pytestmark = pytest.mark.asyncio


async def _register(client, *, org: str):
    email = unique_email()
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret1", "full_name": "User", "organization_name": org},
    )
    assert r.status_code == 201
    body = r.json()
    return {
        "email": email,
        "access_token": body["access_token"],
        "org_id": body["organizations"][0]["id"],
    }


class TestTenantIsolation:
    async def test_user_cannot_read_a_foreign_organization(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")

        r = await client.get(
            f"/api/v1/organizations/{owner_a['org_id']}",
            headers={"Authorization": f"Bearer {user_b['access_token']}"},
        )
        assert r.status_code == 404

    async def test_user_cannot_list_members_of_a_foreign_organization(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")

        r = await client.get(
            f"/api/v1/organizations/{owner_a['org_id']}/members",
            headers={"Authorization": f"Bearer {user_b['access_token']}"},
        )
        assert r.status_code == 404

    async def test_user_cannot_rename_a_foreign_organization(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")

        r = await client.patch(
            f"/api/v1/organizations/{owner_a['org_id']}",
            headers={"Authorization": f"Bearer {user_b['access_token']}"},
            json={"name": "Hijacked"},
        )
        assert r.status_code == 404

    async def test_nonexistent_organization_returns_404_not_401(self, client) -> None:
        user = await _register(client, org="Org A")
        r = await client.get(
            "/api/v1/organizations/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user['access_token']}"},
        )
        assert r.status_code == 404

    async def test_my_organizations_only_lists_orgs_i_belong_to(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        owner_b = await _register(client, org="Org B")

        r = await client.get(
            "/api/v1/organizations", headers={"Authorization": f"Bearer {owner_a['access_token']}"}
        )
        assert r.status_code == 200
        org_ids = {o["id"] for o in r.json()}
        assert owner_a["org_id"] in org_ids
        assert owner_b["org_id"] not in org_ids

    async def test_each_registration_gets_its_own_isolated_organization(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        owner_b = await _register(client, org="Org B")
        assert owner_a["org_id"] != owner_b["org_id"]
