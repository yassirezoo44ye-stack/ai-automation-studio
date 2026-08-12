"""Content Item (library) CRUD and tenant isolation."""
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
    return {"email": email, "access_token": body["access_token"], "org_id": body["organizations"][0]["id"]}


def _auth(user: dict) -> dict:
    return {"Authorization": f"Bearer {user['access_token']}"}


async def _create_item(client, user: dict, **overrides) -> dict:
    payload = {
        "platform": "x",
        "title": "Launch day",
        "body": "We just shipped a new feature!",
        "hashtags": ["ai", "launch"],
        "metadata": {"hook": "Big news"},
        **overrides,
    }
    r = await client.post(f"/api/v1/organizations/{user['org_id']}/content/items", json=payload, headers=_auth(user))
    assert r.status_code == 201, r.text
    return r.json()


class TestItemCrud:
    async def test_create_item(self, client) -> None:
        user = await _register(client, org="Acme")
        item = await _create_item(client, user)
        assert item["platform"] == "x"
        assert item["status"] == "draft"
        assert item["metadata"] == {"hook": "Big news"}
        assert item["organization_id"] == user["org_id"]

    async def test_create_item_never_returns_raw_html_unescaped_differently(self, client) -> None:
        # Body is stored/returned as plain JSON text — this test documents
        # that no server-side HTML rendering happens; the frontend is
        # responsible for treating it as untrusted text (never innerHTML).
        user = await _register(client, org="Acme")
        item = await _create_item(client, user, body="<script>alert(1)</script>")
        assert item["body"] == "<script>alert(1)</script>"  # stored verbatim, not sanitized/escaped server-side

    async def test_list_items(self, client) -> None:
        user = await _register(client, org="Acme")
        await _create_item(client, user, title="One")
        await _create_item(client, user, title="Two")
        r = await client.get(f"/api/v1/organizations/{user['org_id']}/content/items", headers=_auth(user))
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_list_items_filters_by_platform(self, client) -> None:
        user = await _register(client, org="Acme")
        await _create_item(client, user, platform="x")
        await _create_item(client, user, platform="linkedin")
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/items?platform=linkedin", headers=_auth(user)
        )
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["platform"] == "linkedin"

    async def test_get_item(self, client) -> None:
        user = await _register(client, org="Acme")
        item = await _create_item(client, user)
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/items/{item['id']}", headers=_auth(user)
        )
        assert r.status_code == 200

    async def test_update_item(self, client) -> None:
        user = await _register(client, org="Acme")
        item = await _create_item(client, user)
        r = await client.patch(
            f"/api/v1/organizations/{user['org_id']}/content/items/{item['id']}",
            json={"status": "approved", "body": "Updated body"}, headers=_auth(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "approved"
        assert body["body"] == "Updated body"

    async def test_delete_item(self, client) -> None:
        user = await _register(client, org="Acme")
        item = await _create_item(client, user)
        r = await client.delete(
            f"/api/v1/organizations/{user['org_id']}/content/items/{item['id']}", headers=_auth(user)
        )
        assert r.status_code == 204
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/items/{item['id']}", headers=_auth(user)
        )
        assert r.status_code == 404

    async def test_get_nonexistent_item_returns_404(self, client) -> None:
        user = await _register(client, org="Acme")
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/items/00000000-0000-0000-0000-000000000000",
            headers=_auth(user),
        )
        assert r.status_code == 404


class TestItemTenantIsolation:
    async def test_user_cannot_read_foreign_org_item(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        item = await _create_item(client, owner_a)

        r = await client.get(
            f"/api/v1/organizations/{owner_a['org_id']}/content/items/{item['id']}", headers=_auth(user_b)
        )
        assert r.status_code == 404

    async def test_user_cannot_update_foreign_org_item(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        item = await _create_item(client, owner_a)

        r = await client.patch(
            f"/api/v1/organizations/{owner_a['org_id']}/content/items/{item['id']}",
            json={"body": "Hijacked"}, headers=_auth(user_b),
        )
        assert r.status_code == 404

    async def test_user_cannot_delete_foreign_org_item(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        item = await _create_item(client, owner_a)

        r = await client.delete(
            f"/api/v1/organizations/{owner_a['org_id']}/content/items/{item['id']}", headers=_auth(user_b)
        )
        assert r.status_code == 404

    async def test_item_list_never_leaks_across_orgs(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        owner_b = await _register(client, org="Org B")
        await _create_item(client, owner_a, title="A's item")
        await _create_item(client, owner_b, title="B's item")

        r = await client.get(f"/api/v1/organizations/{owner_a['org_id']}/content/items", headers=_auth(owner_a))
        titles = [i["title"] for i in r.json()]
        assert titles == ["A's item"]
