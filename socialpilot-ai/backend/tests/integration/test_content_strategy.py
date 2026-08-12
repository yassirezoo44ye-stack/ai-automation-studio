"""Content Strategy CRUD + pillar CRUD, and their tenant-isolation boundary."""
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


def _auth(user: dict) -> dict:
    return {"Authorization": f"Bearer {user['access_token']}"}


async def _create_strategy(client, user: dict, **overrides) -> dict:
    payload = {
        "name": "AI Tools Brand",
        "business_description": "We sell AI productivity tools.",
        "target_audience": "Startup founders",
        "goals": "Grow brand awareness",
        "tone": "professional",
        "language": "english",
        "brand_voice": "confident, concise",
        "content_preferences": {"platforms": ["x", "linkedin"]},
        **overrides,
    }
    r = await client.post(f"/api/v1/organizations/{user['org_id']}/content/strategies", json=payload, headers=_auth(user))
    assert r.status_code == 201, r.text
    return r.json()


class TestStrategyCrud:
    async def test_create_strategy(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        assert strategy["name"] == "AI Tools Brand"
        assert strategy["organization_id"] == user["org_id"]
        assert strategy["content_preferences"] == {"platforms": ["x", "linkedin"]}

    async def test_create_strategy_applies_defaults(self, client) -> None:
        user = await _register(client, org="Acme")
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/strategies",
            json={"name": "Minimal Strategy"},
            headers=_auth(user),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["tone"] == "engaging"
        assert body["language"] == "english"
        assert body["business_description"] == ""

    async def test_create_strategy_rejects_empty_name(self, client) -> None:
        user = await _register(client, org="Acme")
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/strategies",
            json={"name": ""},
            headers=_auth(user),
        )
        assert r.status_code == 422

    async def test_create_strategy_rejects_oversized_field(self, client) -> None:
        user = await _register(client, org="Acme")
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/strategies",
            json={"name": "X", "business_description": "a" * 5000},
            headers=_auth(user),
        )
        assert r.status_code == 422

    async def test_list_strategies(self, client) -> None:
        user = await _register(client, org="Acme")
        await _create_strategy(client, user, name="Strategy 1")
        await _create_strategy(client, user, name="Strategy 2")
        r = await client.get(f"/api/v1/organizations/{user['org_id']}/content/strategies", headers=_auth(user))
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_get_strategy(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}", headers=_auth(user)
        )
        assert r.status_code == 200
        assert r.json()["id"] == strategy["id"]

    async def test_get_nonexistent_strategy_returns_404(self, client) -> None:
        user = await _register(client, org="Acme")
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/00000000-0000-0000-0000-000000000000",
            headers=_auth(user),
        )
        assert r.status_code == 404

    async def test_update_strategy_partial(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.patch(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}",
            json={"tone": "playful"},
            headers=_auth(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["tone"] == "playful"
        assert body["name"] == strategy["name"]  # untouched fields preserved

    async def test_delete_strategy(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.delete(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}", headers=_auth(user)
        )
        assert r.status_code == 204
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}", headers=_auth(user)
        )
        assert r.status_code == 404

    async def test_unauthenticated_request_rejected(self, client) -> None:
        user = await _register(client, org="Acme")
        r = await client.get(f"/api/v1/organizations/{user['org_id']}/content/strategies")
        assert r.status_code == 401


class TestPillarCrud:
    async def test_create_pillar(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}/pillars",
            json={"name": "AI Tools", "description": "Tool roundups", "priority": 5},
            headers=_auth(user),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "AI Tools"
        assert body["strategy_id"] == strategy["id"]

    async def test_list_pillars(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        for name in ("AI Tools", "AI News", "Tips"):
            await client.post(
                f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}/pillars",
                json={"name": name}, headers=_auth(user),
            )
        r = await client.get(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}/pillars",
            headers=_auth(user),
        )
        assert r.status_code == 200
        assert len(r.json()) == 3

    async def test_update_pillar(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        created = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}/pillars",
            json={"name": "AI Tools"}, headers=_auth(user),
        )
        pillar_id = created.json()["id"]
        r = await client.patch(
            f"/api/v1/organizations/{user['org_id']}/content/pillars/{pillar_id}",
            json={"priority": 9}, headers=_auth(user),
        )
        assert r.status_code == 200
        assert r.json()["priority"] == 9

    async def test_delete_pillar(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        created = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}/pillars",
            json={"name": "AI Tools"}, headers=_auth(user),
        )
        pillar_id = created.json()["id"]
        r = await client.delete(
            f"/api/v1/organizations/{user['org_id']}/content/pillars/{pillar_id}", headers=_auth(user)
        )
        assert r.status_code == 204

    async def test_deleting_strategy_cascades_to_pillars(self, client) -> None:
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        created = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}/pillars",
            json={"name": "AI Tools"}, headers=_auth(user),
        )
        pillar_id = created.json()["id"]
        await client.delete(f"/api/v1/organizations/{user['org_id']}/content/strategies/{strategy['id']}", headers=_auth(user))
        r = await client.patch(
            f"/api/v1/organizations/{user['org_id']}/content/pillars/{pillar_id}",
            json={"priority": 1}, headers=_auth(user),
        )
        assert r.status_code == 404


