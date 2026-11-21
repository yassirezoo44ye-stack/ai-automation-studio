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

def test_rotation_reads_previous_key_and_writes_with_primary(monkeypatch):
    from cryptography.fernet import InvalidToken
    old, new = Fernet.generate_key(), Fernet.generate_key()
    legacy = Fernet(old).encrypt(b"legacy")
    monkeypatch.setenv("BYOK_FERNET_KEY", new.decode("ascii"))
    monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", old.decode("ascii"))
    assert vault._cipher().decrypt(legacy) == b"legacy"
    fresh = vault._cipher().encrypt(b"fresh")
    assert Fernet(new).decrypt(fresh) == b"fresh"
    with pytest.raises(InvalidToken):
        Fernet(old).decrypt(fresh)


def test_invalid_previous_key_fails_closed(monkeypatch):
    monkeypatch.setenv("BYOK_FERNET_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", "invalid")
    with pytest.raises(RuntimeError, match="Invalid"):
        vault._cipher()


def test_retiring_previous_key_blocks_old_ciphertext(monkeypatch):
    from cryptography.fernet import InvalidToken
    old = Fernet.generate_key()
    legacy = Fernet(old).encrypt(b"legacy")
    monkeypatch.setenv("BYOK_FERNET_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
    with pytest.raises(InvalidToken):
        vault._cipher().decrypt(legacy)
