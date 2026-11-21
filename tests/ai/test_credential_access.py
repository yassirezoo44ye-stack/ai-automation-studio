"""Scope checks do not need live credentials or a database."""
import uuid

import pytest

from app.ai.credential_access import (
    CredentialAccessDenied, has_credential, scope_for_authenticated_user,
)
from app.tenancy.context import OrgContext


ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())


def verified_ctx(role="member"):
    return OrgContext(org_id=ORG, user_id=USER, user_email="user@example.test", role=role)


def test_verified_context_scopes_to_authenticated_user():
    scope = scope_for_authenticated_user(verified_ctx(), "openai")
    assert scope.org_id == ORG and scope.user_id == USER
    assert scope.provider == "openai"


def test_org_admin_still_scoped_to_self():
    scope = scope_for_authenticated_user(verified_ctx("owner"), "anthropic")
    assert scope.user_id == USER


@pytest.mark.parametrize("context", [None, {"org_id": ORG, "user_id": USER}, object()])
def test_reject_unverified_context(context):
    with pytest.raises(CredentialAccessDenied):
        scope_for_authenticated_user(context, "openai")


def test_reject_missing_membership_role():
    with pytest.raises(CredentialAccessDenied):
        scope_for_authenticated_user(verified_ctx(""), "openai")


def test_reject_unknown_provider():
    with pytest.raises(ValueError):
        scope_for_authenticated_user(verified_ctx(), "unknown")


@pytest.mark.asyncio
async def test_existence_check_does_not_fetch_secret():
    class FakeConn:
        async def fetchrow(self, query, *args):
            assert "SELECT 1" in query
            assert "encrypted_key" not in query
            assert args[0] == uuid.UUID(ORG) and args[1] == uuid.UUID(USER)
            return {"configured": 1}

    scope = scope_for_authenticated_user(verified_ctx(), "openai")
    assert await has_credential(FakeConn(), scope=scope) is True