class TestContentTenantIsolation:
    async def test_user_cannot_read_foreign_org_strategy(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        strategy = await _create_strategy(client, owner_a)

        r = await client.get(
            f"/api/v1/organizations/{owner_a['org_id']}/content/strategies/{strategy['id']}", headers=_auth(user_b)
        )
        assert r.status_code == 404

    async def test_user_cannot_update_foreign_org_strategy(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        strategy = await _create_strategy(client, owner_a)

        r = await client.patch(
            f"/api/v1/organizations/{owner_a['org_id']}/content/strategies/{strategy['id']}",
            json={"name": "Hijacked"}, headers=_auth(user_b),
        )
        assert r.status_code == 404

    async def test_user_cannot_delete_foreign_org_strategy(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        strategy = await _create_strategy(client, owner_a)

        r = await client.delete(
            f"/api/v1/organizations/{owner_a['org_id']}/content/strategies/{strategy['id']}", headers=_auth(user_b)
        )
        assert r.status_code == 404
        # Confirm it wasn't actually deleted despite the attempt.
        r = await client.get(
            f"/api/v1/organizations/{owner_a['org_id']}/content/strategies/{strategy['id']}", headers=_auth(owner_a)
        )
        assert r.status_code == 200

    async def test_strategy_list_never_leaks_across_orgs(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        owner_b = await _register(client, org="Org B")
        await _create_strategy(client, owner_a, name="A's strategy")
        await _create_strategy(client, owner_b, name="B's strategy")

        r = await client.get(f"/api/v1/organizations/{owner_a['org_id']}/content/strategies", headers=_auth(owner_a))
        names = [s["name"] for s in r.json()]
        assert names == ["A's strategy"]

    async def test_user_cannot_add_pillar_to_foreign_org_strategy(self, client) -> None:
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        strategy = await _create_strategy(client, owner_a)

        r = await client.post(
            f"/api/v1/organizations/{owner_a['org_id']}/content/strategies/{strategy['id']}/pillars",
            json={"name": "Hijack Pillar"}, headers=_auth(user_b),
        )
        assert r.status_code == 404

    async def test_using_org_a_credentials_with_org_b_id_in_url_is_rejected(self, client) -> None:
        """The strongest form of the attack: an authenticated member of org A
        tries to act on org B's URL — must fail at require_org_member(), not
        merely at the strategy lookup."""
        owner_a = await _register(client, org="Org A")
        owner_b = await _register(client, org="Org B")
        strategy_b = await _create_strategy(client, owner_b)

        r = await client.get(
            f"/api/v1/organizations/{owner_b['org_id']}/content/strategies/{strategy_b['id']}", headers=_auth(owner_a)
        )
        assert r.status_code == 404


class TestPillarRbac:
    async def test_viewer_cannot_create_pillar(self, client, db_session) -> None:
        import uuid as uuidlib

        from app.models.organization_member import OrganizationMember, OrganizationRole

        owner = await _register(client, org="Acme")
        strategy = await _create_strategy(client, owner)
        viewer = await _register(client, org="Viewer's own org")

        member = OrganizationMember(
            organization_id=uuidlib.UUID(owner["org_id"]), user_id=uuidlib.UUID(
                (await client.get("/api/v1/auth/me", headers=_auth(viewer))).json()["user"]["id"]
            ),
            role=OrganizationRole.VIEWER,
        )
        db_session.add(member)
        await db_session.commit()

        r = await client.post(
            f"/api/v1/organizations/{owner['org_id']}/content/strategies/{strategy['id']}/pillars",
            json={"name": "Should fail"}, headers=_auth(viewer),
        )
        assert r.status_code == 403
