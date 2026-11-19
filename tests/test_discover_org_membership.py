"""Discover acts only on organizations the caller belongs to.

The X-Organization-Id header used to be trusted as-is, so any signed-in
account could list, edit, delete or publish another organization's private
creations by naming its id (ids appear in the public feed).
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.routers import discover


class _Req:
    def __init__(self, org: str | None):
        self.headers = {"X-Organization-Id": org} if org else {}


def _run(org, role, uid="11111111-1111-1111-1111-111111111111"):
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=uid)
    svc = MagicMock()
    svc.get_member_role = AsyncMock(return_value=role)
    with patch("app.core.auth.owner_email", return_value="alice@example.test"), \
         patch.object(discover, "get_pool", return_value=pool), \
         patch("app.tenancy.service.get_tenancy_service", return_value=svc):
        return asyncio.run(discover._verified_org_id(_Req(org))), svc


def test_member_gets_their_org():
    org, svc = _run("org-a", "viewer")
    assert org == "org-a"
    svc.get_member_role.assert_awaited_once_with("org-a", "11111111-1111-1111-1111-111111111111")


def test_non_member_gets_404_for_someone_elses_org():
    with pytest.raises(HTTPException) as err:
        _run("org-b", None)
    assert err.value.status_code == 404


def test_unknown_account_gets_404():
    with pytest.raises(HTTPException) as err:
        _run("org-a", "owner", uid=None)
    assert err.value.status_code == 404


def test_missing_header_is_400():
    with pytest.raises(HTTPException) as err:
        _run(None, "owner")
    assert err.value.status_code == 400
