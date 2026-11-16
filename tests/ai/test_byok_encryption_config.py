"""Dedicated encryption-key configuration tests (no production secrets)."""
import pytest
from cryptography.fernet import Fernet
from app.ai import user_credentials as vault


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("BYOK_FERNET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        vault._cipher()


def test_invalid_key_fails_closed(monkeypatch):
    monkeypatch.setenv("BYOK_FERNET_KEY", "invalid")
    with pytest.raises(RuntimeError, match="Invalid"):
        vault._cipher()


def test_dedicated_key_encrypts_and_decrypts(monkeypatch):
    monkeypatch.setenv("BYOK_FERNET_KEY", Fernet.generate_key().decode("ascii"))
    cipher = vault._cipher()
    token = cipher.encrypt(b"not-a-real-api-key")
    assert b"not-a-real-api-key" not in token
    assert vault._cipher().decrypt(token) == b"not-a-real-api-key"
