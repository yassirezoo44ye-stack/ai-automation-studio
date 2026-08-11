from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.core import security
from app.core.config import get_settings

settings = get_settings()


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self) -> None:
        password = "Sup3rSecret1"
        hashed = security.hash_password(password)
        assert hashed != password
        assert security.verify_password(password, hashed)

    def test_verify_rejects_wrong_password(self) -> None:
        hashed = security.hash_password("Sup3rSecret1")
        assert not security.verify_password("WrongPassword1", hashed)

    def test_verify_rejects_garbage_hash(self) -> None:
        assert not security.verify_password("whatever", "not-a-valid-hash")

    def test_two_hashes_of_same_password_differ(self) -> None:
        # argon2 salts each hash independently.
        h1 = security.hash_password("Sup3rSecret1")
        h2 = security.hash_password("Sup3rSecret1")
        assert h1 != h2


class TestAccessTokens:
    def test_create_and_decode_roundtrip(self) -> None:
        user_id = uuid.uuid4()
        token = security.create_access_token(user_id=user_id, email="a@example.com")
        payload = security.decode_access_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["email"] == "a@example.com"
        assert payload["type"] == "access"

    def test_decode_rejects_expired_token(self) -> None:
        user_id = uuid.uuid4()
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "email": "a@example.com",
            "type": "access",
            "iat": now - 1000,
            "exp": now - 500,
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(security.TokenError):
            security.decode_access_token(token)

    def test_decode_rejects_bad_signature(self) -> None:
        token = jwt.encode(
            {"sub": "x", "email": "a@example.com", "type": "access"},
            "a-completely-different-secret",
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(security.TokenError):
            security.decode_access_token(token)

    def test_decode_rejects_wrong_token_type(self) -> None:
        payload = {"sub": "x", "email": "a@example.com", "type": "refresh"}
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(security.TokenError):
            security.decode_access_token(token)

    def test_decode_rejects_malformed_token(self) -> None:
        with pytest.raises(security.TokenError):
            security.decode_access_token("not.a.jwt")


class TestRefreshTokens:
    def test_generate_returns_distinct_values_each_call(self) -> None:
        raw1, hash1, _ = security.generate_refresh_token()
        raw2, hash2, _ = security.generate_refresh_token()
        assert raw1 != raw2
        assert hash1 != hash2

    def test_hash_is_deterministic(self) -> None:
        raw, expected_hash, _ = security.generate_refresh_token()
        assert security.hash_token(raw) == expected_hash

    def test_raw_token_is_not_the_stored_hash(self) -> None:
        raw, token_hash, _ = security.generate_refresh_token()
        assert raw != token_hash


class TestCsrf:
    def test_matching_tokens_pass(self) -> None:
        token = security.generate_csrf_token()
        assert security.csrf_tokens_match(token, token)

    def test_mismatched_tokens_fail(self) -> None:
        assert not security.csrf_tokens_match(security.generate_csrf_token(), security.generate_csrf_token())

    def test_missing_values_fail(self) -> None:
        token = security.generate_csrf_token()
        assert not security.csrf_tokens_match(None, token)
        assert not security.csrf_tokens_match(token, None)
        assert not security.csrf_tokens_match(None, None)
