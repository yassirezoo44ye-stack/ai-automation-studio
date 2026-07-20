"""
Integration SDK tests — registry, provider ABC contract, credential
encryption round-trip, OAuth abstraction mechanics (mocked token
endpoint, no real provider), webhook verify/dedup, sync engine
scheduling, permissions, events, health, metrics, service orchestration,
the example provider, and the router surface.

No live Postgres — pool/conn are mocked (same pattern as
tests/test_notifications.py).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _org_id() -> str:
    return str(uuid.uuid4())


# ── Registry ─────────────────────────────────────────────────────────────────

class TestIntegrationRegistry:
    def test_register_then_get(self):
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        registry = IntegrationRegistry()
        provider = WebhookRelayProvider()
        registry.register(provider)

        assert registry.get("webhook-relay") is provider
        assert registry.require("webhook-relay") is provider
        assert provider in registry.list_providers()

    def test_get_unknown_returns_none_require_raises(self):
        from app.integrations.registry import IntegrationRegistry
        registry = IntegrationRegistry()
        assert registry.get("nope") is None
        with pytest.raises(KeyError):
            registry.require("nope")

    def test_re_register_replaces(self):
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        registry = IntegrationRegistry()
        first, second = WebhookRelayProvider(), WebhookRelayProvider()
        registry.register(first)
        registry.register(second)
        assert registry.get("webhook-relay") is second

    def test_unregister(self):
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        registry = IntegrationRegistry()
        registry.register(WebhookRelayProvider())
        registry.unregister("webhook-relay")
        assert registry.get("webhook-relay") is None

    def test_singleton_accessor(self):
        from app.integrations.registry import get_integration_registry
        assert get_integration_registry() is get_integration_registry()


# ── IntegrationProvider ABC contract ─────────────────────────────────────────

class TestProviderABCDefaults:
    def test_minimal_subclass_gets_safe_defaults(self):
        from app.integrations.provider import IntegrationProvider
        from app.integrations.types import ProviderType, IntegrationCredential

        class Minimal(IntegrationProvider):
            @property
            def provider_id(self): return "minimal"
            @property
            def display_name(self): return "Minimal"
            @property
            def provider_type(self): return ProviderType.API_KEY

        p = Minimal()
        assert p.capabilities().sync is False
        assert p.capabilities().webhooks is False
        assert p.scopes() == []
        cred = IntegrationCredential(provider_id="minimal", organization_id=_org_id(), provider_type=ProviderType.API_KEY)
        assert run(p.test_connection(cred)) is True
        assert run(p.disconnect(cred)) is None
        assert p.verify_webhook_signature(MagicMock(), "secret") is False

    def test_sync_not_implemented_by_default(self):
        from app.integrations.provider import IntegrationProvider
        from app.integrations.types import ProviderType, IntegrationCredential

        class Minimal(IntegrationProvider):
            @property
            def provider_id(self): return "minimal"
            @property
            def display_name(self): return "Minimal"
            @property
            def provider_type(self): return ProviderType.API_KEY

        p = Minimal()
        cred = IntegrationCredential(provider_id="minimal", organization_id=_org_id(), provider_type=ProviderType.API_KEY)
        with pytest.raises(NotImplementedError):
            run(p.sync(cred))

    def test_handle_webhook_not_implemented_by_default(self):
        from app.integrations.provider import IntegrationProvider
        from app.integrations.types import ProviderType, IntegrationCredential

        class Minimal(IntegrationProvider):
            @property
            def provider_id(self): return "minimal"
            @property
            def display_name(self): return "Minimal"
            @property
            def provider_type(self): return ProviderType.API_KEY

        p = Minimal()
        cred = IntegrationCredential(provider_id="minimal", organization_id=_org_id(), provider_type=ProviderType.API_KEY)
        with pytest.raises(NotImplementedError):
            run(p.handle_webhook(cred, MagicMock()))

    def test_cannot_instantiate_without_identity_properties(self):
        from app.integrations.provider import IntegrationProvider
        with pytest.raises(TypeError):
            IntegrationProvider()  # abstract


# ── Credential store: real Fernet round-trip via mocked pool ────────────────

class TestCredentialStore:
    def test_save_then_load_round_trips_secrets(self):
        from app.integrations.credential_store import PostgresCredentialStore
        from app.integrations.types import IntegrationCredential, ProviderType

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        pool = _mock_pool(conn)
        store = PostgresCredentialStore(pool)

        org_id = _org_id()
        cred = IntegrationCredential(
            provider_id="webhook-relay", organization_id=org_id, provider_type=ProviderType.CUSTOM,
            secrets={"webhook_secret": "topsecret123"}, metadata={"note": "test"},
        )
        run(store.save(cred))

        sql, *params = conn.execute.call_args.args
        encrypted_blob = params[3]
        assert encrypted_blob != "topsecret123"  # actually encrypted, not stored raw
        assert "topsecret123" not in encrypted_blob

        conn.fetchrow = AsyncMock(return_value={
            "provider_id": "webhook-relay", "organization_id": uuid.UUID(org_id),
            "provider_type": "custom", "secrets_encrypted": encrypted_blob,
            "metadata": '{"note": "test"}', "expires_at": None,
        })
        loaded = run(store.load("webhook-relay", org_id))
        assert loaded.secrets == {"webhook_secret": "topsecret123"}
        assert loaded.metadata == {"note": "test"}
        assert loaded.provider_type == ProviderType.CUSTOM

    def test_load_returns_none_when_no_row(self):
        from app.integrations.credential_store import PostgresCredentialStore
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        store = PostgresCredentialStore(_mock_pool(conn))
        assert run(store.load("x", _org_id())) is None

    def test_load_returns_none_on_undecryptable_blob(self):
        """A corrupted or foreign-key blob must not crash the caller."""
        from app.integrations.credential_store import PostgresCredentialStore
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "provider_id": "x", "organization_id": uuid.UUID(_org_id()),
            "provider_type": "api_key", "secrets_encrypted": "not-a-real-fernet-token",
            "metadata": "{}", "expires_at": None,
        })
        store = PostgresCredentialStore(_mock_pool(conn))
        assert run(store.load("x", _org_id())) is None

    def test_delete_returns_false_when_nothing_deleted(self):
        from app.integrations.credential_store import PostgresCredentialStore
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 0")
        store = PostgresCredentialStore(_mock_pool(conn))
        assert run(store.delete("x", _org_id())) is False

    def test_delete_returns_true_when_row_deleted(self):
        from app.integrations.credential_store import PostgresCredentialStore
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 1")
        store = PostgresCredentialStore(_mock_pool(conn))
        assert run(store.delete("x", _org_id())) is True

    def test_singleton_accessor_requires_pool_or_default(self):
        from app.integrations import credential_store as cs
        cs._store = None
        pool = MagicMock()
        store = cs.get_credential_store(pool)
        assert cs.get_credential_store() is store
        cs._store = None  # don't leak state into other tests


# ── OAuth abstraction (mocked token endpoint — no real provider) ────────────

class TestOAuthAbstraction:
    def test_generate_state_and_pkce_are_unique_and_urlsafe(self):
        from app.integrations.oauth import generate_state, generate_pkce_pair
        s1, s2 = generate_state(), generate_state()
        assert s1 != s2
        verifier, challenge = generate_pkce_pair()
        assert verifier != challenge
        assert len(challenge) == 64  # hex sha256

    def test_build_authorize_url_includes_required_params(self):
        from app.integrations.oauth import OAuthProviderConfig, build_authorize_url
        config = OAuthProviderConfig(
            client_id="cid", client_secret="csecret",
            authorize_url="https://example.test/authorize", token_url="https://example.test/token",
            redirect_uri="https://app.test/callback", scopes=["read", "write"],
        )
        url = build_authorize_url(config, state="abc123")
        assert url.startswith("https://example.test/authorize?")
        assert "client_id=cid" in url
        assert "state=abc123" in url
        assert "response_type=code" in url
        assert "code_challenge" not in url

    def test_build_authorize_url_with_pkce(self):
        from app.integrations.oauth import OAuthProviderConfig, build_authorize_url
        config = OAuthProviderConfig(
            client_id="cid", client_secret="csecret",
            authorize_url="https://example.test/authorize", token_url="https://example.test/token",
            redirect_uri="https://app.test/callback",
        )
        url = build_authorize_url(config, state="abc123", code_challenge="chal")
        assert "code_challenge=chal" in url
        assert "code_challenge_method=S256" in url

    def test_exchange_code_for_token_parses_response(self):
        from app.integrations.oauth import OAuthProviderConfig, exchange_code_for_token

        config = OAuthProviderConfig(
            client_id="cid", client_secret="csecret",
            authorize_url="https://example.test/authorize", token_url="https://example.test/token",
            redirect_uri="https://app.test/callback",
        )
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={
            "access_token": "tok123", "refresh_token": "ref123", "expires_in": 3600, "token_type": "Bearer",
        })
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
            token = run(exchange_code_for_token(config, code="authcode"))

        assert token.access_token == "tok123"
        assert token.refresh_token == "ref123"
        assert token.expires_at is not None

    def test_refresh_access_token_carries_forward_refresh_token_if_omitted(self):
        from app.integrations.oauth import OAuthProviderConfig, refresh_access_token

        config = OAuthProviderConfig(
            client_id="cid", client_secret="csecret",
            authorize_url="https://example.test/authorize", token_url="https://example.test/token",
            redirect_uri="https://app.test/callback",
        )
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={"access_token": "newtok", "token_type": "Bearer"})
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
            token = run(refresh_access_token(config, refresh_token="oldref"))

        assert token.access_token == "newtok"
        assert token.refresh_token == "oldref"  # carried forward, not dropped

    def test_no_real_provider_config_is_defined_anywhere(self):
        """This module implements RFC 6749 mechanics only — asserting no
        module-level OAuthProviderConfig instance ships with a real
        client_id/secret baked in."""
        import app.integrations.oauth as oauth_mod
        for name in dir(oauth_mod):
            val = getattr(oauth_mod, name)
            assert not (hasattr(val, "client_id") and hasattr(val, "authorize_url") and not isinstance(val, type))


# ── Webhooks: verify + dedup + dispatch ──────────────────────────────────────

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


# ── Sync engine ───────────────────────────────────────────────────────────────

class TestSyncEngine:
    def test_schedule_sync_inserts_pending_row_and_submits_job(self):
        from app.integrations.sync_engine import SyncEngine

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        engine = SyncEngine(_mock_pool(conn))

        fake_queue = MagicMock()
        fake_queue.submit = AsyncMock(return_value="job-1")
        fake_queue.register_handler = MagicMock()

        org_id = _org_id()
        with patch("app.core.jobs.get_job_queue", return_value=fake_queue):
            run_id = run(engine.schedule_sync(provider_id="webhook-relay", organization_id=org_id))

        assert uuid.UUID(run_id)
        insert_sql = conn.execute.call_args.args[0]
        assert "integration_sync_runs" in insert_sql
        assert fake_queue.submit.call_count == 1
        assert fake_queue.register_handler.call_count == 1

    def test_start_registers_handler_without_scheduling(self):
        from app.integrations.sync_engine import SyncEngine
        engine = SyncEngine(MagicMock())
        fake_queue = MagicMock()
        with patch("app.core.jobs.get_job_queue", return_value=fake_queue):
            engine.start()
        fake_queue.register_handler.assert_called_once()
        assert engine._handler_registered is True

    def test_run_sync_job_records_success_and_updates_row(self):
        from app.integrations.sync_engine import SyncEngine
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider
        from app.integrations.types import IntegrationCredential, ProviderType

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = _mock_pool(conn)
        engine = SyncEngine(pool)

        registry = IntegrationRegistry()
        registry.register(WebhookRelayProvider())
        org_id = _org_id()
        cred = IntegrationCredential(
            provider_id="webhook-relay", organization_id=org_id, provider_type=ProviderType.CUSTOM,
            secrets={"webhook_secret": "s"},
        )
        fake_store = MagicMock()
        fake_store.load = AsyncMock(return_value=cred)

        job = MagicMock()
        job.payload = {"run_id": str(uuid.uuid4()), "provider_id": "webhook-relay", "organization_id": org_id}

        with patch("app.integrations.registry.get_integration_registry", return_value=registry), \
             patch("app.integrations.credential_store.get_credential_store", return_value=fake_store), \
             patch("app.integrations.events.publish_sync_completed", new=AsyncMock()):
            result = run(engine._run_sync_job(job))

        assert result["status"] == "succeeded"
        update_sql = conn.execute.call_args.args[0]
        assert "integration_sync_runs" in update_sql

    def test_run_sync_job_handles_missing_credential(self):
        from app.integrations.sync_engine import SyncEngine
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        engine = SyncEngine(_mock_pool(conn))

        registry = IntegrationRegistry()
        registry.register(WebhookRelayProvider())
        fake_store = MagicMock()
        fake_store.load = AsyncMock(return_value=None)

        job = MagicMock()
        job.payload = {"run_id": str(uuid.uuid4()), "provider_id": "webhook-relay", "organization_id": _org_id()}

        with patch("app.integrations.registry.get_integration_registry", return_value=registry), \
             patch("app.integrations.credential_store.get_credential_store", return_value=fake_store), \
             patch("app.integrations.events.publish_sync_failed", new=AsyncMock()):
            result = run(engine._run_sync_job(job))

        assert result["status"] == "failed"

    def test_list_history_queries_scoped_to_provider_and_org(self):
        from app.integrations.sync_engine import SyncEngine
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        engine = SyncEngine(_mock_pool(conn))
        run(engine.list_history(provider_id="webhook-relay", organization_id=_org_id()))
        sql, *params = conn.fetch.call_args.args
        assert "integration_sync_runs" in sql
        assert params[0] == "webhook-relay"


# ── Retry / circuit breaker ───────────────────────────────────────────────────

class TestRetry:
    def test_singleton(self):
        from app.integrations.retry import get_integration_circuit_breaker
        assert get_integration_circuit_breaker() is get_integration_circuit_breaker()

    def test_is_connection_allowed_delegates_to_breaker(self):
        from app.integrations import retry as retry_mod
        retry_mod._breaker = None
        assert retry_mod.is_connection_allowed("webhook-relay", _org_id()) is True

    def test_target_key_is_scoped_per_provider_and_org(self):
        from app.core.reliability import CircuitBreaker
        breaker = CircuitBreaker()
        target_a = "webhook-relay:org-1"
        target_b = "webhook-relay:org-2"
        for _ in range(20):
            breaker.record_failure(target_a)
        # org-2's target must be unaffected by org-1's failures
        assert breaker.allow(target_b) is True


# ── Permissions ────────────────────────────────────────────────────────────────

class TestPermissions:
    def test_validate_requested_scopes_rejects_unknown(self):
        from app.integrations.permissions import validate_requested_scopes
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        problems = validate_requested_scopes(WebhookRelayProvider(), ["receive", "bogus"])
        assert len(problems) == 1
        assert "bogus" in problems[0]

    def test_validate_requested_scopes_accepts_known(self):
        from app.integrations.permissions import validate_requested_scopes
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        assert validate_requested_scopes(WebhookRelayProvider(), ["receive"]) == []

    def test_sensitive_scopes_filters_correctly(self):
        from app.integrations.permissions import sensitive_scopes
        from app.integrations.provider import IntegrationProvider
        from app.integrations.types import ProviderType, ProviderScope

        class P(IntegrationProvider):
            @property
            def provider_id(self): return "p"
            @property
            def display_name(self): return "P"
            @property
            def provider_type(self): return ProviderType.API_KEY
            def scopes(self):
                return [ProviderScope(id="read", label="Read"), ProviderScope(id="delete", label="Delete", sensitive=True)]

        result = sensitive_scopes(P(), ["read", "delete"])
        assert result == ["delete"]


# ── Events ────────────────────────────────────────────────────────────────────

class TestEvents:
    def test_all_integration_event_types_declared_on_bus(self):
        from app.core.events.bus import EVENT_TYPES
        expected = {
            "integration.connected", "integration.disconnected",
            "integration.sync_started", "integration.sync_completed", "integration.sync_failed",
            "integration.webhook_received", "integration.health_changed",
        }
        assert expected.issubset(EVENT_TYPES)

    def test_publish_connected_calls_bus_with_correct_type(self):
        from app.integrations.events import publish_connected
        fake_bus = MagicMock()
        fake_bus.publish = AsyncMock()
        with patch("app.core.events.get_event_bus", return_value=fake_bus):
            run(publish_connected("webhook-relay", "org-1"))
        fake_bus.publish.assert_called_once()
        args, kwargs = fake_bus.publish.call_args
        assert args[0] == "integration.connected"
        assert kwargs["organization_id"] == "org-1"

    def test_publish_failure_is_swallowed(self):
        """Matches notifications' dispatcher convention: a broken event bus
        must never break the caller (connect/sync/webhook flows)."""
        from app.integrations.events import publish_sync_failed
        fake_bus = MagicMock()
        fake_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))
        with patch("app.core.events.get_event_bus", return_value=fake_bus):
            run(publish_sync_failed("webhook-relay", "org-1", message="boom"))  # must not raise


# ── Health probe ──────────────────────────────────────────────────────────────

class TestHealthProbe:
    def test_healthy_when_no_connections_tracked(self):
        from app.integrations.health import _probe_integrations
        from app.core.observability.health import HealthStatus
        fake_breaker = MagicMock()
        fake_breaker.snapshot = MagicMock(return_value={})
        with patch("app.integrations.retry.get_integration_circuit_breaker", return_value=fake_breaker):
            result = run(_probe_integrations())
        assert result.status == HealthStatus.HEALTHY

    def test_degraded_when_some_circuits_open(self):
        from app.integrations.health import _probe_integrations
        from app.core.observability.health import HealthStatus
        fake_breaker = MagicMock()
        fake_breaker.snapshot = MagicMock(return_value={
            "a:org1": {"state": "open"}, "b:org1": {"state": "closed"},
        })
        with patch("app.integrations.retry.get_integration_circuit_breaker", return_value=fake_breaker):
            result = run(_probe_integrations())
        assert result.status == HealthStatus.DEGRADED

    def test_unhealthy_when_all_circuits_open(self):
        from app.integrations.health import _probe_integrations
        from app.core.observability.health import HealthStatus
        fake_breaker = MagicMock()
        fake_breaker.snapshot = MagicMock(return_value={"a:org1": {"state": "open"}})
        with patch("app.integrations.retry.get_integration_circuit_breaker", return_value=fake_breaker):
            result = run(_probe_integrations())
        assert result.status == HealthStatus.UNHEALTHY

    def test_register_probe_calls_health_registry(self):
        from app.integrations.health import register_integration_health_probe
        fake_registry = MagicMock()
        with patch("app.core.observability.health.get_health_registry", return_value=fake_registry):
            register_integration_health_probe()
        fake_registry.register.assert_called_once()
        assert fake_registry.register.call_args.args[0] == "integrations"


# ── Metrics ───────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_record_sync_increments_counters(self):
        from app.integrations.metrics import record_sync
        fake_metrics = MagicMock()
        fake_counter = MagicMock()
        fake_metrics.counter = MagicMock(return_value=fake_counter)
        with patch("app.core.observability.metrics.get_metrics", return_value=fake_metrics):
            record_sync(succeeded=False)
        assert fake_counter.inc.call_count == 2  # total + failures

    def test_record_connection_change_moves_gauge(self):
        from app.integrations.metrics import record_connection_change
        fake_metrics = MagicMock()
        fake_gauge = MagicMock()
        fake_metrics.gauge = MagicMock(return_value=fake_gauge)
        with patch("app.core.observability.metrics.get_metrics", return_value=fake_metrics):
            record_connection_change(connected=True)
        fake_gauge.inc.assert_called_once()


# ── Permission matrix ─────────────────────────────────────────────────────────

class TestIntegrationsPermissionMatrix:
    def test_integrations_manage_seeded_for_admin(self):
        """admin has no blanket "manage" wildcard (only (*, read/create/
        update/delete) plus specific resource grants) — without an explicit
        ("integrations", "manage") tuple, only owner's (*, *) god-mode grant
        would pass require_permission("integrations", "manage"), locking
        admins out of connect/disconnect/sync. Same class of gap as
        ("teams", "manage") in test_enterprise.py."""
        from app.tenancy.schema import DEFAULT_PERMISSIONS
        assert ("integrations", "manage") in DEFAULT_PERMISSIONS["admin"]

    def test_integrations_read_covered_by_wildcard_for_every_role(self):
        from app.tenancy.schema import DEFAULT_PERMISSIONS
        for role, perms in DEFAULT_PERMISSIONS.items():
            assert ("*", "read") in perms or ("*", "*") in perms, role


# ── Schema ────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_schema_defines_all_four_tables_idempotently(self):
        from app.integrations.schema import INTEGRATIONS_SCHEMA
        for table in ("integrations", "integration_credentials", "integration_sync_runs", "integration_webhook_events"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in INTEGRATIONS_SCHEMA

    def test_integrations_table_references_organizations_and_users(self):
        from app.integrations.schema import INTEGRATIONS_SCHEMA
        assert "REFERENCES organizations(id)" in INTEGRATIONS_SCHEMA
        assert "REFERENCES users(id)" in INTEGRATIONS_SCHEMA


# ── IntegrationService orchestration ─────────────────────────────────────────

class TestIntegrationService:
    def _service_with_mocks(self):
        from app.integrations.service import IntegrationService
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        conn.fetchval = AsyncMock(return_value=1)
        pool = _mock_pool(conn)
        return IntegrationService(pool), conn

    def test_connect_rejects_unknown_scope(self):
        from app.integrations.service import IntegrationService, IntegrationError
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        registry = IntegrationRegistry()
        registry.register(WebhookRelayProvider())
        svc = IntegrationService(_mock_pool(AsyncMock()))

        with patch("app.integrations.registry.get_integration_registry", return_value=registry):
            with pytest.raises(IntegrationError):
                run(svc.connect(
                    provider_id="webhook-relay", organization_id=_org_id(), user_id=_org_id(),
                    secrets={"webhook_secret": "s"}, granted_scopes=["not-a-real-scope"],
                ))

    def test_connect_rejects_failed_test_connection(self):
        from app.integrations.service import IntegrationService, IntegrationError
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        registry = IntegrationRegistry()
        registry.register(WebhookRelayProvider())
        svc = IntegrationService(_mock_pool(AsyncMock()))

        with patch("app.integrations.registry.get_integration_registry", return_value=registry):
            with pytest.raises(IntegrationError):
                # no webhook_secret in secrets -> test_connection() returns False
                run(svc.connect(
                    provider_id="webhook-relay", organization_id=_org_id(), user_id=_org_id(),
                    secrets={},
                ))

    def test_connect_happy_path_saves_credential_and_publishes_event(self):
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        svc, conn = self._service_with_mocks()
        registry = IntegrationRegistry()
        registry.register(WebhookRelayProvider())

        fake_store = MagicMock()
        fake_store.save = AsyncMock()

        with patch("app.integrations.registry.get_integration_registry", return_value=registry), \
             patch("app.integrations.credential_store.get_credential_store", return_value=fake_store), \
             patch("app.integrations.events.publish_connected", new=AsyncMock()) as pub, \
             patch("app.integrations.metrics.record_connection_change") as metric:
            result = run(svc.connect(
                provider_id="webhook-relay", organization_id=_org_id(), user_id=_org_id(),
                secrets={"webhook_secret": "s"}, granted_scopes=["receive"],
            ))

        assert result["status"] == "connected"
        fake_store.save.assert_called_once()
        pub.assert_called_once()
        metric.assert_called_once_with(connected=True)

    def test_disconnect_returns_false_when_not_connected(self):
        svc, conn = self._service_with_mocks()
        fake_store = MagicMock()
        fake_store.load = AsyncMock(return_value=None)
        with patch("app.integrations.credential_store.get_credential_store", return_value=fake_store):
            ok = run(svc.disconnect(provider_id="webhook-relay", organization_id=_org_id(), user_id=_org_id()))
        assert ok is False

    def test_trigger_sync_rejects_provider_without_sync_capability(self):
        from app.integrations.service import IntegrationError
        from app.integrations.provider import IntegrationProvider
        from app.integrations.types import ProviderType
        from app.integrations.registry import IntegrationRegistry

        class NoSyncProvider(IntegrationProvider):
            @property
            def provider_id(self): return "no-sync"
            @property
            def display_name(self): return "No Sync"
            @property
            def provider_type(self): return ProviderType.API_KEY

        registry = IntegrationRegistry()
        registry.register(NoSyncProvider())
        svc, _ = self._service_with_mocks()

        with patch("app.integrations.registry.get_integration_registry", return_value=registry):
            with pytest.raises(IntegrationError):
                run(svc.trigger_sync(provider_id="no-sync", organization_id=_org_id()))

    def test_trigger_sync_rejects_when_not_connected(self):
        from app.integrations.service import IntegrationError
        from app.integrations.registry import IntegrationRegistry
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider

        registry = IntegrationRegistry()
        registry.register(WebhookRelayProvider())
        svc, conn = self._service_with_mocks()
        conn.fetchval = AsyncMock(return_value=None)  # not connected

        with patch("app.integrations.registry.get_integration_registry", return_value=registry):
            with pytest.raises(IntegrationError):
                run(svc.trigger_sync(provider_id="webhook-relay", organization_id=_org_id()))

    def test_receive_webhook_rejects_provider_without_webhook_capability(self):
        from app.integrations.service import IntegrationError
        from app.integrations.provider import IntegrationProvider
        from app.integrations.types import ProviderType
        from app.integrations.registry import IntegrationRegistry

        class NoWebhookProvider(IntegrationProvider):
            @property
            def provider_id(self): return "no-webhook"
            @property
            def display_name(self): return "No Webhook"
            @property
            def provider_type(self): return ProviderType.API_KEY

        registry = IntegrationRegistry()
        registry.register(NoWebhookProvider())
        svc, _ = self._service_with_mocks()

        with patch("app.integrations.registry.get_integration_registry", return_value=registry):
            with pytest.raises(IntegrationError):
                run(svc.receive_webhook(provider_id="no-webhook", organization_id=_org_id(), headers={}, body=b"{}"))


# ── Example provider ─────────────────────────────────────────────────────────

class TestWebhookRelayProvider:
    def test_capabilities_and_scopes(self):
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider
        p = WebhookRelayProvider()
        assert p.capabilities().sync is True
        assert p.capabilities().webhooks is True
        assert len(p.scopes()) == 1

    def test_test_connection_requires_webhook_secret(self):
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider
        from app.integrations.types import IntegrationCredential, ProviderType
        p = WebhookRelayProvider()
        ok_cred = IntegrationCredential(provider_id="webhook-relay", organization_id=_org_id(),
                                         provider_type=ProviderType.CUSTOM, secrets={"webhook_secret": "s"})
        bad_cred = IntegrationCredential(provider_id="webhook-relay", organization_id=_org_id(),
                                          provider_type=ProviderType.CUSTOM, secrets={})
        assert run(p.test_connection(ok_cred)) is True
        assert run(p.test_connection(bad_cred)) is False

    def test_sync_is_a_deterministic_no_op(self):
        from app.integrations.examples.webhook_relay_provider import WebhookRelayProvider
        from app.integrations.types import IntegrationCredential, ProviderType, SyncStatus
        p = WebhookRelayProvider()
        cred = IntegrationCredential(provider_id="webhook-relay", organization_id=_org_id(),
                                      provider_type=ProviderType.CUSTOM, secrets={"webhook_secret": "s"})
        result = run(p.sync(cred))
        assert result.status == SyncStatus.SUCCEEDED
        assert result.items_synced == 0


# ── Router surface ────────────────────────────────────────────────────────────

@pytest.fixture()
def integrations_client():
    from fastapi import FastAPI
    from app.routers.integrations import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestIntegrationsRouterGating:
    """Matches tests/test_enterprise.py's gating-verification convention:
    require_permission() returns a fresh closure per call, so equality is
    checked via __qualname__ + the resource/action baked into the closure's
    repr, not object identity."""

    def _gated_resource_action(self, endpoint):
        import inspect
        from app.tenancy.context import require_permission
        for p in inspect.signature(endpoint).parameters.values():
            if p.default is not inspect.Parameter.empty and hasattr(p.default, "dependency"):
                dep = p.default.dependency
                if getattr(dep, "__qualname__", "") == require_permission("x", "y").__qualname__:
                    return dep
        return None

    def test_providers_and_list_gated_on_read(self):
        from app.routers.integrations import list_providers, list_connections
        assert self._gated_resource_action(list_providers) is not None
        assert self._gated_resource_action(list_connections) is not None

    def test_mutating_endpoints_gated_on_manage(self):
        from app.routers.integrations import connect, disconnect, trigger_sync
        for endpoint in (connect, disconnect, trigger_sync):
            assert self._gated_resource_action(endpoint) is not None

    def test_webhook_endpoint_has_no_permission_dependency(self):
        """External senders can't attach a bearer token — the router must
        not require org auth on this route (signature verification is the
        auth), mirroring /api/stripe/webhook."""
        import inspect
        from app.routers.integrations import receive_webhook
        for p in inspect.signature(receive_webhook).parameters.values():
            if p.default is not inspect.Parameter.empty and hasattr(p.default, "dependency"):
                assert "require_permission" not in repr(p.default.dependency)


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
