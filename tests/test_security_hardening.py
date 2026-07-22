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


if __name__ == "__main__":
    unittest.main()
