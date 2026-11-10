"""
End-to-end tests for Axon authentication (app/core/axon_auth.py and
app/routers/axon_auth.py) against a real PostgreSQL with init_db.sql applied.

Run with AXON_TEST_DATABASE_URL pointing at a server where the login may
CREATE DATABASE and CREATE ROLE, e.g.:

    AXON_TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres pytest tests/test_axon_auth.py

Without it, only the request-parsing tests run.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import bcrypt
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import axon_auth as auth
from app.core import axon_security as sec
from app.core.config import TokenCipher, settings
from app.core.db import Database, TenantContextError, get_db_session, set_database
from app.core.rate_limit import rl_store
from app.routers.axon_auth import router

ADMIN_URL = os.getenv("AXON_TEST_DATABASE_URL", "")
INIT_SQL = Path(__file__).resolve().parent.parent / "init_db.sql"
pg = pytest.mark.skipif(not ADMIN_URL, reason="AXON_TEST_DATABASE_URL not set")

PASSWORD = "Correct-Horse-Battery-42"
CIPHER = TokenCipher.from_spec("k1:Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo")


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pg_url():
    import asyncpg
    from sqlalchemy.engine import make_url

    name = f"axon_auth_test_{uuid.uuid4().hex[:10]}"
    target = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)

    async def setup():
        conn = await asyncpg.connect(ADMIN_URL)
        try:
            await conn.execute(f'CREATE DATABASE "{name}"')
        finally:
            await conn.close()
        conn = await asyncpg.connect(target)
        try:
            await conn.execute(INIT_SQL.read_text())
        finally:
            await conn.close()

    async def teardown():
        conn = await asyncpg.connect(ADMIN_URL)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await conn.close()

    asyncio.run(setup())
    try:
        yield target
    finally:
        asyncio.run(teardown())


def _database(url: str, pool: int = 2) -> Database:
    cfg = settings.model_copy(update={
        "database_url": SecretStr(url), "db_pool_size": pool, "db_max_overflow": 0, "db_rls_role": "axon_app",
    })
    return Database(cfg, url=url)


@pytest.fixture
async def db(pg_url, monkeypatch):
    database = _database(pg_url)
    set_database(database)
    monkeypatch.setattr(auth, "get_token_cipher", lambda: CIPHER)
    rl_store.clear()  # rate limits and login lockouts are in-process in tests
    yield database
    set_database(None)
    await database.dispose()


@pytest.fixture
async def client(db):
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _slug() -> str:
    return f"org-{uuid.uuid4().hex[:10]}"


async def _register(client, slug: str | None = None, email: str = "owner@example.com") -> dict:
    slug = slug or _slug()
    r = await client.post("/api/axon/auth/register", json={
        "organization_name": "Acme", "organization_slug": slug, "email": email, "password": PASSWORD,
    })
    assert r.status_code == 201, r.text
    return {**r.json(), "slug": slug, "email": email}


async def _add_user(db, org_id: str, email: str, role: str = "member", *, password: str = PASSWORD,
                    pw_hash: str | None = None, mfa: bool = False) -> str:
    async with db.system_session("test: add user") as s:
        return str((await s.execute(
            text("INSERT INTO axon.users (organization_id, email, hashed_password, role, mfa_enabled) "
                 "VALUES (:o, :e, :h, :r, :m) RETURNING id"),
            {"o": org_id, "e": email, "h": pw_hash or sec.hash_password(password), "r": role, "m": mfa},
        )).scalar_one())


async def _login(client, slug: str, email: str, password: str = PASSWORD):
    return await client.post("/api/axon/auth/login",
                             json={"organization_slug": slug, "email": email, "password": password})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _me(client, headers: dict):
    return await client.get("/api/axon/auth/me", headers=headers)


# ═════════════════════════════════════════════════════════════════════════════
# Request parsing (no database)
# ═════════════════════════════════════════════════════════════════════════════

class TestCredentialParsing:
    @pytest.fixture
    def app_client(self):
        app = FastAPI()

        @app.get("/who")
        async def who(p: auth.AuthenticatedDep):
            return {"ok": True}

        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    @pytest.mark.parametrize("headers, code", [
        ({}, "missing_credentials"),
        ({"Authorization": "Basic dXNlcjpwYXNz"}, "unsupported_scheme"),
        ({"Authorization": "Bearer"}, "missing_credentials"),
        ({"Authorization": "Bearer not-a-jwt"}, "invalid_token"),
        ({"Authorization": "ApiKey axk_bad"}, "invalid_api_key"),
        ({"X-API-Key": "axon_legacy_key"}, "invalid_api_key"),
        ({"Authorization": "Bearer x", "X-API-Key": "y"}, "ambiguous_credentials"),
    ])
    async def test_rejected_before_database(self, app_client, headers, code):
        async with app_client as c:
            r = await c.get("/who", headers=headers)
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == code
        assert r.headers["www-authenticate"].startswith("Bearer")

    async def test_expired_token_code(self, app_client):
        token, _ = sec.issue_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), session_id=uuid.uuid4(),
                                          scopes=set(), now=datetime.now(timezone.utc) - timedelta(hours=1))
        async with app_client as c:
            r = await c.get("/who", headers=bearer(token))
        assert r.json()["detail"]["code"] == "token_expired"

    def test_requires_rejects_bad_scope_declaration(self):
        with pytest.raises(TenantContextError):
            auth.requires("not a scope")

    def test_token_pair_repr_hides_tokens(self):
        pair = auth.TokenPair(access_token="secret-access", access_expires_at=datetime.now(timezone.utc),
                              refresh_token="secret-refresh", refresh_expires_at=datetime.now(timezone.utc),
                              session_id=uuid.uuid4(), user_id=uuid.uuid4(), organization_id=uuid.uuid4(),
                              scopes=frozenset())
        assert "secret" not in repr(pair)


# ═════════════════════════════════════════════════════════════════════════════
# Registration and login
# ═════════════════════════════════════════════════════════════════════════════

@pg
class TestRegisterAndLogin:
    async def test_register_returns_admin_session(self, client):
        reg = await _register(client)
        assert reg["token_type"] == "Bearer" and reg["refresh_token"].startswith("axr_")
        assert {"api_keys:manage", "organization:manage", "members:manage"} <= set(reg["scopes"])
        me = await _me(client, bearer(reg["access_token"]))
        assert me.status_code == 200
        assert me.json()["organization_id"] == reg["organization_id"]
        assert me.json()["kind"] == "user"

    async def test_register_stores_argon2_hash_only(self, client, db):
        reg = await _register(client)
        async with db.system_session("test") as s:
            h = (await s.execute(text("SELECT hashed_password FROM axon.users WHERE id = :u"),
                                 {"u": reg["user_id"]})).scalar_one()
        assert h.startswith("$argon2id$") and PASSWORD not in h

    async def test_duplicate_slug_conflict(self, client):
        reg = await _register(client)
        r = await client.post("/api/axon/auth/register", json={
            "organization_name": "Other", "organization_slug": reg["slug"], "email": "x@example.com",
            "password": PASSWORD,
        })
        assert r.status_code == 409 and r.json()["detail"]["code"] == "slug_taken"

    @pytest.mark.parametrize("password", ["short", "password123", "aaaaaaaaaaaaaaaa"])
    async def test_weak_password_rejected(self, client, password):
        r = await client.post("/api/axon/auth/register", json={
            "organization_name": "Acme", "organization_slug": _slug(), "email": "a@example.com",
            "password": password,
        })
        assert r.status_code == 422 and r.json()["detail"]["code"] == "weak_password"

    async def test_signup_can_be_disabled(self, db, monkeypatch):
        cfg = settings.model_copy(update={"auth_allow_signup": False})
        with pytest.raises(auth.AuthError) as exc:
            await auth.register(organization_name="A", organization_slug=_slug(), email="a@example.com",
                                password=PASSWORD, db=db, cfg=cfg)
        assert exc.value.code == "signup_disabled"

    async def test_login_success_updates_last_login(self, client, db):
        reg = await _register(client)
        r = await _login(client, reg["slug"], reg["email"])
        assert r.status_code == 200
        assert r.json()["session_id"] != reg["session_id"]
        async with db.system_session("test") as s:
            last = (await s.execute(text("SELECT last_login_at FROM axon.users WHERE id = :u"),
                                    {"u": reg["user_id"]})).scalar_one()
        assert last is not None

    async def test_login_failures_are_indistinguishable(self, client):
        reg = await _register(client)
        cases = [
            (reg["slug"], reg["email"], "Wrong-Password-123"),
            (reg["slug"], "nobody@example.com", PASSWORD),
            (_slug(), reg["email"], PASSWORD),
            ("!!bad slug!!", reg["email"], PASSWORD),
        ]
        bodies = set()
        for slug, email, pw in cases:
            r = await _login(client, slug, email, pw)
            assert r.status_code == 401
            bodies.add(str(r.json()))
        assert len(bodies) == 1

    async def test_same_email_in_two_orgs_needs_slug(self, client):
        a = await _register(client, email="shared@example.com")
        b = await _register(client, email="shared@example.com")
        ra = await _login(client, a["slug"], "shared@example.com")
        rb = await _login(client, b["slug"], "shared@example.com")
        assert ra.json()["organization_id"] == a["organization_id"]
        assert rb.json()["organization_id"] == b["organization_id"]

    async def test_lockout_after_repeated_failures(self, client):
        reg = await _register(client)
        for _ in range(5):
            assert (await _login(client, reg["slug"], reg["email"], "Wrong-Password-123")).status_code == 401
        r = await _login(client, reg["slug"], reg["email"])
        assert r.status_code == 429 and r.json()["detail"]["code"] == "account_locked"

    async def test_inactive_user_cannot_login(self, client, db):
        reg = await _register(client)
        uid = await _add_user(db, reg["organization_id"], "gone@example.com")
        async with db.system_session("test") as s:
            await s.execute(text("UPDATE axon.users SET is_active = false WHERE id = :u"), {"u": uid})
        assert (await _login(client, reg["slug"], "gone@example.com")).status_code == 401

    async def test_inactive_organization_cannot_login(self, client, db):
        reg = await _register(client)
        async with db.system_session("test") as s:
            await s.execute(text("UPDATE axon.organizations SET is_active = false WHERE id = :o"),
                            {"o": reg["organization_id"]})
        assert (await _login(client, reg["slug"], reg["email"])).status_code == 401
        assert (await _me(client, bearer(reg["access_token"]))).status_code == 401

    async def test_mfa_account_fails_closed(self, client, db):
        reg = await _register(client)
        await _add_user(db, reg["organization_id"], "mfa@example.com", mfa=True)
        r = await _login(client, reg["slug"], "mfa@example.com")
        assert r.status_code == 401 and r.json()["detail"]["code"] == "mfa_required"

    async def test_legacy_bcrypt_hash_is_upgraded_on_login(self, client, db):
        reg = await _register(client)
        legacy = bcrypt.hashpw(hashlib.sha256(PASSWORD.encode()).digest(), bcrypt.gensalt()).decode()
        uid = await _add_user(db, reg["organization_id"], "old@example.com", pw_hash=legacy)
        assert (await _login(client, reg["slug"], "old@example.com")).status_code == 200
        async with db.system_session("test") as s:
            h = (await s.execute(text("SELECT hashed_password FROM axon.users WHERE id = :u"), {"u": uid})).scalar_one()
        assert h.startswith("$argon2id$")
        assert (await _login(client, reg["slug"], "old@example.com")).status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Sessions: refresh rotation, revocation, live scopes
# ═════════════════════════════════════════════════════════════════════════════

@pg
class TestSessions:
    async def _refresh(self, client, token: str):
        return await client.post("/api/axon/auth/refresh", json={"refresh_token": token})

    async def test_rotation_issues_new_tokens(self, client, db):
        reg = await _register(client)
        r = await self._refresh(client, reg["refresh_token"])
        assert r.status_code == 200
        new = r.json()
        assert new["refresh_token"] != reg["refresh_token"]
        assert new["session_id"] == reg["session_id"]
        assert (await _me(client, bearer(new["access_token"]))).status_code == 200
        async with db.system_session("test") as s:
            rows = (await s.execute(
                text("SELECT used_at IS NOT NULL FROM axon.refresh_tokens WHERE family_id = :f ORDER BY created_at"),
                {"f": reg["session_id"]},
            )).scalars().all()
        assert rows == [True, False]

    async def test_reuse_revokes_whole_session(self, client):
        reg = await _register(client)
        second = (await self._refresh(client, reg["refresh_token"])).json()
        reused = await self._refresh(client, reg["refresh_token"])
        assert reused.status_code == 401 and reused.json()["detail"]["code"] == "refresh_token_reused"
        # The legitimate holder's newer tokens die too: the family is revoked.
        assert (await self._refresh(client, second["refresh_token"])).status_code == 401
        assert (await _me(client, bearer(second["access_token"]))).status_code == 401
        assert (await _me(client, bearer(reg["access_token"]))).status_code == 401

    async def test_reuse_is_audited(self, client, db):
        reg = await _register(client)
        await self._refresh(client, reg["refresh_token"])
        await self._refresh(client, reg["refresh_token"])
        async with db.system_session("test") as s:
            n = (await s.execute(
                text("SELECT count(*) FROM axon.audit_events WHERE organization_id = :o "
                     "AND action = 'auth.refresh_reuse_detected'"),
                {"o": reg["organization_id"]},
            )).scalar_one()
        assert n == 1

    async def test_concurrent_refresh_only_one_wins(self, pg_url, monkeypatch):
        database = _database(pg_url, pool=4)
        set_database(database)
        rl_store.clear()
        try:
            pair = await auth.register(organization_name="A", organization_slug=_slug(),
                                       email="race@example.com", password=PASSWORD, db=database)
            results = await asyncio.gather(
                *(auth.refresh(pair.refresh_token, db=database) for _ in range(4)), return_exceptions=True,
            )
            wins = [r for r in results if isinstance(r, auth.TokenPair)]
            assert len(wins) == 1
            assert all(isinstance(r, (auth.TokenPair, auth.AuthError)) for r in results)
        finally:
            set_database(None)
            await database.dispose()

    @pytest.mark.parametrize("token", ["", "garbage", "axr_" + "a" * 43])
    async def test_unknown_refresh_token(self, client, token):
        r = await self._refresh(client, token)
        assert r.status_code in (401, 422)

    async def test_expired_refresh_token(self, client, db):
        reg = await _register(client)
        async with db.system_session("test") as s:
            await s.execute(text(
                "UPDATE axon.refresh_tokens SET created_at = now() - interval '2 days', "
                "expires_at = now() - interval '1 second' WHERE family_id = :f"), {"f": reg["session_id"]})
        r = await self._refresh(client, reg["refresh_token"])
        assert r.json()["detail"]["code"] == "refresh_token_expired"

    async def test_session_max_age_is_absolute(self, client, db):
        reg = await _register(client)
        async with db.system_session("test") as s:
            await s.execute(text(
                "UPDATE axon.refresh_tokens SET created_at = now() - interval '400 days' WHERE family_id = :f"),
                {"f": reg["session_id"]})
        r = await self._refresh(client, reg["refresh_token"])
        assert r.status_code == 401 and r.json()["detail"]["code"] == "session_expired"

    async def test_logout_revokes_access_and_refresh(self, client):
        reg = await _register(client)
        other = (await _login(client, reg["slug"], reg["email"])).json()
        r = await client.post("/api/axon/auth/logout", headers=bearer(reg["access_token"]))
        assert r.status_code == 204
        assert (await _me(client, bearer(reg["access_token"]))).status_code == 401
        assert (await self._refresh(client, reg["refresh_token"])).status_code == 401
        # Other sessions of the same user are unaffected.
        assert (await _me(client, bearer(other["access_token"]))).status_code == 200

    async def test_logout_all(self, client):
        reg = await _register(client)
        other = (await _login(client, reg["slug"], reg["email"])).json()
        r = await client.post("/api/axon/auth/logout-all", headers=bearer(reg["access_token"]))
        assert r.status_code == 200 and r.json()["tokens_revoked"] >= 2
        for token in (reg["access_token"], other["access_token"]):
            assert (await _me(client, bearer(token))).status_code == 401

    async def test_deactivation_applies_immediately(self, client, db):
        reg = await _register(client)
        uid = await _add_user(db, reg["organization_id"], "temp@example.com")
        session = (await _login(client, reg["slug"], "temp@example.com")).json()
        assert (await _me(client, bearer(session["access_token"]))).status_code == 200
        async with db.system_session("test") as s:
            await s.execute(text("UPDATE axon.users SET is_active = false WHERE id = :u"), {"u": uid})
        assert (await _me(client, bearer(session["access_token"]))).status_code == 401
        assert (await self._refresh(client, session["refresh_token"])).status_code == 401

    async def test_role_change_applies_on_next_request(self, client, db):
        reg = await _register(client)
        uid = await _add_user(db, reg["organization_id"], "dev@example.com", role="member")
        session = (await _login(client, reg["slug"], "dev@example.com")).json()
        assert "api_keys:manage" not in (await _me(client, bearer(session["access_token"]))).json()["scopes"]
        async with db.system_session("test") as s:
            await s.execute(text("UPDATE axon.users SET role = 'manager' WHERE id = :u"), {"u": uid})
        assert "api_keys:manage" in (await _me(client, bearer(session["access_token"]))).json()["scopes"]

    async def test_token_for_another_org_is_rejected(self, client):
        a = await _register(client)
        b = await _register(client)
        claims = sec.decode_access_token(a["access_token"])
        forged, _ = sec.issue_access_token(user_id=claims.user_id, tenant_id=uuid.UUID(b["organization_id"]),
                                           session_id=claims.session_id, scopes={"*"})
        assert (await _me(client, bearer(forged))).status_code == 401

    async def test_password_change_rotates_everything(self, client):
        reg = await _register(client)
        other = (await _login(client, reg["slug"], reg["email"])).json()
        new_pw = "A-Brand-New-Passphrase-7"
        bad = await client.post("/api/axon/auth/password", headers=bearer(reg["access_token"]),
                                json={"current_password": "Wrong-Password-123", "new_password": new_pw})
        assert bad.status_code == 401
        r = await client.post("/api/axon/auth/password", headers=bearer(reg["access_token"]),
                              json={"current_password": PASSWORD, "new_password": new_pw})
        assert r.status_code == 200, r.text
        fresh = r.json()
        assert (await _me(client, bearer(other["access_token"]))).status_code == 401
        assert (await _me(client, bearer(reg["access_token"]))).status_code == 401
        assert (await _me(client, bearer(fresh["access_token"]))).status_code == 200
        assert (await _login(client, reg["slug"], reg["email"])).status_code == 401
        assert (await _login(client, reg["slug"], reg["email"], new_pw)).status_code == 200

    async def test_password_change_enforces_policy(self, client):
        reg = await _register(client)
        r = await client.post("/api/axon/auth/password", headers=bearer(reg["access_token"]),
                              json={"current_password": PASSWORD, "new_password": PASSWORD})
        assert r.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# API keys and scopes
# ═════════════════════════════════════════════════════════════════════════════

@pg
class TestApiKeys:
    async def _create(self, client, token: str, scopes: list[str], **extra):
        return await client.post("/api/axon/api-keys", headers=bearer(token),
                                 json={"name": "ci", "scopes": scopes, **extra})

    async def test_create_use_and_revoke(self, client, db):
        reg = await _register(client)
        r = await self._create(client, reg["access_token"], ["workflows:read", "workflows:execute"])
        assert r.status_code == 201, r.text
        key = r.json()
        assert key["key"].startswith(key["prefix"] + "_")
        for headers in ({"X-API-Key": key["key"]}, {"Authorization": f"ApiKey {key['key']}"},
                        {"Authorization": f"Bearer {key['key']}"}):
            me = await _me(client, headers)
            assert me.status_code == 200
            assert me.json()["kind"] == "api_key"
            assert set(me.json()["scopes"]) == {"workflows:read", "workflows:execute"}
        async with db.system_session("test") as s:
            row = (await s.execute(text("SELECT hashed_key, last_used_at FROM axon.api_keys WHERE id = :k"),
                                   {"k": key["id"]})).mappings().one()
        assert row["last_used_at"] is not None
        assert key["key"] not in row["hashed_key"] and len(row["hashed_key"]) == 64

        assert (await client.delete(f"/api/axon/api-keys/{key['id']}", headers=bearer(reg["access_token"]))
                ).status_code == 204
        assert (await _me(client, {"X-API-Key": key["key"]})).status_code == 401

    async def test_key_is_shown_once(self, client):
        reg = await _register(client)
        await self._create(client, reg["access_token"], ["workflows:read"])
        listed = await client.get("/api/axon/api-keys", headers=bearer(reg["access_token"]))
        assert listed.status_code == 200
        assert all("key" not in k and "hashed_key" not in k for k in listed.json())

    async def test_key_cannot_exceed_creator_scopes(self, client, db):
        reg = await _register(client)
        await _add_user(db, reg["organization_id"], "mgr@example.com", role="manager")
        mgr = (await _login(client, reg["slug"], "mgr@example.com")).json()
        r = await self._create(client, mgr["access_token"], ["workflows:read", "organization:manage"])
        assert r.status_code == 403 and r.json()["detail"]["code"] == "scope_escalation"
        r = await self._create(client, mgr["access_token"], ["*"])
        assert r.status_code == 403

    async def test_member_without_scope_gets_403(self, client, db):
        reg = await _register(client)
        await _add_user(db, reg["organization_id"], "mem@example.com", role="member")
        mem = (await _login(client, reg["slug"], "mem@example.com")).json()
        r = await self._create(client, mem["access_token"], ["workflows:read"])
        assert r.status_code == 403 and r.json()["detail"]["missing"] == ["api_keys:manage"]

    async def test_api_key_cannot_mint_keys_or_logout(self, client):
        reg = await _register(client)
        key = (await self._create(client, reg["access_token"], ["api_keys:manage"])).json()["key"]
        r = await client.post("/api/axon/api-keys", headers={"X-API-Key": key},
                              json={"name": "child", "scopes": ["api_keys:manage"]})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "user_required"
        r = await client.post("/api/axon/auth/logout", headers={"X-API-Key": key})
        assert r.status_code == 403

    async def test_expired_key_rejected(self, client, db):
        reg = await _register(client)
        key = (await self._create(client, reg["access_token"], ["workflows:read"])).json()
        async with db.system_session("test") as s:
            await s.execute(text("UPDATE axon.api_keys SET expires_at = now() - interval '1 second' WHERE id = :k"),
                            {"k": key["id"]})
        assert (await _me(client, {"X-API-Key": key["key"]})).status_code == 401

    async def test_past_expiry_rejected_at_creation(self, client):
        reg = await _register(client)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        r = await self._create(client, reg["access_token"], ["workflows:read"], expires_at=past)
        assert r.status_code == 422

    async def test_forged_key_with_real_prefix_rejected(self, client):
        reg = await _register(client)
        key = (await self._create(client, reg["access_token"], ["workflows:read"])).json()
        forged = key["prefix"] + "_" + "A" * 43
        assert (await _me(client, {"X-API-Key": forged})).status_code == 401

    async def test_keys_are_isolated_between_orgs(self, client):
        a = await _register(client)
        b = await _register(client)
        key_a = (await self._create(client, a["access_token"], ["workflows:read"])).json()
        listed = (await client.get("/api/axon/api-keys", headers=bearer(b["access_token"]))).json()
        assert key_a["id"] not in {k["id"] for k in listed}
        r = await client.delete(f"/api/axon/api-keys/{key_a['id']}", headers=bearer(b["access_token"]))
        assert r.status_code == 404
        assert (await _me(client, {"X-API-Key": key_a["key"]})).status_code == 200

    async def test_principal_binds_tenant_for_db_dependencies(self, client, db):
        reg = await _register(client)
        app = FastAPI()

        @app.get("/org", dependencies=[Depends(auth.authenticate)])
        async def org(session: Annotated[AsyncSession, Depends(get_db_session)]):
            return {"ids": [str(i) for i in (await session.execute(
                text("SELECT id FROM axon.organizations"))).scalars().all()]}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/org", headers=bearer(reg["access_token"]))
            assert r.json() == {"ids": [reg["organization_id"]]}
            assert (await c.get("/org")).status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# Webhooks
# ═════════════════════════════════════════════════════════════════════════════

@pg
class TestWebhooks:
    async def _endpoint(self, client):
        reg = await _register(client)
        r = await client.post("/api/axon/webhook-endpoints", headers=bearer(reg["access_token"]),
                              json={"name": "crm", "tolerance_seconds": 300})
        assert r.status_code == 201, r.text
        return reg, r.json()

    @staticmethod
    def _headers(secret: str, delivery: str, body: bytes, ts: int | None = None) -> dict:
        return {sec.SIGNATURE_HEADER: sec.sign_webhook(secret, delivery_id=delivery, body=body, timestamp=ts),
                sec.DELIVERY_HEADER: delivery, "Content-Type": "application/json"}

    async def test_signed_delivery_accepted_once(self, client):
        _, hook = await self._endpoint(client)
        body = b'{"event":"lead.created"}'
        headers = self._headers(hook["secret"], "dlv_00000001", body)
        r = await client.post(hook["url"], content=body, headers=headers)
        assert r.status_code == 202 and r.json()["delivery_id"] == "dlv_00000001"
        replay = await client.post(hook["url"], content=body, headers=headers)
        assert replay.status_code == 409

    async def test_secret_is_encrypted_at_rest(self, client, db):
        _, hook = await self._endpoint(client)
        async with db.system_session("test") as s:
            stored = (await s.execute(text("SELECT secret_ciphertext FROM axon.webhook_endpoints WHERE id = :w"),
                                      {"w": hook["id"]})).scalar_one()
        assert stored.startswith("axv1.") and hook["secret"] not in stored

    async def test_bad_signature_and_unknown_endpoint_look_the_same(self, client):
        _, hook = await self._endpoint(client)
        body = b"{}"
        bad = self._headers("whsec_wrong", "dlv_00000002", body)
        r1 = await client.post(hook["url"], content=body, headers=bad)
        r2 = await client.post(f"/api/axon/webhooks/{uuid.uuid4()}", content=body,
                               headers=self._headers(hook["secret"], "dlv_00000003", body))
        assert r1.status_code == r2.status_code == 401
        assert r1.json() == r2.json()

    async def test_tampered_body_rejected(self, client):
        _, hook = await self._endpoint(client)
        headers = self._headers(hook["secret"], "dlv_00000004", b'{"amount":1}')
        r = await client.post(hook["url"], content=b'{"amount":1000}', headers=headers)
        assert r.status_code == 401

    async def test_stale_delivery_rejected(self, client):
        _, hook = await self._endpoint(client)
        body = b"{}"
        headers = self._headers(hook["secret"], "dlv_00000005", body, ts=int(time.time()) - 3600)
        assert (await client.post(hook["url"], content=body, headers=headers)).status_code == 401

    async def test_oversized_body_rejected(self, client):
        _, hook = await self._endpoint(client)
        body = b"x" * (1024 * 1024 + 1)
        headers = self._headers(hook["secret"], "dlv_00000006", body)
        assert (await client.post(hook["url"], content=body, headers=headers)).status_code == 413

    async def test_rotation_invalidates_old_secret(self, client):
        reg, hook = await self._endpoint(client)
        r = await client.post(f"/api/axon/webhook-endpoints/{hook['id']}/rotate-secret",
                              headers=bearer(reg["access_token"]))
        assert r.status_code == 200
        new_secret = r.json()["secret"]
        body = b"{}"
        old = await client.post(hook["url"], content=body, headers=self._headers(hook["secret"], "dlv_00000007", body))
        new = await client.post(hook["url"], content=body, headers=self._headers(new_secret, "dlv_00000008", body))
        assert old.status_code == 401 and new.status_code == 202

    async def test_creating_endpoints_needs_scope(self, client, db):
        reg = await _register(client)
        await _add_user(db, reg["organization_id"], "viewer@example.com", role="member")
        mem = (await _login(client, reg["slug"], "viewer@example.com")).json()
        r = await client.post("/api/axon/webhook-endpoints", headers=bearer(mem["access_token"]),
                              json={"name": "x"})
        assert r.status_code == 403
