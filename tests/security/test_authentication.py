"""
Security Regression Suite — Authentication.

Every route in this file used to be reachable with zero valid credential
(missing /api/ prefix so api_auth_middleware never saw it, or a fail-open
identity fallback) — each test proves the specific bypass stays closed:
access without login must return 401, never a working response.

Relocated (unmodified) from tests/test_security_hardening.py as part of
the Security Testing phase's tests/security/ reorganization — see that
phase's closing report for the full fix history. No behavioral change.
"""
from __future__ import annotations

import unittest


# ═══════════════════════════════════════════════════════════════════════════════
# Unauthenticated AI-cost endpoint (app/routers/chat.py) — /run(/stream)
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatRunEndpointsRequireAuth(unittest.TestCase):
    """POST /run and /run/stream (app/routers/chat.py) — the endpoints the
    live Chat page actually calls — used to be mounted without an /api/
    prefix, so api_auth_middleware's global auth gate (app/factory.py,
    only matches paths starting with /api/) never saw them: anyone with
    network access could call Claude through them with zero login, with
    only a spoofable per-IP rate limit standing between them and the
    platform's Anthropic bill. Moved to /api/run(/stream) so the existing
    gate applies, same as every other AI-cost endpoint in this app."""

    def _app(self):
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
        os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
        from app.factory import create_app
        return create_app()

    def test_unauthenticated_run_stream_rejected(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/api/run/stream", json={"project_id": "demo", "prompt": "hi"})

        self.assertEqual(asyncio.run(_run()).status_code, 401)

    def test_unauthenticated_run_rejected(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/api/run", json={"project_id": "demo", "prompt": "hi"})

        self.assertEqual(asyncio.run(_run()).status_code, 401)

    def test_authenticated_run_stream_passes_the_auth_gate(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport
        from app.core.auth import make_token

        async def _run():
            transport = ASGITransport(app=self._app())
            headers = {"X-Sub-Token": make_token("run-stream-test@example.com", False, 0)}
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post(
                    "/api/run/stream", json={"project_id": "demo", "prompt": "hi"}, headers=headers,
                )
        # No live Postgres in this test, so the handler itself may still
        # fail downstream — the only thing under test is that a valid
        # credential is not rejected by the auth gate (never 401).
        self.assertNotEqual(asyncio.run(_run()).status_code, 401)

    def test_old_unprefixed_run_stream_path_no_longer_registered(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/run/stream", json={"project_id": "demo", "prompt": "hi"})

        # No POST route matches the old path anymore — only the (GET-only)
        # SPA catch-all does, so this is a 405, not the chat handler.
        self.assertEqual(asyncio.run(_run()).status_code, 405)


# ═══════════════════════════════════════════════════════════════════════════════
# owner_email() fail-open fallback (app/core/auth.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOwnerEmailFailsClosed(unittest.TestCase):
    """owner_email() used to silently return a shared "demo@local" identity
    for any request it couldn't identify, instead of rejecting it — every
    caller of this function sits behind api_auth_middleware, so reaching
    that fallback meant the two layers disagreed about what's valid. Now
    it raises 401 instead of scoping the request to a shared identity."""

    class _Req:
        def __init__(self, headers):
            self.headers = headers
            self.cookies = {}
            self.client = None

    def test_no_credentials_raises_401_not_demo_fallback(self):
        from fastapi import HTTPException
        from app.core.auth import owner_email
        with self.assertRaises(HTTPException) as ctx:
            owner_email(self._Req({}))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_garbage_bearer_raises_401_not_demo_fallback(self):
        from fastapi import HTTPException
        from app.core.auth import owner_email
        with self.assertRaises(HTTPException) as ctx:
            owner_email(self._Req({"Authorization": "Bearer not-a-real-token"}))
        self.assertEqual(ctx.exception.status_code, 401)


# ═══════════════════════════════════════════════════════════════════════════════
# Unauthenticated Arabic NLU endpoint (app/routers/arabic_api.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestArabicApiRequiresAuth(unittest.TestCase):
    """POST /arabic/analyze used to be mounted without an /api/ prefix,
    the same shape of bug as chat.py's /run(/stream) — it bypassed
    api_auth_middleware entirely and made a real LLM call with zero
    login. No frontend caller depended on the old path (dead surface
    from the UI's perspective, but a live, reachable one over HTTP)."""

    def _app(self):
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
        os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
        from app.factory import create_app
        return create_app()

    def test_unauthenticated_analyze_rejected(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/api/arabic/analyze", json={"text": "مرحبا"})

        self.assertEqual(asyncio.run(_run()).status_code, 401)

    def test_old_unprefixed_path_no_longer_registered(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/arabic/analyze", json={"text": "مرحبا"})

        # No POST route matches the old path anymore — only the (GET-only)
        # SPA catch-all does, so this is a 405, not the NLU handler
        # (same reasoning as the chat.py /run/stream regression test).
        self.assertEqual(asyncio.run(_run()).status_code, 405)


class TestWorkflowApiRequiresAuth(unittest.TestCase):
    """POST /workflows/approvals/{run_id}/{step_id}/approve(/reject) used to
    be mounted without an /api/ prefix — same shape of bug as chat.py's
    /run(/stream): api_auth_middleware never saw it, so ANYONE could
    approve or reject a human-approval-gated workflow step for any
    organization, with zero authentication. Privilege Escalation Audit
    phase fix: moved to /api/workflows."""

    def _app(self):
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
        os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
        from app.factory import create_app
        return create_app()

    def test_unauthenticated_approve_rejected(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/api/workflows/approvals/run-1/step-1/approve")

        self.assertEqual(asyncio.run(_run()).status_code, 401)

    def test_unauthenticated_active_list_rejected(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/workflows/active")

        self.assertEqual(asyncio.run(_run()).status_code, 401)

    def test_old_unprefixed_approve_path_no_longer_registered(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/workflows/approvals/run-1/step-1/approve")

        # No route matches the old unprefixed path anymore — the SPA
        # catch-all is GET-only, so a POST here is 405, not the handler.
        self.assertEqual(asyncio.run(_run()).status_code, 405)


class TestJobsApiRequiresAuthAndOrgScoping(unittest.TestCase):
    """POST/GET/DELETE /jobs used to be mounted without an /api/ prefix AND
    had no per-route auth dependency — worse than a read-only leak:
    submit_job accepted an arbitrary client-supplied payload dict
    (including "organization_id") verbatim, and the queue's only
    registered handler (integration sync) trusts payload["organization_id"]
    to decide whose integration credentials to use. Privilege Escalation
    Audit phase fix: /api/jobs + mandatory org_context on every route +
    JobQueue.submit's org_id kwarg always overwrites whatever the client
    put in payload["organization_id"]."""

    def _app(self):
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
        os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
        from app.factory import create_app
        return create_app()

    def test_unauthenticated_submit_rejected(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/api/jobs", json={"kind": "integration_sync", "payload": {}})

        self.assertEqual(asyncio.run(_run()).status_code, 401)

    def test_unauthenticated_list_rejected(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/jobs")

        self.assertEqual(asyncio.run(_run()).status_code, 401)

    def test_old_unprefixed_path_no_longer_registered(self):
        # GET would be caught by app.factory's GET-only SPA catch-all
        # (200, not 404) — POST isn't, so a POST to the old path with no
        # matching route is the real signal it's gone (405), same
        # reasoning as the chat.py/arabic_api.py regression tests.
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=self._app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/jobs", json={"kind": "k"})

        self.assertEqual(asyncio.run(_run()).status_code, 405)

    def test_submit_always_overwrites_client_supplied_organization_id(self):
        # The core exploit this closes: even a legitimate, authenticated
        # caller must not be able to make the queue believe a job belongs
        # to a DIFFERENT org than the one it's actually verified for.
        import asyncio
        from app.core.jobs.queue import JobQueue

        async def _run():
            queue = JobQueue()
            job_id = await queue.submit(
                "integration_sync",
                payload={"organization_id": "attacker-claimed-org", "provider_id": "x"},
                org_id="server-verified-org",
            )
            return await queue.get(job_id)

        job = asyncio.run(_run())
        self.assertEqual(job.payload["organization_id"], "server-verified-org")

    def test_list_jobs_scoped_to_org(self):
        import asyncio
        from app.core.jobs.queue import JobQueue

        async def _run():
            queue = JobQueue()
            await queue.submit("k", payload={}, org_id="org-a")
            await queue.submit("k", payload={}, org_id="org-b")
            return await queue.list_jobs(org_id="org-a")

        jobs = asyncio.run(_run())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].payload["organization_id"], "org-a")


if __name__ == "__main__":
    unittest.main()
