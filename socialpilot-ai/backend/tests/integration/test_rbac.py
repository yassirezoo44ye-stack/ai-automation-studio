"""Role-based access control on organization-scoped endpoints.

`PATCH /organizations/{id}` is gated to owner/admin (see
`app/api/v1/organizations.py::rename_organization`); editor/viewer must be
able to *read* but never *write*.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.organization_member import OrganizationMember, OrganizationRole
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
        "user_id": body["user"]["id"],
        "org_id": body["organizations"][0]["id"],
    }


async def _add_member(db_session, *, organization_id: str, user_id: str, role: OrganizationRole) -> None:
    member = OrganizationMember(
        organization_id=uuid.UUID(organization_id), user_id=uuid.UUID(user_id), role=role
    )
    db_session.add(member)
    await db_session.commit()


class TestOrganizationRbac:
    async def test_owner_can_rename_organization(self, client) -> None:
        owner = await _register(client, org="Acme")
        r = await client.patch(
            f"/api/v1/organizations/{owner['org_id']}",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json={"name": "Acme Renamed"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Acme Renamed"

    async def test_admin_can_rename_organization(self, client, db_session) -> None:
        owner = await _register(client, org="Acme")
        admin = await _register(client, org="Admin's own org")
        await _add_member(
            db_session, organization_id=owner["org_id"], user_id=admin["user_id"], role=OrganizationRole.ADMIN
        )

        r = await client.patch(
            f"/api/v1/organizations/{owner['org_id']}",
            headers={"Authorization": f"Bearer {admin['access_token']}"},
            json={"name": "Renamed by admin"},
        )
        assert r.status_code == 200

    async def test_editor_cannot_rename_organization(self, client, db_session) -> None:
        owner = await _register(client, org="Acme")
        editor = await _register(client, org="Editor's own org")
        await _add_member(
            db_session,
            organization_id=owner["org_id"],
            user_id=editor["user_id"],
            role=OrganizationRole.EDITOR,
        )

        r = await client.patch(
            f"/api/v1/organizations/{owner['org_id']}",
            headers={"Authorization": f"Bearer {editor['access_token']}"},
            json={"name": "Hijacked by editor"},
        )
        assert r.status_code == 403

    async def test_viewer_cannot_rename_organization(self, client, db_session) -> None:
        owner = await _register(client, org="Acme")
        viewer = await _register(client, org="Viewer's own org")
        await _add_member(
            db_session,
            organization_id=owner["org_id"],
            user_id=viewer["user_id"],
            role=OrganizationRole.VIEWER,
        )

        r = await client.patch(
            f"/api/v1/organizations/{owner['org_id']}",
            headers={"Authorization": f"Bearer {viewer['access_token']}"},
            json={"name": "Hijacked by viewer"},
        )
        assert r.status_code == 403

    async def test_viewer_can_still_read_organization(self, client, db_session) -> None:
        owner = await _register(client, org="Acme")
        viewer = await _register(client, org="Viewer's own org")
        await _add_member(
            db_session,
            organization_id=owner["org_id"],
            user_id=viewer["user_id"],
            role=OrganizationRole.VIEWER,
        )

        r = await client.get(
            f"/api/v1/organizations/{owner['org_id']}",
            headers={"Authorization": f"Bearer {viewer['access_token']}"},
        )
        assert r.status_code == 200

    async def test_editor_can_list_members(self, client, db_session) -> None:
        owner = await _register(client, org="Acme")
        editor = await _register(client, org="Editor's own org")
        await _add_member(
            db_session,
            organization_id=owner["org_id"],
            user_id=editor["user_id"],
            role=OrganizationRole.EDITOR,
        )

        r = await client.get(
            f"/api/v1/organizations/{owner['org_id']}/members",
            headers={"Authorization": f"Bearer {editor['access_token']}"},
        )
        assert r.status_code == 200
        assert len(r.json()) == 2  # owner + editor
