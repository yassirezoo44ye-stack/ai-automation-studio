"""
Security Regression Suite — Webhook & Callback Security.

Covers: SSRF protection on outbound webhook/callback URLs (blocks
loopback/private/link-local/cloud-metadata targets and non-http(s)
schemes); OAuth login CSRF (the `state` parameter RFC 6749 §10.12
prescribes) and the one-time OAuth code exchange that replaced putting
tokens directly in a redirect URL; and inbound webhook signature
verification + delivery dedup for the Integration SDK.

Relocated (unmodified) from tests/test_security_hardening.py and
tests/test_integrations.py as part of the Security Testing phase's
tests/security/ reorganization. No behavioral change.
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def _org_id() -> str:
    return str(uuid.uuid4())


def _mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


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
# Inbound webhook signature verification + dedup (Integration SDK)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebhookPipeline:
    def test_receive_webhook_happy_path(self):
        from app.integrations.webhooks import receive_webhook
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider
        from app.integrations.types import IntegrationCredential, ProviderType
        import hmac
        import hashlib

        provider = WebhookRelayProvider()
        org_id = _org_id()
        secret = "shhh"
        cred = IntegrationCredential(
            provider_id="webhook-relay", organization_id=org_id, provider_type=ProviderType.CUSTOM,
            secrets={"webhook_secret": secret},
        )
        body = b'{"hello":"world"}'
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=uuid.uuid4())  # inserted (not a dup)
        pool = _mock_pool(conn)

        event = run(receive_webhook(
            provider=provider, credential=cred, headers={"x-relay-signature": sig}, body=body, pool=pool,
        ))
        assert event.body == body

    def test_receive_webhook_rejects_bad_signature(self):
        from app.integrations.webhooks import receive_webhook, WebhookVerificationError
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider
        from app.integrations.types import IntegrationCredential, ProviderType

        provider = WebhookRelayProvider()
        cred = IntegrationCredential(
            provider_id="webhook-relay", organization_id=_org_id(), provider_type=ProviderType.CUSTOM,
            secrets={"webhook_secret": "shhh"},
        )
        with pytest.raises(WebhookVerificationError):
            run(receive_webhook(
                provider=provider, credential=cred, headers={"x-relay-signature": "wrong"}, body=b"{}",
                pool=_mock_pool(AsyncMock()),
            ))

    def test_receive_webhook_raises_duplicate_when_dedup_key_conflicts(self):
        from app.integrations.webhooks import receive_webhook, WebhookDuplicateError
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider
        from app.integrations.types import IntegrationCredential, ProviderType
        import hmac
        import hashlib

        provider = WebhookRelayProvider()
        secret = "shhh"
        cred = IntegrationCredential(
            provider_id="webhook-relay", organization_id=_org_id(), provider_type=ProviderType.CUSTOM,
            secrets={"webhook_secret": secret},
        )
        body = b"{}"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # ON CONFLICT DO NOTHING -> no row
        with pytest.raises(WebhookDuplicateError):
            run(receive_webhook(
                provider=provider, credential=cred, headers={"x-relay-signature": sig}, body=body,
                pool=_mock_pool(conn),
            ))

    def test_dedup_key_is_scoped_per_provider_and_org(self):
        from app.integrations.webhooks import _dedup_key
        body = b"same body"
        k1 = _dedup_key("provider-a", "org-1", body)
        k2 = _dedup_key("provider-b", "org-1", body)
        k3 = _dedup_key("provider-a", "org-2", body)
        assert len({k1, k2, k3}) == 3


@pytest.fixture()
def integrations_client():
    from fastapi import FastAPI
    from app.routers.integrations import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestIntegrationsWebhookEndpoint:
    def test_unknown_provider_returns_404(self, integrations_client):
        fake_svc = MagicMock()
        fake_svc.receive_webhook = AsyncMock(side_effect=KeyError("nope"))
        with patch("app.routers.integrations.get_integration_service", return_value=fake_svc):
            res = integrations_client.post(f"/api/orgs/{_org_id()}/integrations/nope/webhook", content=b"{}")
        assert res.status_code == 404

    def test_bad_signature_returns_401(self, integrations_client):
        from app.integrations.webhooks import WebhookVerificationError
        fake_svc = MagicMock()
        fake_svc.receive_webhook = AsyncMock(side_effect=WebhookVerificationError("bad sig"))
        with patch("app.routers.integrations.get_integration_service", return_value=fake_svc):
            res = integrations_client.post(f"/api/orgs/{_org_id()}/integrations/webhook-relay/webhook", content=b"{}")
        assert res.status_code == 401

    def test_duplicate_delivery_returns_200(self, integrations_client):
        from app.integrations.webhooks import WebhookDuplicateError
        fake_svc = MagicMock()
        fake_svc.receive_webhook = AsyncMock(side_effect=WebhookDuplicateError("dup"))
        with patch("app.routers.integrations.get_integration_service", return_value=fake_svc):
            res = integrations_client.post(f"/api/orgs/{_org_id()}/integrations/webhook-relay/webhook", content=b"{}")
        assert res.status_code == 200
        assert "duplicate" in res.json()["status"]

    def test_success_returns_received(self, integrations_client):
        fake_svc = MagicMock()
        fake_svc.receive_webhook = AsyncMock(return_value=None)
        with patch("app.routers.integrations.get_integration_service", return_value=fake_svc):
            res = integrations_client.post(f"/api/orgs/{_org_id()}/integrations/webhook-relay/webhook", content=b"{}")
        assert res.status_code == 200
        assert res.json()["status"] == "received"

    def test_integration_error_returns_400(self, integrations_client):
        from app.integrations.service import IntegrationError
        fake_svc = MagicMock()
        fake_svc.receive_webhook = AsyncMock(side_effect=IntegrationError("not connected"))
        with patch("app.routers.integrations.get_integration_service", return_value=fake_svc):
            res = integrations_client.post(f"/api/orgs/{_org_id()}/integrations/webhook-relay/webhook", content=b"{}")
        assert res.status_code == 400


if __name__ == "__main__":
    unittest.main()
