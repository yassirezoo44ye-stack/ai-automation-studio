"""
Axon configuration and token encryption (app/core/config.py).

Covers: required/unsafe secret handling, DATABASE_URL and key-ring
validation, secrets staying out of repr(), and the AES-GCM TokenCipher's
tenant/purpose binding, tamper detection and key rotation.
"""
from __future__ import annotations

import base64
import re
import secrets
import uuid

import pytest
from pydantic import ValidationError

from app.core.config import (
    AxonSettings,
    ConfigurationError,
    TokenCipher,
    TokenDecryptionError,
    load_settings,
    parse_key_ring,
)

GOOD_SECRET = "9d4e2b7f1a6c3e8d5b0a7f2c4e6d8b1a3c5e7f9a"
DB_URL = "postgresql://axon:pw@localhost:5432/axon"

# The CHECK constraint on axon.integration_credentials.ciphertext in init_db.sql.
SQL_CIPHERTEXT_RE = re.compile(r"^axv1\.[A-Za-z0-9_-]{1,32}\.[A-Za-z0-9_-]+$")


def make_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


@pytest.fixture
def env(monkeypatch):
    """Start every test from a clean, valid production environment."""
    for name in (
        "ENVIRONMENT", "AXON_ENV", "AXON_TOKEN_ENCRYPTION_KEYS", "TOKEN_ENCRYPTION_KEYS",
        "AXON_DB_RLS_ROLE", "AXON_DB_POOL_SIZE", "APP_URL", "FRONTEND_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("SESSION_SECRET", GOOD_SECRET)
    return monkeypatch


# ── Settings validation ──────────────────────────────────────────────────────

class TestSettings:
    def test_valid_environment_loads(self, env):
        s = load_settings()
        assert s.environment == "production"
        assert s.session_secret.get_secret_value() == GOOD_SECRET
        assert s.db_rls_role == "axon_app"

    def test_unknown_environment_fails_closed_to_production(self, env):
        env.setenv("ENVIRONMENT", "prodution")  # typo
        assert load_settings().environment == "production"

    @pytest.mark.parametrize("missing", ["DATABASE_URL", "SESSION_SECRET"])
    def test_missing_required_value_is_reported_by_name(self, env, missing):
        env.delenv(missing)
        with pytest.raises(ConfigurationError, match=f"{missing} is not set"):
            load_settings()

    def test_short_secret_rejected_in_production(self, env):
        env.setenv("SESSION_SECRET", "x7Gq2Lp9")
        with pytest.raises(ConfigurationError, match="at least 32"):
            load_settings()

    @pytest.mark.parametrize("secret", [
        "dev-secret-not-for-production-use-change-me",
        "a" * 64,
        "please-replace-me-with-a-real-value-0123456789",
    ])
    def test_placeholder_secret_rejected_in_production(self, env, secret):
        env.setenv("SESSION_SECRET", secret)
        with pytest.raises(ConfigurationError, match="placeholder"):
            load_settings()

    def test_staging_follows_production_rules(self, env):
        env.setenv("ENVIRONMENT", "staging")
        env.setenv("SESSION_SECRET", "short")
        with pytest.raises(ConfigurationError):
            load_settings()

    def test_development_allows_placeholder_secret(self, env):
        env.setenv("ENVIRONMENT", "development")
        env.setenv("SESSION_SECRET", "dev-secret-not-for-production-use-change-me")
        assert load_settings().environment == "development"

    def test_empty_secret_rejected_even_in_development(self, env):
        env.setenv("ENVIRONMENT", "development")
        env.setenv("SESSION_SECRET", "   ")
        with pytest.raises(ConfigurationError):
            load_settings()

    @pytest.mark.parametrize("url", ["mysql://u:p@h/db", "sqlite:///x.db", "not a url"])
    def test_non_postgres_database_url_rejected(self, env, url):
        env.setenv("DATABASE_URL", url)
        with pytest.raises(ConfigurationError, match="DATABASE_URL"):
            load_settings()

    def test_error_message_never_contains_secret_values(self, env):
        env.setenv("DATABASE_URL", "mysql://admin:hunter2-very-secret@h/db")
        with pytest.raises(ConfigurationError) as exc:
            load_settings()
        assert "hunter2" not in str(exc.value)

    def test_repr_hides_secrets(self, env):
        env.setenv("AXON_TOKEN_ENCRYPTION_KEYS", f"k1:{make_key()}")
        s = load_settings()
        dumped = repr(s) + str(s.model_dump())
        assert GOOD_SECRET not in dumped
        assert "pw@" not in dumped

    @pytest.mark.parametrize("role", ["Axon_App", "axon-app", "app; DROP TABLE x", '"x"'])
    def test_rls_role_must_be_plain_identifier(self, env, role):
        env.setenv("AXON_DB_RLS_ROLE", role)
        with pytest.raises(ConfigurationError, match="AXON_DB_RLS_ROLE"):
            load_settings()

    def test_pool_bounds_validated(self, env):
        env.setenv("AXON_DB_POOL_SIZE", "0")
        with pytest.raises(ConfigurationError):
            load_settings()

    def test_settings_are_immutable(self, env):
        s = load_settings()
        with pytest.raises(ValidationError):
            s.db_rls_role = "postgres"  # type: ignore[misc]

    def test_cipher_unavailable_without_keys(self, env):
        with pytest.raises(ConfigurationError, match="AXON_TOKEN_ENCRYPTION_KEYS"):
            load_settings().token_cipher()


# ── Key ring parsing ─────────────────────────────────────────────────────────

class TestKeyRing:
    def test_first_key_is_primary(self):
        k1, k2 = make_key(), make_key()
        primary, ring = parse_key_ring(f"new:{k1}, old:{k2}")
        assert primary == "new"
        assert set(ring) == {"new", "old"}

    @pytest.mark.parametrize("spec, fragment", [
        ("", "no keys"),
        ("nokid", "<key-id>:<base64url key>"),
        ("bad id!:AAAA", "invalid key id"),
        ("k1:not-base64-@@@", "base64url"),
        (f"k1:{base64.urlsafe_b64encode(b'x' * 16).decode()}", "32 bytes"),
        (f"k1:{base64.urlsafe_b64encode(bytes(32)).decode()}", "entropy"),
    ])
    def test_invalid_specs(self, spec, fragment):
        with pytest.raises(ValueError, match=re.escape(fragment)):
            parse_key_ring(spec)

    def test_duplicate_ids_and_material_rejected(self):
        k = make_key()
        with pytest.raises(ValueError, match="duplicate"):
            parse_key_ring(f"a:{k},a:{make_key()}")
        with pytest.raises(ValueError, match="same key material"):
            parse_key_ring(f"a:{k},b:{k}")

    def test_invalid_ring_stops_startup(self, env):
        env.setenv("AXON_TOKEN_ENCRYPTION_KEYS", "k1:short")
        with pytest.raises(ConfigurationError, match="AXON_TOKEN_ENCRYPTION_KEYS"):
            load_settings()

    def test_key_reusing_session_secret_rejected(self, env):
        secret = "Zr8Lq3Nw6Tb1Yc4Vx7Hm2Kd5Gp9Sf0Ja"  # exactly 32 chars, usable as raw key
        env.setenv("SESSION_SECRET", secret)
        reused = base64.urlsafe_b64encode(secret.encode()).decode()
        env.setenv("AXON_TOKEN_ENCRYPTION_KEYS", f"k1:{reused}")
        with pytest.raises(ConfigurationError, match="must not reuse SESSION_SECRET"):
            load_settings()


# ── TokenCipher ──────────────────────────────────────────────────────────────

@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher.from_spec(f"k2026:{make_key()}")


TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


class TestTokenCipher:
    def test_round_trip(self, cipher):
        token = cipher.encrypt("ya29.secret-oauth-token", tenant_id=TENANT_A, purpose="integration:google")
        assert cipher.decrypt(token, tenant_id=TENANT_A, purpose="integration:google") == "ya29.secret-oauth-token"

    def test_envelope_matches_database_constraint(self, cipher):
        token = cipher.encrypt("x", tenant_id=TENANT_A, purpose="webhook:secret")
        assert SQL_CIPHERTEXT_RE.match(token)
        assert TokenCipher.key_id_of(token) == "k2026"
        assert "x" not in token.split(".", 2)[2] or len(token) > 40

    def test_plaintext_never_appears_in_ciphertext(self, cipher):
        secret_value = "sk_live_THIS_MUST_NOT_LEAK"
        token = cipher.encrypt(secret_value, tenant_id=TENANT_A, purpose="integration:stripe")
        assert secret_value not in token
        assert secret_value.encode() not in base64.urlsafe_b64decode(token.split(".")[2] + "==")

    def test_same_plaintext_encrypts_differently(self, cipher):
        a = cipher.encrypt("same", tenant_id=TENANT_A, purpose="p.x")
        b = cipher.encrypt("same", tenant_id=TENANT_A, purpose="p.x")
        assert a != b

    def test_ciphertext_bound_to_tenant(self, cipher):
        token = cipher.encrypt("tenant-a-token", tenant_id=TENANT_A, purpose="integration:slack")
        with pytest.raises(TokenDecryptionError):
            cipher.decrypt(token, tenant_id=TENANT_B, purpose="integration:slack")

    def test_ciphertext_bound_to_purpose(self, cipher):
        token = cipher.encrypt("v", tenant_id=TENANT_A, purpose="integration:slack")
        with pytest.raises(TokenDecryptionError):
            cipher.decrypt(token, tenant_id=TENANT_A, purpose="webhook:secret")

    def test_tenant_id_string_and_uuid_are_equivalent(self, cipher):
        token = cipher.encrypt("v", tenant_id=str(TENANT_A).upper(), purpose="p.x")
        assert cipher.decrypt(token, tenant_id=TENANT_A, purpose="p.x") == "v"

    def test_tampering_detected(self, cipher):
        token = cipher.encrypt("value", tenant_id=TENANT_A, purpose="p.x")
        prefix, kid, payload = token.split(".")
        raw = bytearray(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        raw[-1] ^= 0x01
        forged = f"{prefix}.{kid}.{base64.urlsafe_b64encode(bytes(raw)).decode().rstrip('=')}"
        with pytest.raises(TokenDecryptionError):
            cipher.decrypt(forged, tenant_id=TENANT_A, purpose="p.x")

    @pytest.mark.parametrize("token", [
        "", "plaintext-token", "axv1.k2026", "axv2.k2026.AAAA", "axv1.k2026.@@@@", "axv1.k2026.AAAA",
    ])
    def test_malformed_tokens_rejected(self, cipher, token):
        with pytest.raises(TokenDecryptionError):
            cipher.decrypt(token, tenant_id=TENANT_A, purpose="p.x")

    def test_unknown_key_id_rejected(self, cipher):
        other = TokenCipher.from_spec(f"other:{make_key()}")
        token = other.encrypt("v", tenant_id=TENANT_A, purpose="p.x")
        with pytest.raises(TokenDecryptionError):
            cipher.decrypt(token, tenant_id=TENANT_A, purpose="p.x")

    def test_invalid_purpose_and_tenant_rejected(self, cipher):
        with pytest.raises(ValueError):
            cipher.encrypt("v", tenant_id=TENANT_A, purpose="Bad Purpose")
        with pytest.raises(ValueError):
            cipher.encrypt("v", tenant_id="not-a-uuid", purpose="p.x")

    def test_oversized_plaintext_rejected(self, cipher):
        with pytest.raises(ValueError):
            cipher.encrypt("x" * (TokenCipher.MAX_PLAINTEXT_BYTES + 1), tenant_id=TENANT_A, purpose="p.x")

    def test_key_rotation(self):
        old_key, new_key = make_key(), make_key()
        old = TokenCipher.from_spec(f"old:{old_key}")
        token = old.encrypt("refresh-token", tenant_id=TENANT_A, purpose="integration:google")

        rotated_ring = TokenCipher.from_spec(f"new:{new_key},old:{old_key}")
        assert rotated_ring.needs_rotation(token)
        # Old ciphertext still readable during the rotation window.
        assert rotated_ring.decrypt(token, tenant_id=TENANT_A, purpose="integration:google") == "refresh-token"

        fresh = rotated_ring.rotate(token, tenant_id=TENANT_A, purpose="integration:google")
        assert TokenCipher.key_id_of(fresh) == "new"
        assert not rotated_ring.needs_rotation(fresh)
        assert rotated_ring.rotate(fresh, tenant_id=TENANT_A, purpose="integration:google") == fresh

        new_only = TokenCipher.from_spec(f"new:{new_key}")
        assert new_only.decrypt(fresh, tenant_id=TENANT_A, purpose="integration:google") == "refresh-token"
        with pytest.raises(TokenDecryptionError):
            new_only.decrypt(token, tenant_id=TENANT_A, purpose="integration:google")

    def test_repr_hides_key_material(self):
        key = make_key()
        assert key not in repr(TokenCipher.from_spec(f"k:{key}"))

    def test_settings_build_working_cipher(self, env):
        env.setenv("AXON_TOKEN_ENCRYPTION_KEYS", f"k1:{make_key()}")
        c = load_settings().token_cipher()
        assert c.decrypt(c.encrypt("ok", tenant_id=TENANT_A, purpose="p.x"), tenant_id=TENANT_A, purpose="p.x") == "ok"


def test_module_settings_type():
    from app.core import config
    assert isinstance(config.settings, AxonSettings)
    assert config.SESSION_SECRET == config.settings.session_secret.get_secret_value()
