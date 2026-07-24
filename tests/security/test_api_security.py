"""
Security Regression Suite — API Security (IDOR + forged headers).

Two distinct bug shapes: (1) endpoints that trusted a client-supplied
X-Organization-Id header without verifying real DB membership, letting a
caller bill/read against an org they don't belong to just by naming its
id; (2) endpoints missing the ownership JOIN/check entirely, letting any
authenticated caller read, mutate, or delete another user's resource by
guessing/learning its id (conversations, tasks, build-workspace files).

Relocated (unmodified) from tests/test_security_hardening.py,
tests/test_chat_isolation.py, and tests/test_security_hardening.py's
Webhook & Callback Security section as part of the Security Testing
phase's tests/security/ reorganization. No behavioral change.
"""
from __future__ import annotations

import os
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-org quota/billing bypass via unverified X-Organization-Id (forged header)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrgQuotaTrustsOnlyVerifiedMembership(unittest.TestCase):
    """check_org_quota (app/core/org_quota.py) used to read
    X-Organization-Id straight off the request with no membership check —
    any authenticated caller could bill/meter usage against, or trip the
    quota limit of, an org they don't belong to just by naming its id."""

    def _request(self, org_header: str | None):
        req = MagicMock()
        req.headers = {"X-Organization-Id": org_header} if org_header else {}
        req.query_params = {}
        req.path_params = {}
        return req

    def test_non_member_org_id_is_ignored(self):
        import asyncio

        async def _run():
            with patch("app.tenancy.context._get_current_user_dep") as get_dep, \
                 patch("app.tenancy.context.get_tenancy_service") as get_svc:
                from fastapi.security import HTTPBearer
                with patch.object(HTTPBearer, "__call__", new=AsyncMock(return_value="creds")):
                    get_dep.return_value = AsyncMock(return_value={"id": "attacker-user"})
                    svc = MagicMock()
                    svc.get_member_role = AsyncMock(return_value=None)  # not a member
                    get_svc.return_value = svc

                    from app.core.org_quota import check_org_quota
                    return await check_org_quota(self._request("victim-org-id"))
        self.assertIsNone(asyncio.run(_run()))

    def test_verified_member_org_id_is_honored(self):
        import asyncio

        async def _run():
            with patch("app.tenancy.context._get_current_user_dep") as get_dep, \
                 patch("app.tenancy.context.get_tenancy_service") as get_svc, \
                 patch("app.billing.get_usage_service") as get_usage:
                from fastapi.security import HTTPBearer
                with patch.object(HTTPBearer, "__call__", new=AsyncMock(return_value="creds")):
                    get_dep.return_value = AsyncMock(return_value={"id": "real-member"})
                    svc = MagicMock()
                    svc.get_member_role = AsyncMock(return_value="member")
                    get_svc.return_value = svc
                    usage = MagicMock()
                    usage.check_quota = AsyncMock(return_value=None)
                    get_usage.return_value = usage

                    from app.core.org_quota import check_org_quota
                    return await check_org_quota(self._request("my-real-org-id"))
        self.assertEqual(asyncio.run(_run()), "my-real-org-id")


# ═══════════════════════════════════════════════════════════════════════════════
# IDOR: conversations/tasks (app/routers/chat.py, tasks.py) — H-03
# ═══════════════════════════════════════════════════════════════════════════════

OWNER_A_EMAIL = "alice@example.com"
OWNER_A_UID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _make_chat_app():
    from fastapi import FastAPI
    from app.routers.chat import router
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_chat_pool(conn: AsyncMock):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.chat.get_pool", return_value=pool)


