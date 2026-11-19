"""Role management respects rank on both sides.

change_member_role only checked the actor's own rank, so an admin could
demote the owner (and then remove them). create_invitation accepted any
non-owner role, so a manager could invite their own address as admin and
accept it.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.tenancy.service import TenancyError, TenancyService

ORG = "00000000-0000-0000-0000-0000000000aa"
ACTOR = "00000000-0000-0000-0000-000000000001"
TARGET = "00000000-0000-0000-0000-000000000002"


def _svc(roles: dict[str, str]) -> TenancyService:
    svc = TenancyService.__new__(TenancyService)
    svc._pool = MagicMock()
    svc.get_member_role = AsyncMock(side_effect=lambda org, uid: roles.get(uid))
    svc._check_seat_capacity = AsyncMock()
    return svc


def _raises(coro, status=403):
    with pytest.raises(TenancyError) as err:
        asyncio.run(coro)
    assert err.value.status == status


def test_admin_cannot_demote_the_owner():
    svc = _svc({ACTOR: "admin", TARGET: "owner"})
    _raises(svc.change_member_role(ORG, actor_id=ACTOR, member_user_id=TARGET, new_role="viewer"))


def test_admin_cannot_change_a_peer_admin():
    svc = _svc({ACTOR: "admin", TARGET: "admin"})
    _raises(svc.change_member_role(ORG, actor_id=ACTOR, member_user_id=TARGET, new_role="viewer"))


def test_admin_cannot_mint_another_admin():
    svc = _svc({ACTOR: "admin", TARGET: "viewer"})
    _raises(svc.change_member_role(ORG, actor_id=ACTOR, member_user_id=TARGET, new_role="admin"))


def test_admin_cannot_remove_a_peer_admin():
    svc = _svc({ACTOR: "admin", TARGET: "admin"})
    _raises(svc.remove_member(ORG, actor_id=ACTOR, member_user_id=TARGET))


def test_manager_cannot_invite_at_or_above_their_rank():
    svc = _svc({ACTOR: "manager"})
    for role in ("admin", "manager"):
        _raises(svc.create_invitation(ORG, actor_id=ACTOR, email="me@example.test", role=role))


def test_owner_may_still_manage_anyone():
    svc = _svc({ACTOR: "owner", TARGET: "admin"})
    # The owner passes every rank rule; the call then reaches persistence,
    # which this unit test doesn't provide.
    try:
        asyncio.run(svc.change_member_role(ORG, actor_id=ACTOR, member_user_id=TARGET, new_role="viewer"))
    except TenancyError as exc:
        raise AssertionError(f"owner was refused: {exc}") from exc
    except (AttributeError, TypeError, RuntimeError, OSError):
        return
