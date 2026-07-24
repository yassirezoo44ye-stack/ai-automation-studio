"""
Security Regression Suite — AI Provider Isolation.

Covers two shapes of cross-tenant leak specific to the AI provider layer:
(1) the completion response cache hashing only request content — never
org_id — so two organizations issuing content-identical requests (a
shared demo-workflow template, a built-in agent's static system prompt)
could collide on the same cache entry and one org would receive another
org's cached AI response; (2) ContextManager's project-context injection
reading any project_id with no ownership check. Also covers the
credential-carrying dataclasses whose default Python repr would print
decrypted secrets verbatim if one were ever logged.

Relocated (unmodified) from tests/test_ai_platform.py and
tests/test_integrations.py as part of the Security Testing phase's
tests/security/ reorganization. No behavioral change.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.models import CompletionRequest, Message


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# Response cache — must never cross a tenant boundary
# ═══════════════════════════════════════════════════════════════════════════════

class TestResponseCacheOrgIsolation:
    def _req(self) -> CompletionRequest:
        return CompletionRequest(
            messages=[Message(role="user", content="Summarize this document.")],
            system="You are a helpful assistant.",
        )

    def test_make_key_differs_by_org_id_for_identical_request_content(self):
        from app.ai.cache import ResponseCache
        req = self._req()
        key_a = ResponseCache.make_key(req, org_id="org-A")
        key_b = ResponseCache.make_key(req, org_id="org-B")
        assert key_a != key_b

    def test_make_key_differs_between_no_org_and_an_org(self):
        from app.ai.cache import ResponseCache
        req = self._req()
        assert ResponseCache.make_key(req) != ResponseCache.make_key(req, org_id="org-A")

    def test_make_key_stable_for_same_org_and_content(self):
        from app.ai.cache import ResponseCache
        req = self._req()
        assert ResponseCache.make_key(req, org_id="org-A") == ResponseCache.make_key(req, org_id="org-A")

    def test_gateway_cache_hit_is_scoped_to_the_requesting_org(self):
        # End-to-end through AIGateway.complete(): org-A populates the
        # cache, then an identical request from org-B must NOT get served
        # org-A's cached response — it has to actually call the provider.
        from app.ai.cache import cache as response_cache
        from app.ai.gateway import AIGateway
        from app.ai.models import CompletionResponse

        response_cache.clear()
        gw = AIGateway(pool=object())
        req = CompletionRequest(
            messages=[Message(role="user", content="Same prompt, two tenants")],
            cache_ttl=60,
        )

        org_a_response = CompletionResponse(content="org-A's private answer")
        org_b_response = CompletionResponse(content="org-B's own answer")

        async def fake_enrich(request, *, user_id=None):
            return request

        async def fake_check_quota(_org_id):
            return None

        async def fake_post_complete(*a, **kw):
            return None

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(gw, "_enrich", fake_enrich)
            mp.setattr(gw, "_check_quota", fake_check_quota)
            mp.setattr(gw, "_post_complete", fake_post_complete)
            mp.setattr(
                "app.core.ai.registry.registry.platform_registry.complete_with_events",
                AsyncMock(side_effect=[
                    (org_a_response, "test-provider"),
                    (org_b_response, "test-provider"),
                ]),
            )
            resp_a = _run(gw.complete(req, org_id="org-A"))
            resp_b = _run(gw.complete(req, org_id="org-B"))

        assert resp_a.content == "org-A's private answer"
        # The bug this regression guards against: org-B silently receiving
        # org-A's cached response instead of making its own call.
        assert resp_b.content == "org-B's own answer"
        assert resp_b.content != resp_a.content

        response_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# ContextManager — project-context injection ownership check
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextManagerProjectOwnership:
    def test_project_context_scoped_to_owning_user(self):
        from app.core.ai.context.manager import ContextManager

        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"name": "Proj", "description": "desc"})
        mgr = ContextManager(pool=pool)

        bundle = _run(mgr.build(user_id="owner-1", project_id="proj-1"))

        sql, *params = pool.fetchrow.call_args.args
        assert "user_id" in sql
        assert params == ["proj-1", "owner-1"]
        assert bundle.project_meta == {"project": "Proj", "description": "desc"}

    def test_project_context_skipped_without_user_id(self):
        from app.core.ai.context.manager import ContextManager

        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"name": "Proj", "description": "desc"})
        mgr = ContextManager(pool=pool)

        bundle = _run(mgr.build(project_id="proj-1"))

        pool.fetchrow.assert_not_called()
        assert bundle.project_meta == {}


# ═══════════════════════════════════════════════════════════════════════════════
# Credential-carrying dataclasses — default repr must not leak secrets
# ═══════════════════════════════════════════════════════════════════════════════

def _org_id() -> str:
    return str(uuid.uuid4())


class TestCredentialReprSafety:
    def test_oauth_provider_config_repr_redacts_client_secret(self):
        from app.integrations.oauth import OAuthProviderConfig
        config = OAuthProviderConfig(
            client_id="cid", client_secret="SUPER-SECRET-CLIENT-VALUE",
            authorize_url="https://example.test/authorize", token_url="https://example.test/token",
            redirect_uri="https://app.test/callback", scopes=["read"],
        )
        text = repr(config)
        assert "SUPER-SECRET-CLIENT-VALUE" not in text
        assert str(config) == text  # dataclasses fall back to __repr__ for __str__
        assert "cid" in text and "https://example.test/authorize" in text  # non-secret fields stay visible

    def test_oauth_token_repr_redacts_access_and_refresh_tokens_and_raw(self):
        from app.integrations.oauth import OAuthToken
        token = OAuthToken(
            access_token="ACCESS-VALUE", refresh_token="REFRESH-VALUE", expires_at=123.0,
            raw={"access_token": "ACCESS-VALUE", "id_token": "JWT-VALUE-HERE"},
        )
        text = repr(token)
        assert "ACCESS-VALUE" not in text
        assert "REFRESH-VALUE" not in text
        assert "JWT-VALUE-HERE" not in text
        assert "123.0" in text  # non-secret field stays visible

    def test_oauth_token_repr_handles_missing_refresh_token(self):
        from app.integrations.oauth import OAuthToken
        token = OAuthToken(access_token="ACCESS-VALUE", refresh_token=None, expires_at=None, raw={})
        text = repr(token)
        assert "ACCESS-VALUE" not in text
        assert "refresh_token=None" in text

    def test_integration_credential_repr_redacts_secrets_dict_values(self):
        from app.integrations.types import IntegrationCredential, ProviderType
        cred = IntegrationCredential(
            provider_id="webhook-relay", organization_id=_org_id(), provider_type=ProviderType.CUSTOM,
            secrets={"access_token": "TOP-SECRET-VALUE", "webhook_secret": "ANOTHER-SECRET"},
            metadata={"account_email": "user@example.test"},
        )
        text = repr(cred)
        assert "TOP-SECRET-VALUE" not in text
        assert "ANOTHER-SECRET" not in text
        assert str(cred) == text
        # non-secret fields (including secret *key names*, and metadata) stay visible for debuggability
        assert "access_token" in text
        assert "webhook_secret" in text
        assert "user@example.test" in text
        assert "webhook-relay" in text

    def test_integration_credential_repr_empty_secrets_is_safe(self):
        from app.integrations.types import IntegrationCredential, ProviderType
        cred = IntegrationCredential(provider_id="p", organization_id=_org_id(), provider_type=ProviderType.API_KEY)
        assert repr(cred) == str(cred)


if __name__ == "__main__":
    pytest.main([__file__])
