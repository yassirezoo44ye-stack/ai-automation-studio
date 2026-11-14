"""GET /api/orgs gives a brand-new user a personal workspace.

Without one, every org-scoped page (Teams, Billing, Devices, SaaS Factory…)
fails with "Missing organization context" for new accounts.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.routers.auth_users import get_current_user  # noqa: E402
from app.routers.organizations import router  # noqa: E402

_ORG = {
    "id": "11111111-1111-1111-1111-111111111111", "name": "Personal workspace",
    "slug": "personal-workspace", "kind": "personal", "plan": "free",
    "settings": {}, "my_role": "owner",
    "created_at": MagicMock(isoformat=lambda: "2026-10-16T00:00:00+00:00"),
}


def _client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "aaaaaaaa-0000-0000-0000-000000000001", "email": "new@example.com",
    }
    return TestClient(app)


def test_new_user_gets_personal_workspace():
    svc = MagicMock()
    svc.list_organizations_for_user = AsyncMock(side_effect=[[], [], [_ORG]])
    svc.create_organization = AsyncMock(return_value=_ORG)
    with patch("app.routers.organizations.get_tenancy_service", return_value=svc):
        res = _client().get("/api/orgs")
    assert res.status_code == 200
    assert [o["kind"] for o in res.json()["organizations"]] == ["personal"]
    svc.create_organization.assert_awaited_once()
    assert svc.create_organization.await_args.kwargs["kind"] == "personal"


def test_existing_member_gets_no_extra_workspace():
    svc = MagicMock()
    svc.list_organizations_for_user = AsyncMock(return_value=[_ORG])
    svc.create_organization = AsyncMock()
    with patch("app.routers.organizations.get_tenancy_service", return_value=svc):
        res = _client().get("/api/orgs")
    assert res.status_code == 200
    svc.create_organization.assert_not_awaited()
