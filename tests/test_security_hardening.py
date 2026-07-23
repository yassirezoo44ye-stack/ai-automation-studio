"""
v1.0 Security Hardening phase — tests for each fix landed this phase.
One test class per fix, named after the finding it closes, so a failing
test names exactly which security property regressed.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock


# ═══════════════════════════════════════════════════════════════════════════════
# SSRF guard (app/core/ssrf_guard.py) — used by the alert-rule webhook
# ═══════════════════════════════════════════════════════════════════════════════

class TestSsrfGuard(unittest.TestCase):
    def test_public_https_url_allowed(self):
        from app.core.ssrf_guard import assert_public_url
        assert_public_url("https://example.com/webhook")  # must not raise

    def test_public_http_url_allowed(self):
        from app.core.ssrf_guard import assert_public_url
        assert_public_url("http://example.com/webhook")  # must not raise

    def test_loopback_literal_ip_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http://127.0.0.1/steal")

    def test_localhost_hostname_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http://localhost/steal")

    def test_cloud_metadata_endpoint_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http://169.254.169.254/latest/meta-data/")

    def test_private_rfc1918_ranges_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        for host in ("10.0.0.5", "172.16.0.1", "192.168.1.1"):
            with self.subTest(host=host):
                with self.assertRaises(UnsafeUrlError):
                    assert_public_url(f"http://{host}/x")

    def test_non_http_scheme_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        for url in ("file:///etc/passwd", "gopher://127.0.0.1:6379/_INFO", "ftp://example.com/x"):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeUrlError):
                    assert_public_url(url)

    def test_url_with_no_hostname_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http:///no-host")


class TestAlertRuleWebhookSsrfRejection(unittest.TestCase):
    """The router-level validator on AlertRuleCreate — this is the actual
    fail-fast enforcement point a client hits (app/routers/diagnostics_api.py)."""

    def test_internal_webhook_url_rejected_at_creation(self):
        from pydantic import ValidationError
        from app.routers.diagnostics_api import AlertRuleCreate
        with self.assertRaises(ValidationError):
            AlertRuleCreate(
                name="evil", rule_type="gauge_above", target="x", threshold=1.0,
                notify_webhook_url="http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            )

    def test_public_webhook_url_accepted_at_creation(self):
        # example.com is IANA's reserved, always-resolvable test domain —
        # a made-up subdomain would fail DNS resolution in this test
        # environment and produce a false failure, not a real one.
        from app.routers.diagnostics_api import AlertRuleCreate
        rule = AlertRuleCreate(
            name="ok", rule_type="gauge_above", target="x", threshold=1.0,
            notify_webhook_url="https://example.com/incoming",
        )
        self.assertEqual(rule.notify_webhook_url, "https://example.com/incoming")

    def test_no_webhook_url_is_fine(self):
        from app.routers.diagnostics_api import AlertRuleCreate
        rule = AlertRuleCreate(name="ok", rule_type="gauge_above", target="x", threshold=1.0)
        self.assertIsNone(rule.notify_webhook_url)


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-org quota/billing bypass via unverified X-Organization-Id
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
        from unittest.mock import AsyncMock, MagicMock, patch

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
        from unittest.mock import AsyncMock, MagicMock, patch

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
# OAuth login CSRF (app/routers/auth_users.py) — missing `state` parameter
# ═══════════════════════════════════════════════════════════════════════════════

class TestOAuthStateCsrfProtection(unittest.TestCase):
    """Google/Microsoft/GitHub OAuth start+callback used to have no `state`
    parameter at all — RFC 6749 §10.12's textbook CSRF defense. Without it,
    an attacker completes their own OAuth flow, then tricks a victim into
    opening the resulting callback URL: the victim's browser ends up
    logged into the attacker's account (login/session-fixation CSRF)."""

    def _client(self):
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
        os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import auth_users
        auth_users._GOOGLE_CLIENT_ID = "test-google-client-id"
        app = FastAPI()
        app.include_router(auth_users.router)
        return TestClient(app, raise_server_exceptions=False)

    def test_start_endpoint_includes_state_and_sets_cookie(self):
        client = self._client()
        resp = client.get("/api/auth/google", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 307))
        self.assertIn("state=", resp.headers["location"])
        self.assertIn("oauth_state", resp.cookies)

    def test_callback_without_state_rejected(self):
        client = self._client()
        resp = client.get("/api/auth/google/callback?code=irrelevant", follow_redirects=False)
        self.assertEqual(resp.status_code, 400)

    def test_callback_with_mismatched_state_rejected(self):
        client = self._client()
        client.cookies.set("oauth_state", "cookie-value")
        resp = client.get(
            "/api/auth/google/callback?code=irrelevant&state=attacker-supplied",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400)

    def test_callback_with_no_cookie_at_all_rejected(self):
        # An attacker replaying their own captured callback URL (with a
        # real-looking state value) against a victim who never started the
        # flow has no oauth_state cookie to match against.
        client = self._client()
        resp = client.get(
            "/api/auth/google/callback?code=irrelevant&state=some-state-value",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400)


