"""
Regression tests for the CRITICAL self-issued "admin" API-key scope fix
(see app/core/config.py's ADMIN_EMAILS and the docstrings in
api_keys_router.py::create_key / organizations.py::create_org_api_key).

POST /api/keys (personal keys) and POST /api/orgs/{id}/api-keys
(org-scoped keys) both accepted an "admin" scope from any caller with no
check that the caller was actually a platform admin. "admin" is exactly
what require_api_key(scopes=["admin"]) checks for on real, still-live
dangerous endpoints (app/routers/marketplace.py's publisher-trust
endpoints, app/routers/usage_api.py's admin view) — since account
creation (POST /api/auth/register) and organization creation
(POST /api/orgs) are both self-service, any signed-up user could mint a
key that bypassed those gates.

Confirmed against this session's git-worktree audit (see
docs/... security reconciliation): a worktree commit (175d79f3) fixed
this identically on a stale branch that never merged into main; this
file re-implements and re-verifies the same fix against current main's
actual code rather than cherry-picking the stale diff.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


class TestPersonalKeyAdminScopeRequiresAllowlist(unittest.TestCase):
    def test_admin_scope_rejected_for_non_admin_email(self):
        from app.routers.api_keys_router import create_key, CreateKeyRequest

        async def _run():
            with patch("app.routers.api_keys_router.ADMIN_EMAILS", frozenset({"root@example.com"})):
                body = CreateKeyRequest(name="x", scopes=["admin"])
                await create_key(body, user={"id": "u1", "email": "random@user.com"})

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(_run())
        self.assertEqual(cm.exception.status_code, 403)

    def test_admin_scope_allowed_for_allowlisted_email(self):
        """The allowlist must not break the legitimate case."""
        from app.routers.api_keys_router import create_key, CreateKeyRequest

        async def _run():
            fake_rec = MagicMock(key_id="k1", name="x", scopes=["admin"], expires_at=None)
            with patch("app.routers.api_keys_router.ADMIN_EMAILS", frozenset({"root@example.com"})), \
                 patch("app.routers.api_keys_router.create_api_key",
                       new=AsyncMock(return_value=("raw123", fake_rec))):
                body = CreateKeyRequest(name="x", scopes=["admin"])
                return await create_key(body, user={"id": "u2", "email": "root@example.com"})

        result = asyncio.run(_run())
        self.assertEqual(result["api_key"], "raw123")

    def test_non_admin_scopes_stay_self_service(self):
        """The allowlist must gate only "admin" — read/write/etc. stay
        available to every signed-up user, exactly as before this fix."""
        from app.routers.api_keys_router import create_key, CreateKeyRequest

        async def _run():
            fake_rec = MagicMock(key_id="k1", name="x", scopes=["read", "write"], expires_at=None)
            with patch("app.routers.api_keys_router.ADMIN_EMAILS", frozenset()), \
                 patch("app.routers.api_keys_router.create_api_key",
                       new=AsyncMock(return_value=("raw123", fake_rec))):
                body = CreateKeyRequest(name="x", scopes=["read", "write"])
                return await create_key(body, user={"id": "u3", "email": "random@user.com"})

        result = asyncio.run(_run())
        self.assertEqual(result["api_key"], "raw123")


class TestOrgScopedKeyAdminScopeRequiresAllowlist(unittest.TestCase):
    """A second, independent route to the same hole: ApiKeyRecord.has_scope()
    ignores organization_id, so an org-scoped "admin" key also satisfies a
    platform-wide require_api_key(scopes=["admin"]) gate. Org creation and
    the "manage api_keys" permission are both self-service."""

    def test_admin_scope_rejected_for_non_admin_org_owner(self):
        from app.routers.organizations import create_org_api_key, CreateApiKeyRequest

        async def _run():
            ctx = MagicMock(user_email="orgowner@user.com", user_id="u4", org_id="org1")
            with patch("app.routers.organizations.ADMIN_EMAILS", frozenset({"root@example.com"})):
                body = CreateApiKeyRequest(name="x", scopes=["admin"])
                await create_org_api_key(body, ctx=ctx)

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(_run())
        self.assertEqual(cm.exception.status_code, 403)

    def test_admin_scope_allowed_for_allowlisted_email(self):
        from app.routers.organizations import create_org_api_key, CreateApiKeyRequest

        async def _run():
            fake_rec = MagicMock(key_id="k1", name="x", scopes=["admin"],
                                  organization_id="org1", expires_at=None)
            ctx = MagicMock(user_email="root@example.com", user_id="u5", org_id="org1")
            with patch("app.routers.organizations.ADMIN_EMAILS", frozenset({"root@example.com"})), \
                 patch("app.core.api_keys.create_api_key",
                       new=AsyncMock(return_value=("raw123", fake_rec))):
                body = CreateApiKeyRequest(name="x", scopes=["admin"])
                return await create_org_api_key(body, ctx=ctx)

        result = asyncio.run(_run())
        self.assertEqual(result["api_key"], "raw123")


if __name__ == "__main__":
    unittest.main()