class TestConversationsIsScoped:
    def test_list_conversations_without_project_id_scopes_to_owner(self):
        app = _make_chat_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)  # owner_user_id lookup
        conn.fetch = AsyncMock(return_value=[])

        with _mock_chat_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/conversations", headers={"X-Sub-Token": "alice-token"})

        assert res.status_code == 200
        sql, *params = conn.fetch.call_args_list[0].args
        assert "p.user_id" in sql
        assert OWNER_A_UID in params

    def test_get_messages_for_foreign_conversation_returns_404(self):
        """A conv_id belonging to another user must not leak its messages."""
        app = _make_chat_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[OWNER_A_UID, None])  # owner uid, then ownership check fails
        conn.fetch = AsyncMock(return_value=[{"id": uuid.uuid4(), "role": "user",
                                               "content": "secret", "created_at": __import__("datetime").datetime.now()}])

        foreign_conv_id = str(uuid.uuid4())
        with _mock_chat_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    f"/api/conversations/{foreign_conv_id}/messages",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404
        # messages fetch must never have been reached
        conn.fetch.assert_not_called()

    def test_delete_conversation_not_owned_returns_404_and_does_not_delete(self):
        app = _make_chat_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)
        conn.execute = AsyncMock(return_value="DELETE 0")  # WHERE matched nothing

        foreign_conv_id = str(uuid.uuid4())
        with _mock_chat_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.delete(
                    f"/api/conversations/{foreign_conv_id}",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404
        sql = conn.execute.call_args_list[0].args[0]
        assert "p.user_id" in sql

    def test_extract_tasks_from_foreign_conversation_returns_404(self):
        """H-03, same shape, found later in tasks.py: the ownership JOIN
        (conversations -> projects.user_id) was missing entirely here —
        any conv_id worked, and that conversation's private messages
        would be fetched and fed to the LLM, with fragments leaking back
        via the extracted tasks' titles/notes."""
        from fastapi import FastAPI
        from app.routers.tasks import router as tasks_router

        app = FastAPI()
        app.include_router(tasks_router)

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)          # ensure_tasks_table's CREATE TABLE
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)   # owner_user_id lookup
        conn.fetchrow = AsyncMock(return_value=None)          # ownership JOIN finds nothing
        conn.fetch = AsyncMock(return_value=[{"role": "user", "content": "secret"}])

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        foreign_conv_id = str(uuid.uuid4())
        with patch("app.routers.tasks.get_pool", return_value=pool), \
             patch("app.core.db.get_pool", return_value=pool), \
             patch("app.routers.tasks.owner_email", return_value=OWNER_A_EMAIL), \
             patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL), \
             patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value=None)), \
             patch("app.routers.tasks.get_ai_client", return_value=MagicMock()):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.post(
                    f"/api/tasks/from-conversation/{foreign_conv_id}",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404
        # The ownership query itself must actually check projects.user_id...
        sql, *params = conn.fetchrow.call_args_list[0].args
        assert "p.user_id" in sql
        assert OWNER_A_UID in params
        # ...and the other user's messages must never have been fetched.
        conn.fetch.assert_not_called()

    def test_search_scopes_conversations_and_messages_to_owner(self):
        app = _make_chat_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)
        conn.fetch = AsyncMock(return_value=[])

        with _mock_chat_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/search?q=hello", headers={"X-Sub-Token": "alice-token"})

        assert res.status_code == 200
        assert conn.fetch.call_count == 2
        for call in conn.fetch.call_args_list:
            sql, *params = call.args
            assert "p.user_id" in sql
            assert OWNER_A_UID in params

    def test_export_foreign_conversation_returns_404(self):
        app = _make_chat_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)
        conn.fetchrow = AsyncMock(return_value=None)  # ownership JOIN finds nothing

        foreign_conv_id = str(uuid.uuid4())
        with _mock_chat_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    f"/api/export/conversations/{foreign_conv_id}",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# IDOR: build-workspace endpoints (app/routers/build.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildProjectEndpointsRequireOwnership(unittest.TestCase):
    """Every /api/projects/{project_id}/{files,sync,upload,download,run,
    process,proxy} endpoint used to operate purely on the URL's project_id
    string — workspace(project_id) only guards against path traversal, it
    has no concept of ownership, and none of these 10 routes ever called
    resolve_project_id (unlike /api/build, which already did, one function
    away). Any authenticated user who learned another user's project_id
    (a UUID, but one that travels through URLs/logs/screenshots) could
    read, overwrite, delete, or download that project's files, or run/stop
    a process and proxy into its running dev server. Webhook & Callback
    Security phase fix: every route now calls the shared
    _require_project_owner() guard before touching workspace()/process_mgr."""

    def _full_app(self):
        from app.factory import create_app
        return create_app()

    def test_unauthenticated_requests_rejected(self):
        """No X-Sub-Token at all: api_auth_middleware must reject before
        the handler (and its ownership check) ever runs."""
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._full_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                results = {}
                results["list_files"] = await client.get("/api/projects/some-id/files")
                results["download"] = await client.get("/api/projects/some-id/download")
                results["stop"] = await client.delete("/api/projects/some-id/process")
                results["proxy"] = await client.get("/api/projects/some-id/proxy/")
                return results

        for name, res in asyncio.run(_run()).items():
            self.assertEqual(res.status_code, 401, f"{name} did not reject an unauthenticated caller")

    def _build_router_app(self):
        from fastapi import FastAPI
        from app.routers.build import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _mock_pool(self, *, requester_uid, owns_project: bool):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[
            requester_uid,             # owner_user_id() resolves the caller
            1 if owns_project else None,  # resolve_project_id()'s ownership SELECT
        ])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def test_non_owner_gets_404_not_the_files(self):
        """Bob authenticates fine, but the project belongs to Alice —
        every affected route must 404, never leak Alice's data."""
        bob_uid = uuid.uuid4()
        alice_project_id = str(uuid.uuid4())
        app = self._build_router_app()

        routes = [
            ("GET", f"/api/projects/{alice_project_id}/files"),
            ("GET", f"/api/projects/{alice_project_id}/download"),
            ("DELETE", f"/api/projects/{alice_project_id}/process"),
            ("GET", f"/api/projects/{alice_project_id}/process"),
            ("GET", f"/api/projects/{alice_project_id}/proxy/"),
        ]
        for method, path in routes:
            pool = self._mock_pool(requester_uid=bob_uid, owns_project=False)
            with patch("app.routers.build.get_pool", return_value=pool), \
                 patch("app.core.auth.owner_email", return_value="bob@example.com"):
                with TestClient(app, raise_server_exceptions=False) as c:
                    res = c.request(method, path, headers={"X-Sub-Token": "bob-token"})
            self.assertEqual(res.status_code, 404, f"{method} {path} should 404 for a non-owner, got {res.status_code}")

    def test_owner_can_still_list_files(self):
        """The fix must not break legitimate access for the actual owner."""
        import tempfile
        from pathlib import Path

        alice_uid = uuid.uuid4()
        project_id = str(uuid.uuid4())
        app = self._build_router_app()
        pool = self._mock_pool(requester_uid=alice_uid, owns_project=True)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.routers.build.get_pool", return_value=pool), \
                 patch("app.core.auth.owner_email", return_value="alice@example.com"), \
                 patch("app.core.filesystem.WORKSPACES", Path(tmp)):
                with TestClient(app, raise_server_exceptions=False) as c:
                    res = c.get(f"/api/projects/{project_id}/files", headers={"X-Sub-Token": "alice-token"})

        self.assertEqual(res.status_code, 200)
        self.assertIn("files", res.json())

    def test_owner_can_still_check_process_status(self):
        alice_uid = uuid.uuid4()
        project_id = str(uuid.uuid4())
        app = self._build_router_app()
        pool = self._mock_pool(requester_uid=alice_uid, owns_project=True)

        with patch("app.routers.build.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="alice@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(f"/api/projects/{project_id}/process", headers={"X-Sub-Token": "alice-token"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"running": False})


if __name__ == "__main__":
    unittest.main()
