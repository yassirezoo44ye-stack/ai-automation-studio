"""
Auth Error Contract Tests
=========================
Verifies that every auth endpoint returns the correct HTTP status code and a
machine-readable `detail` string that the frontend can display directly.

Properties under test:
  - STATUS: each failure scenario returns the expected HTTP code
  - DETAIL: the `detail` field contains a safe, user-facing string
  - NO-ENUM: login 401s are byte-identical for wrong-password vs user-not-found
             (no email-enumeration side-channel)
  - NO-LEAK: error responses never contain SQL, stack traces, or internal paths

These tests are the gate that ensures the frontend `res.json()` fix (commit
579d51a9) actually receives meaningful strings from the backend, not empty
bodies or silent 5xx blobs.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-auth-contract-tests")

from app.routers.auth_users import router  # noqa: E402


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_app():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def client():
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _mock_pool(conn_mock):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.auth_users.get_pool", return_value=pool)


def _conn_with_transaction(conn):
    """Wrap conn so it also supports async context manager on .transaction().

    conn.transaction must be a plain MagicMock (not AsyncMock) so that
    `async with conn.transaction():` receives a real context-manager object
    rather than a coroutine — which isn't iterable and breaks the `async with`.
    """
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)
    return conn


# ── Registration contract ──────────────────────────────────────────────────────

class TestRegisterContract:
    """POST /api/auth/register — status codes and detail messages."""

    def test_valid_registration_returns_201_with_message(self, client):
        conn = AsyncMock()
        _conn_with_transaction(conn)
        conn.execute = AsyncMock(return_value=None)

        with _mock_pool(conn), \
             patch("app.routers.auth_users.send_verification_email", new_callable=AsyncMock), \
             patch("app.routers.auth_users.write_audit", new_callable=AsyncMock):
            res = client.post(
                "/api/auth/register",
                json={"name": "Alice", "email": "alice@example.com", "password": "Str0ngPass!"},
            )

        assert res.status_code == 201
        body = res.json()
        assert "message" in body
        assert body["message"]  # non-empty

    def test_duplicate_email_returns_409_with_detail(self, client):
        """409 must carry 'Email already registered' so the UI can show it."""
        conn = AsyncMock()
        _conn_with_transaction(conn)
        conn.execute = AsyncMock(
            side_effect=asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
        )

        with _mock_pool(conn):
            res = client.post(
                "/api/auth/register",
                json={"name": "Bob", "email": "bob@example.com", "password": "Str0ngPass!"},
            )

        assert res.status_code == 409
        body = res.json()
        assert "detail" in body
        assert "already registered" in body["detail"].lower()

    def test_short_password_returns_422_with_detail(self, client):
        """Pydantic validation error — 422 body must contain a detail array."""
        res = client.post(
            "/api/auth/register",
            json={"name": "Carol", "email": "carol@example.com", "password": "short"},
        )
        assert res.status_code == 422
        body = res.json()
        assert "detail" in body
        # Pydantic returns a list of validation errors
        assert isinstance(body["detail"], list)
        assert len(body["detail"]) > 0

    def test_invalid_email_returns_422(self, client):
        res = client.post(
            "/api/auth/register",
            json={"name": "Dave", "email": "not-an-email", "password": "Str0ngPass!"},
        )
        assert res.status_code == 422
        assert "detail" in res.json()

    def test_empty_name_returns_422(self, client):
        res = client.post(
            "/api/auth/register",
            json={"name": "   ", "email": "eve@example.com", "password": "Str0ngPass!"},
        )
        assert res.status_code == 422
        assert "detail" in res.json()

    def test_missing_body_returns_422(self, client):
        res = client.post("/api/auth/register", json={})
        assert res.status_code == 422
        assert "detail" in res.json()

    def test_409_detail_contains_no_sql_or_stacktrace(self, client):
        """Security: duplicate-email error must never expose internal details."""
        conn = AsyncMock()
        _conn_with_transaction(conn)
        conn.execute = AsyncMock(
            side_effect=asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
        )

        with _mock_pool(conn):
            res = client.post(
                "/api/auth/register",
                json={"name": "Frank", "email": "frank@example.com", "password": "Str0ngPass!"},
            )

        body_text = res.text.lower()
        forbidden = ["traceback", "sqlstate", "constraint", "asyncpg", "postgresql",
                     "column", "table", "public", "stack"]
        for term in forbidden:
            assert term not in body_text, (
                f"Leaked internal term '{term}' in 409 response: {res.text[:300]}"
            )


# ── Login contract ─────────────────────────────────────────────────────────────

class TestLoginContract:
    """POST /api/auth/login — status codes, detail messages, and no enumeration."""

    def _fake_user(self, *, has_hash: bool = True) -> MagicMock:
        data = {
            "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
            "email": "user@example.com",
            "name": "User",
            "password_hash": "$2b$12$fakehash" if has_hash else None,
            "email_verified": True,
            "avatar_url": None,
            "created_at": None,
        }
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=data.__getitem__)
        row.get = MagicMock(side_effect=data.get)
        return row

    def test_valid_credentials_return_200_and_tokens(self, client):
        user_row = self._fake_user()
        conn = AsyncMock()
        async def _fetchrow(q, *a):
            if "mfa_secrets" in q:
                return None
            return user_row
        conn.fetchrow = AsyncMock(side_effect=_fetchrow)
        conn.execute = AsyncMock(return_value=None)

        with _mock_pool(conn), \
             patch("app.routers.auth_users.verify_password", return_value=True), \
             patch("app.routers.auth_users.make_access_token", return_value="acc.tok"), \
             patch("app.routers.auth_users.make_refresh_token", return_value="ref.tok"), \
             patch("app.routers.auth_users.write_audit", new_callable=AsyncMock):
            res = client.post(
                "/api/auth/login",
                json={"email": "user@example.com", "password": "Str0ngPass!"},
                headers={"X-Forwarded-For": "1.2.3.4"},
            )

        assert res.status_code == 200
        body = res.json()
        assert body.get("access_token") == "acc.tok"
        assert body.get("refresh_token") == "ref.tok"

    def test_wrong_password_returns_401_with_detail(self, client):
        user_row = self._fake_user()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=user_row)

        with _mock_pool(conn), \
             patch("app.routers.auth_users.verify_password", return_value=False):
            res = client.post(
                "/api/auth/login",
                json={"email": "user@example.com", "password": "WrongPass!"},
                headers={"X-Forwarded-For": "2.2.2.2"},
            )

        assert res.status_code == 401
        body = res.json()
        assert "detail" in body
        assert body["detail"]

    def test_user_not_found_returns_401_with_detail(self, client):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # no user in DB

        with _mock_pool(conn):
            res = client.post(
                "/api/auth/login",
                json={"email": "ghost@example.com", "password": "Str0ngPass!"},
                headers={"X-Forwarded-For": "3.3.3.3"},
            )

        assert res.status_code == 401
        body = res.json()
        assert "detail" in body
        assert body["detail"]

    def test_oauth_only_account_no_password_hash_returns_401(self, client):
        """Account created via OAuth (password_hash=None) cannot login with password."""
        oauth_user = self._fake_user(has_hash=False)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=oauth_user)

        with _mock_pool(conn):
            res = client.post(
                "/api/auth/login",
                json={"email": "user@example.com", "password": "AnyPassword1!"},
                headers={"X-Forwarded-For": "4.4.4.4"},
            )

        assert res.status_code == 401
        assert "detail" in res.json()

    def test_no_email_enumeration_wrong_password_vs_not_found(self, client):
        """401 detail must be identical for wrong-password and user-not-found
        so an attacker cannot distinguish registered from unregistered emails."""
        user_row = self._fake_user()

        conn_with_user = AsyncMock()
        conn_with_user.fetchrow = AsyncMock(return_value=user_row)
        conn_no_user = AsyncMock()
        conn_no_user.fetchrow = AsyncMock(return_value=None)

        with _mock_pool(conn_with_user), \
             patch("app.routers.auth_users.verify_password", return_value=False):
            res_wrong = client.post(
                "/api/auth/login",
                json={"email": "user@example.com", "password": "WrongPass!"},
                headers={"X-Forwarded-For": "5.5.5.5"},
            )

        with _mock_pool(conn_no_user):
            res_missing = client.post(
                "/api/auth/login",
                json={"email": "nobody@example.com", "password": "AnyPass1!"},
                headers={"X-Forwarded-For": "6.6.6.6"},
            )

        assert res_wrong.status_code == res_missing.status_code == 401
        # Critical: same detail string — no email enumeration
        assert res_wrong.json()["detail"] == res_missing.json()["detail"], (
            "Email enumeration: 401 detail differs between wrong-password and user-not-found.\n"
            f"  wrong-password: {res_wrong.json()['detail']!r}\n"
            f"  user-not-found: {res_missing.json()['detail']!r}"
        )

    def test_401_detail_contains_no_sensitive_info(self, client):
        """Security: 401 must never expose password hash, DB details, or stack traces."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with _mock_pool(conn):
            res = client.post(
                "/api/auth/login",
                json={"email": "x@x.com", "password": "AnyPass1!"},
                headers={"X-Forwarded-For": "7.7.7.7"},
            )

        body_text = res.text.lower()
        forbidden = ["traceback", "bcrypt", "hash", "sql", "asyncpg",
                     "postgresql", "column", "stack", "exception"]
        for term in forbidden:
            assert term not in body_text, (
                f"Leaked sensitive term '{term}' in 401 response: {res.text[:300]}"
            )

    def test_missing_password_returns_422(self, client):
        res = client.post("/api/auth/login", json={"email": "x@x.com"})
        assert res.status_code == 422
        assert "detail" in res.json()

    def test_malformed_json_returns_422(self, client):
        res = client.post(
            "/api/auth/login",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 422
