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

import html
import json
import os
import shlex
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


# ═══════════════════════════════════════════════════════════════════════════════
# IDOR: packaging endpoint (app/routers/package.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPackageStreamRequiresOwnership(unittest.TestCase):
    """POST /api/package/stream took project_id straight to workspace()
    with no ownership check — any authenticated user who learned another
    user's project_id could trigger a build against that project's
    workspace (the "docker" target zips every source file verbatim) and
    download the result, exfiltrating that user's project source. Fixed
    with the same owner_user_id()/resolve_project_id() pair build.py's
    shared _require_project_owner() guard is built from — resolve_project_id
    itself already returns the resolved project UUID and 404s a non-owner,
    which package_stream now needs for package_artifacts ownership too."""

    def _package_router_app(self):
        from fastapi import FastAPI
        from app.routers.package import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _mock_pool(self, *, requester_uid, owns_project: bool):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[
            requester_uid,                # owner_user_id() resolves the caller
            1 if owns_project else None,  # resolve_project_id()'s ownership SELECT
        ])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def test_non_owner_gets_404_not_a_build(self):
        """Bob authenticates fine, but the project belongs to Alice —
        the request must 404 before any workspace access or build starts."""
        bob_uid = uuid.uuid4()
        alice_project_id = str(uuid.uuid4())
        app = self._package_router_app()
        pool = self._mock_pool(requester_uid=bob_uid, owns_project=False)

        with patch("app.routers.package.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.post(
                    "/api/package/stream",
                    json={
                        "project_id": alice_project_id, "target": "exe", "lang": "python",
                        "app_name": "MyApp", "app_version": "1.0.0",
                    },
                    headers={"X-Sub-Token": "bob-token"},
                )
        self.assertEqual(res.status_code, 404)

    def test_owner_passes_the_ownership_gate(self):
        """The fix must not break legitimate access for the actual owner —
        the request should proceed past the guard into the packaging
        stream (docker/zip target: no subprocess, just file I/O)."""
        import tempfile
        from pathlib import Path

        alice_uid = uuid.uuid4()
        project_id = str(uuid.uuid4())
        app = self._package_router_app()
        pool = self._mock_pool(requester_uid=alice_uid, owns_project=True)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.routers.package.get_pool", return_value=pool), \
                 patch("app.core.auth.owner_email", return_value="alice@example.com"), \
                 patch("app.core.filesystem.WORKSPACES", Path(tmp)):
                with TestClient(app, raise_server_exceptions=False) as c:
                    res = c.post(
                        "/api/package/stream",
                        json={
                            "project_id": project_id, "target": "zip", "lang": "docker",
                            "app_name": "MyApp", "app_version": "1.0.0",
                        },
                        headers={"X-Sub-Token": "alice-token"},
                    )
        self.assertEqual(res.status_code, 200)


class TestPackageDownloadRequiresOwnership(unittest.TestCase):
    """GET /api/package/download/{folder}/{filename} used to serve any file
    under DIST_DIR to any authenticated user with no ownership check at
    all — only a path-traversal guard. Since folder is derived from the
    user-chosen app_name (the UI's own default is "Flow App"), unrelated
    users' builds could collide on the same download path. Fixed by
    keying downloads to a package_artifacts row scoped to (id, user_id)."""

    def _package_router_app(self):
        from fastapi import FastAPI
        from app.routers.package import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _mock_pool(self, *, requester_uid, artifact_row):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=requester_uid)  # owner_user_id()
        conn.fetchrow = AsyncMock(return_value=artifact_row)   # artifact ownership SELECT
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def test_foreign_or_missing_artifact_returns_404(self):
        """Bob authenticates fine, but no row matches (artifact_id, bob) —
        whether it belongs to Alice or doesn't exist must look identical."""
        bob_uid = uuid.uuid4()
        artifact_id = str(uuid.uuid4())
        app = self._package_router_app()
        pool = self._mock_pool(requester_uid=bob_uid, artifact_row=None)

        with patch("app.routers.package.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    f"/api/package/download/{artifact_id}",
                    headers={"X-Sub-Token": "bob-token"},
                )
        self.assertEqual(res.status_code, 404)

    def test_owner_can_download_own_artifact(self):
        """The fix must not break legitimate access for the actual owner."""
        import tempfile
        from pathlib import Path

        alice_uid = uuid.uuid4()
        artifact_id = str(uuid.uuid4())
        app = self._package_router_app()

        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "MyApp.zip"
            file_path.write_bytes(b"fake zip contents")
            row = {"filename": "MyApp.zip", "path": str(file_path)}
            pool = self._mock_pool(requester_uid=alice_uid, artifact_row=row)

            with patch("app.routers.package.get_pool", return_value=pool), \
                 patch("app.core.auth.owner_email", return_value="alice@example.com"):
                with TestClient(app, raise_server_exceptions=False) as c:
                    res = c.get(
                        f"/api/package/download/{artifact_id}",
                        headers={"X-Sub-Token": "alice-token"},
                    )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"fake zip contents")

    def test_non_uuid_artifact_id_returns_404(self):
        """A malformed id must 404 cleanly, not 500 on the UUID cast."""
        app = self._package_router_app()
        pool = self._mock_pool(requester_uid=uuid.uuid4(), artifact_row=None)

        with patch("app.routers.package.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    "/api/package/download/not-a-uuid",
                    headers={"X-Sub-Token": "bob-token"},
                )
        self.assertEqual(res.status_code, 404)