# ═══════════════════════════════════════════════════════════════════════════════
# OAuth tokens-in-URL (app/routers/auth_users.py) — one-time exchange code
# ═══════════════════════════════════════════════════════════════════════════════

class TestOAuthExchangeIsSingleUse(unittest.TestCase):
    """POST /api/auth/oauth-exchange redeems the one-time code an OAuth
    callback hands the frontend for the real tokens, replacing the old
    behavior of putting tokens directly in the redirect URL (exposed via
    browser history, Referer headers, and any access log that captures
    full request URLs)."""

    def _client(self):
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
        os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import auth_users
        app = FastAPI()
        app.include_router(auth_users.router)
        return TestClient(app, raise_server_exceptions=False)

    def test_unknown_code_rejected(self):
        client = self._client()
        resp = client.post("/api/auth/oauth-exchange", json={"code": "not-a-real-code"})
        self.assertEqual(resp.status_code, 400)

    def test_valid_code_redeems_once_then_fails(self):
        import asyncio
        from app.routers.auth_users import _stash_oauth_session_for_exchange

        async def _stash():
            return await _stash_oauth_session_for_exchange(
                {"access_token": "at", "refresh_token": "rt", "sub_token": "st"}
            )
        code = asyncio.run(_stash())

        client = self._client()
        first = client.post("/api/auth/oauth-exchange", json={"code": code})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["access_token"], "at")

        second = client.post("/api/auth/oauth-exchange", json={"code": code})
        self.assertEqual(second.status_code, 400)


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
# Cross-tenant agent-execution memory leak (app/agents/memory.py, agent_os_api.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentosMemoryEndpointIsOrgScoped(unittest.TestCase):
    """GET /api/agentos/memory used to return every org's raw execution
    history (input/args/error) with zero tenant scoping — any
    authenticated user of any org could read it. It must resolve the
    caller's verified org (app.tenancy.context.optional_org_id, the same
    pattern used by the cross-org billing fix earlier this phase) and
    pass it through to AgentMemory.recent(org_id=...)."""

    def test_resolves_and_passes_verified_org_id(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-42")):
                mem = MagicMock()
                mem.recent = MagicMock(return_value=[])
                with patch("app.agents.memory.get_memory", return_value=mem):
                    from app.routers.agent_os_api import agentos_memory
                    req = MagicMock()
                    result = await agentos_memory(req, n=50)
                    return mem.recent, result

        recent_mock, result = asyncio.run(_run())
        recent_mock.assert_called_once_with(50, org_id="org-42")
        self.assertEqual(result, {"count": 0, "records": []})

    def _real_memory_with_two_tenants(self):
        """A real (non-mocked) AgentMemory, in-process only — same
        construction pattern tests/test_agent_os.py's _make_memory() uses
        — pre-populated with one record each for org-a and org-b, so the
        isolation tests below exercise the real recent(org_id=...)
        filtering logic end-to-end, not a mock's assertion."""
        import threading
        from app.agents.memory import AgentMemory, ExecutionRecord
        mem = AgentMemory.__new__(AgentMemory)
        mem._lock = threading.Lock()
        mem._records = [
            ExecutionRecord(agent="echo", input="org-a confidential business data", args="",
                             success=True, duration_ms=1.0, organization_id="org-a"),
            ExecutionRecord(agent="echo", input="org-b confidential business data", args="",
                             success=True, duration_ms=1.0, organization_id="org-b"),
        ]
        return mem

    def test_org_a_cannot_read_org_b_records(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-a")), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        self.assertEqual(result["count"], 1)
        inputs = [r["input"] for r in result["records"]]
        self.assertIn("org-a confidential business data", inputs)
        self.assertNotIn("org-b confidential business data", inputs)

    def test_org_b_cannot_read_org_a_records(self):
        # Same check, other direction — isolation must not be a one-way
        # accident of iteration/insertion order.
        import asyncio
        from unittest.mock import AsyncMock, patch

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-b")), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        self.assertEqual(result["count"], 1)
        inputs = [r["input"] for r in result["records"]]
        self.assertIn("org-b confidential business data", inputs)
        self.assertNotIn("org-a confidential business data", inputs)

    def test_empty_result_when_caller_org_has_no_records(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        mem = self._real_memory_with_two_tenants()  # only org-a / org-b have data

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-c")), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        self.assertEqual(result, {"count": 0, "records": []})

    def test_forged_org_id_is_ignored_when_membership_verification_fails(self):
        # optional_org_id resolves the raw X-Organization-Id header value
        # ONLY after verifying real DB membership (app.tenancy.context) —
        # a caller who names an org they don't belong to gets None back,
        # never the forged id. This proves the endpoint relies on that
        # verified value, not on a client-supplied header directly.
        import asyncio
        from unittest.mock import AsyncMock, MagicMock as MM, patch

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context._get_current_user_dep") as get_dep, \
                 patch("app.tenancy.context.get_tenancy_service") as get_svc, \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from fastapi.security import HTTPBearer
                with patch.object(HTTPBearer, "__call__", new=AsyncMock(return_value="creds")):
                    get_dep.return_value = AsyncMock(return_value={"id": "attacker"})
                    svc = MM()
                    svc.get_member_role = AsyncMock(return_value=None)  # not a member of org-a
                    get_svc.return_value = svc

                    req = MM()
                    req.headers = {"X-Organization-Id": "org-a"}  # forged/claimed, not actually a member
                    req.query_params = {}
                    req.path_params = {}

                    from app.routers.agent_os_api import agentos_memory
                    return await agentos_memory(req, n=50)

        result = asyncio.run(_run())
        # Falls back to the no-org bucket (org_id=None), never org-a's data
        self.assertEqual(result, {"count": 0, "records": []})

    def test_garbage_org_id_cannot_bypass_filtering(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value=None)), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        # org_id=None is the explicit "no org" bucket — must not silently
        # widen to "every org", which is exactly the original leak.
        self.assertEqual(result, {"count": 0, "records": []})

    def test_missing_authentication_returns_401(self):
        # /api/agentos/memory is gated by factory.py's api_auth_middleware
        # like every other /api/* route outside PUBLIC_PREFIXES — an
        # unauthenticated request must never reach the handler at all.
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            import os
            os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
            os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
            from app.factory import create_app
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/agentos/memory")

        self.assertEqual(asyncio.run(_run()).status_code, 401)


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-tenant LayeredMemory leak (app/memory/layered.py, diagnostics_api.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticsMemoryEndpointIsOrgScoped(unittest.TestCase):
    """GET /api/diagnostics/memory and POST /api/diagnostics/memory/search
    read from LayeredMemory — a single, process-wide store shared by
    every tenant — with zero org scoping. Same fix shape as the AgentOS
    memory leak: resolve the caller's verified org via
    app.tenancy.context.optional_org_id and pass it through."""

    def _memory_with_two_tenants(self):
        import time
        import uuid
        from app.memory.layered import LayeredMemory, MemoryItem
        mem = LayeredMemory()
        mem.add(MemoryItem(id=str(uuid.uuid4()), layer="", kind="execution",
                            content="org-a confidential business data", tags=[],
                            created_at=time.time(), agent="assistant",
                            organization_id="org-a"))
        mem.add(MemoryItem(id=str(uuid.uuid4()), layer="", kind="execution",
                            content="org-b confidential business data", tags=[],
                            created_at=time.time(), agent="assistant",
                            organization_id="org-b"))
        return mem

    def test_org_a_cannot_read_org_b_records(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        mem = self._memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-a")), \
                 patch("app.memory.layered.get_layered_memory", return_value=mem):
                from app.routers.diagnostics_api import diagnostics_memory
                return await diagnostics_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        contents = [r["content"] for r in result["records"]]
        self.assertIn("org-a confidential business data", contents)
        self.assertNotIn("org-b confidential business data", contents)

    def test_org_b_cannot_read_org_a_records(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        mem = self._memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-b")), \
                 patch("app.memory.layered.get_layered_memory", return_value=mem):
                from app.routers.diagnostics_api import diagnostics_memory
                return await diagnostics_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        contents = [r["content"] for r in result["records"]]
        self.assertIn("org-b confidential business data", contents)
        self.assertNotIn("org-a confidential business data", contents)

    def test_forged_org_id_is_ignored_when_membership_verification_fails(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock as MM, patch

        mem = self._memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context._get_current_user_dep") as get_dep, \
                 patch("app.tenancy.context.get_tenancy_service") as get_svc, \
                 patch("app.memory.layered.get_layered_memory", return_value=mem):
                from fastapi.security import HTTPBearer
                with patch.object(HTTPBearer, "__call__", new=AsyncMock(return_value="creds")):
                    get_dep.return_value = AsyncMock(return_value={"id": "attacker"})
                    svc = MM()
                    svc.get_member_role = AsyncMock(return_value=None)  # not a member of org-a
                    get_svc.return_value = svc

                    req = MM()
                    req.headers = {"X-Organization-Id": "org-a"}
                    req.query_params = {}
                    req.path_params = {}

                    from app.routers.diagnostics_api import diagnostics_memory
                    return await diagnostics_memory(req, n=50)

        result = asyncio.run(_run())
        contents = [r["content"] for r in result["records"]]
        self.assertNotIn("org-a confidential business data", contents)
        self.assertNotIn("org-b confidential business data", contents)

    def test_missing_authentication_returns_401(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            import os
            os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
            os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
            from app.factory import create_app
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/diagnostics/memory")

        self.assertEqual(asyncio.run(_run()).status_code, 401)


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


class TestAgentosAgentEndpointsAreOrgScoped(unittest.TestCase):
    """GET /api/agentos/agents and /status used to return every org's
    plugin-installed/self-generated agent names + metadata with zero
    tenant scoping — /agents took no request context at all. Now scoped
    via AgentKernel.visible_agents()/status(organization_id=...), the
    Agent Execution Isolation phase's core fix."""

    def _kernel_with_two_tenants(self):
        import threading
        from app.agents.base import AgentContext, AgentResult, EvolvableAgent
        from app.agents.intent import IntentParser
        from app.agents.kernel import AgentKernel
        from app.agents.memory import AgentMemory
        from app.plugins.registry_guard import OwnershipTracker

        class _OrgAgent(EvolvableAgent):
            group = "test"
            def __init__(self, name):
                self.name = name
                self.description = "owned"
            async def execute(self, ctx: AgentContext) -> AgentResult:
                return AgentResult.ok(self.name, "ok")

        mem = AgentMemory.__new__(AgentMemory)
        mem._lock, mem._records = threading.Lock(), []

        kernel = AgentKernel.__new__(AgentKernel)
        kernel._agents, kernel._memory = {}, mem
        kernel._agent_owners = OwnershipTracker("agent")
        kernel._parser = IntentParser()
        kernel._booted = True
        kernel._modifier = kernel._reloader = kernel._router = None
        kernel._reflector = kernel._deliberation = kernel._autonomy = kernel._loop = None
        kernel._evolution = None

        kernel.register_agent(_OrgAgent("shared_builtin"))               # owner=None
        kernel.register_agent(_OrgAgent("org_a_secret_agent"), owner="org-a")
        kernel.register_agent(_OrgAgent("org_b_secret_agent"), owner="org-b")
        kernel._parser.update_agents(list(kernel._agents.keys()))
        return kernel

    def test_agents_endpoint_hides_other_orgs_custom_agents(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        kernel = self._kernel_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-a")), \
                 patch("app.agents.kernel.get_agent_kernel", return_value=kernel):
                from app.routers.agent_os_api import agentos_agents
                return await agentos_agents(MagicMock())

        result = asyncio.run(_run())
        names = {a["name"] for a in result["agents"]}
        self.assertIn("shared_builtin", names)
        self.assertIn("org_a_secret_agent", names)
        self.assertNotIn("org_b_secret_agent", names)

    def test_agents_endpoint_with_no_verified_org_sees_only_builtins(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        kernel = self._kernel_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value=None)), \
                 patch("app.agents.kernel.get_agent_kernel", return_value=kernel):
                from app.routers.agent_os_api import agentos_agents
                return await agentos_agents(MagicMock())

        result = asyncio.run(_run())
        names = {a["name"] for a in result["agents"]}
        self.assertEqual(names, {"shared_builtin"})

    def test_status_endpoint_agent_names_scoped_to_caller_org(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        kernel = self._kernel_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-b")), \
                 patch("app.agents.kernel.get_agent_kernel", return_value=kernel):
                from app.routers.agent_os_api import agentos_status
                return await agentos_status(MagicMock())

        result = asyncio.run(_run())
        self.assertIn("org_b_secret_agent", result["agent_names"])
        self.assertNotIn("org_a_secret_agent", result["agent_names"])


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
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
        os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
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
        from unittest.mock import AsyncMock, MagicMock
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
        import uuid
        from unittest.mock import patch
        from fastapi.testclient import TestClient

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
        import uuid
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from fastapi.testclient import TestClient

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
        import uuid
        from unittest.mock import patch
        from fastapi.testclient import TestClient

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