# ═══════════════════════════════════════════════════════════════════════════════
# Injection payload regression: every app_name generation path (package.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPackageAppNameStaysInert(unittest.TestCase):
    """app_name is embedded into generated Python (tkinter fallback), TOML
    (Briefcase pyproject.toml), JS (Electron main.js), HTML (Electron
    fallback index.html + Capacitor index.html), and Bash (docker
    setup.sh). Each of those five files must treat a malicious app_name
    as inert text, never as code/markup that breaks out of its enclosing
    literal. Covers both the original 3 escaping fixes (commit
    421c9424) and the 3 paths found missing on a follow-up sweep
    (Capacitor HTML, Briefcase TOML, docker setup.sh)."""

    PAYLOAD = (
        "\"); import os; os.system('calc'); print(\""
        "$(touch /tmp/pwned)"
        "`whoami`"
        "<script>alert(1)</script>"
    )

    def _app(self):
        from fastapi import FastAPI
        from app.routers.package import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _mock_pool(self, uid):
        conn = AsyncMock()
        # owner_user_id(), resolve_project_id()'s ownership SELECT, and a
        # spare value for record_artifact()'s INSERT (only the docker path
        # reaches that third call — harmless if the other paths don't use it).
        conn.fetchval = AsyncMock(side_effect=[uid, 1, uuid.uuid4()])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def _stream(self, tmp, *, lang, target, project_id, seed_workspace_file=False):
        """POST /api/package/stream with a malicious app_name. Every
        subprocess touchpoint is faked to succeed instantly (0 exit, no
        output) so each branch's real file-generation code runs without
        needing PyInstaller/Briefcase/npm/Gradle actually installed.
        seed_workspace_file: the docker target bails out early on an empty
        workspace, so pre-populate one dummy file for that case."""
        from pathlib import Path
        from app.runtime.preflight import PreflightResult

        async def fake_stream_process(cmd, cwd=None, **kwargs):
            yield "", 0

        async def fake_run_process(cmd, cwd=None, **kwargs):
            return 0, [], []

        workspaces_dir = Path(tmp) / "workspaces"
        dist_dir = Path(tmp) / "dist"
        workspaces_dir.mkdir(parents=True, exist_ok=True)
        dist_dir.mkdir(parents=True, exist_ok=True)
        if seed_workspace_file:
            project_ws = workspaces_dir / project_id
            project_ws.mkdir(parents=True, exist_ok=True)
            (project_ws / "app.py").write_text("print('hello')\n", encoding="utf-8")

        pool = self._mock_pool(uuid.uuid4())
        preflight_ok = PreflightResult(ok=True, checks=[], missing=[])

        with patch("app.routers.package.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="tester@example.com"), \
             patch("app.core.filesystem.WORKSPACES", workspaces_dir), \
             patch("app.routers.package.DIST_DIR", dist_dir), \
             patch("app.routers.package.run_preflight", return_value=preflight_ok), \
             patch("app.runtime.process.stream_process", fake_stream_process), \
             patch("app.runtime.process.run_process", fake_run_process):
            with TestClient(self._app(), raise_server_exceptions=False) as c:
                c.post(
                    "/api/package/stream",
                    json={
                        "project_id": project_id, "target": target, "lang": lang,
                        "app_name": self.PAYLOAD, "app_version": "1.0.0",
                    },
                    headers={"X-Sub-Token": "tester-token"},
                )
        return workspaces_dir, dist_dir

    def _assert_html_escaped(self, html_content: str, *, context: str):
        self.assertNotIn("<script>alert(1)</script>", html_content,
                          f"{context}: <script> tag was not HTML-escaped")
        self.assertIn(html.escape(self.PAYLOAD), html_content,
                       f"{context}: escaped payload not found — generation logic may have changed")

    def test_tkinter_fallback_treats_app_name_as_data(self):
        import ast
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            project_id = str(uuid.uuid4())
            workspaces_dir, _ = self._stream(tmp, lang="python", target="exe", project_id=project_id)
            main_py = workspaces_dir / project_id / "main.py"
            self.assertTrue(main_py.exists(), "tkinter fallback main.py was not generated")
            content = main_py.read_text(encoding="utf-8")
            tree = ast.parse(content)  # raises SyntaxError if escaping broke the file
            self.assertEqual(
                len(tree.body), 7,
                "main.py has extra top-level statements — app_name broke out of the string literal",
            )

    def test_briefcase_pyproject_stays_valid_toml(self):
        import tempfile
        import tomllib
        with tempfile.TemporaryDirectory() as tmp:
            project_id = str(uuid.uuid4())
            _, dist_dir = self._stream(tmp, lang="python", target="apk", project_id=project_id)
            candidates = list(dist_dir.glob("*_briefcase/pyproject.toml"))
            self.assertEqual(len(candidates), 1, "Briefcase pyproject.toml was not generated")
            content = candidates[0].read_text(encoding="utf-8")
            parsed = tomllib.loads(content)  # raises TOMLDecodeError if escaping broke the file
            self.assertEqual(parsed["tool"]["briefcase"]["project_name"], self.PAYLOAD)
            # The payload must be a single scalar value, not additional
            # injected keys — the fixed schema keys must all still be present.
            self.assertIn("bundle", parsed["tool"]["briefcase"])
            self.assertIn("version", parsed["tool"]["briefcase"])

    def test_electron_main_js_and_html_stay_inert(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            project_id = str(uuid.uuid4())
            _, dist_dir = self._stream(tmp, lang="electron", target="exe", project_id=project_id)
            el_dirs = list(dist_dir.glob("*_electron"))
            self.assertEqual(len(el_dirs), 1, "Electron output dir was not generated")

            main_js = (el_dirs[0] / "main.js").read_text(encoding="utf-8")
            self.assertIn(json.dumps(self.PAYLOAD), main_js,
                           "main.js does not contain the JSON-escaped app name")

            html_files = list(el_dirs[0].glob("*.html"))
            self.assertEqual(len(html_files), 1, "Electron fallback HTML was not generated")
            self._assert_html_escaped(html_files[0].read_text(encoding="utf-8"), context="electron index.html")

    def test_capacitor_html_stays_inert(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            project_id = str(uuid.uuid4())
            workspaces_dir, _ = self._stream(tmp, lang="web", target="apk", project_id=project_id)
            html_files = list((workspaces_dir / project_id).glob("*.html"))
            self.assertEqual(len(html_files), 1, "Capacitor fallback HTML was not generated")
            self._assert_html_escaped(html_files[0].read_text(encoding="utf-8"), context="capacitor index.html")

    def test_docker_setup_sh_stays_inert(self):
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            project_id = str(uuid.uuid4())
            _, dist_dir = self._stream(
                tmp, lang="docker", target="zip", project_id=project_id, seed_workspace_file=True,
            )
            zips = list(dist_dir.rglob("*-deploy.zip"))
            self.assertEqual(len(zips), 1, "docker deploy zip was not generated")
            with zipfile.ZipFile(zips[0]) as zf:
                names = [n for n in zf.namelist() if n.endswith("setup.sh")]
                self.assertEqual(len(names), 1, "setup.sh was not found in the deploy zip")
                setup_sh = zf.read(names[0]).decode("utf-8")
            self.assertIn(shlex.quote(self.PAYLOAD), setup_sh,
                           "setup.sh does not contain the shell-quoted app name")
            # Every use after the quoted assignment must be the $APP_NAME
            # variable reference, never the raw payload re-embedded.
            self.assertNotIn(f'"{self.PAYLOAD}"', setup_sh)


# ═══════════════════════════════════════════════════════════════════════════════
# IDOR: design canvas read/delete (app/routers/design.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDesignCanvasRequiresOwnership(unittest.TestCase):
    """GET/DELETE /api/design/canvases/{design_id} took design_id straight
    to a raw SELECT/DELETE with zero ownership check. DELETE was the worse
    of the two: no ownership check AND no Request parameter at all, so any
    authenticated user could destroy any other user's design with no
    recovery path. design_canvases has no user_id column, so the fix JOINs
    projects the same way resolve_project_id already verifies ownership
    for /api/design/canvases (POST) and /api/projects/{project_id}/*."""

    def _app(self):
        from fastapi import FastAPI
        from app.routers.design import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _mock_pool(self, *, uid, fetchrow_return=None, execute_return="DELETE 0"):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=uid)  # owner_user_id()
        conn.fetchrow = AsyncMock(return_value=fetchrow_return)
        conn.execute = AsyncMock(return_value=execute_return)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def test_get_foreign_or_missing_canvas_returns_404(self):
        bob_uid = uuid.uuid4()
        design_id = str(uuid.uuid4())
        app = self._app()
        pool = self._mock_pool(uid=bob_uid, fetchrow_return=None)

        with patch("app.routers.design.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(f"/api/design/canvases/{design_id}", headers={"X-Sub-Token": "bob-token"})
        self.assertEqual(res.status_code, 404)

    def test_owner_can_get_own_canvas(self):
        alice_uid = uuid.uuid4()
        design_id = str(uuid.uuid4())
        row = {
            "id": uuid.UUID(design_id), "project_id": uuid.uuid4(), "name": "My Design",
            "canvas_json": {"objects": []}, "thumbnail": None, "width": 1080, "height": 1080,
            "updated_at": None,
        }
        app = self._app()
        pool = self._mock_pool(uid=alice_uid, fetchrow_return=row)

        with patch("app.routers.design.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="alice@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(f"/api/design/canvases/{design_id}", headers={"X-Sub-Token": "alice-token"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "My Design")

    def test_delete_foreign_canvas_returns_404(self):
        """Bob authenticates fine, but the JOIN matches nothing for him —
        the row is not deleted (DELETE 0), and he sees a plain 404."""
        bob_uid = uuid.uuid4()
        design_id = str(uuid.uuid4())
        app = self._app()
        pool = self._mock_pool(uid=bob_uid, execute_return="DELETE 0")

        with patch("app.routers.design.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.delete(f"/api/design/canvases/{design_id}", headers={"X-Sub-Token": "bob-token"})
        self.assertEqual(res.status_code, 404)

    def test_owner_can_delete_own_canvas(self):
        alice_uid = uuid.uuid4()
        design_id = str(uuid.uuid4())
        app = self._app()
        pool = self._mock_pool(uid=alice_uid, execute_return="DELETE 1")

        with patch("app.routers.design.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="alice@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.delete(f"/api/design/canvases/{design_id}", headers={"X-Sub-Token": "alice-token"})
        self.assertEqual(res.status_code, 204)

    def test_malformed_design_id_returns_404_not_500(self):
        """A non-UUID design_id must 404 cleanly on both routes, not hit
        Postgres's ::uuid cast and bubble up as an unhandled 500."""
        app = self._app()
        pool = self._mock_pool(uid=uuid.uuid4())  # never reached if the guard works

        with patch("app.routers.design.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                get_res = c.get("/api/design/canvases/not-a-uuid", headers={"X-Sub-Token": "bob-token"})
                del_res = c.delete("/api/design/canvases/not-a-uuid", headers={"X-Sub-Token": "bob-token"})
        self.assertEqual(get_res.status_code, 404)
        self.assertEqual(del_res.status_code, 404)
        pool_conn = pool.acquire.return_value.__aenter__.return_value
        pool_conn.fetchrow.assert_not_called()
        pool_conn.execute.assert_not_called()

    def test_unauthenticated_requests_rejected(self):
        """No X-Sub-Token at all: api_auth_middleware must reject before
        the handler (and its ownership check) ever runs."""
        import asyncio
        from httpx import AsyncClient, ASGITransport
        from app.factory import create_app

        async def _run():
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                get_res = await client.get(f"/api/design/canvases/{uuid.uuid4()}")
                del_res = await client.delete(f"/api/design/canvases/{uuid.uuid4()}")
                return get_res, del_res

        get_res, del_res = asyncio.run(_run())
        self.assertEqual(get_res.status_code, 401)
        self.assertEqual(del_res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
