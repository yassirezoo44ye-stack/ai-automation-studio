"""Account export and deletion against real PostgreSQL (isolated schema).

Run with ACCOUNT_TEST_DATABASE_URL (CI reuses the study test database).
"""

import json
import os
import uuid
from unittest.mock import patch

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.billing.subscriptions import init_org_subscriptions_schema
from app.core import db as core_db
from app.core.db import init_db
from app.core.jwt_utils import make_access_token
from app.core.passwords import hash_password
from app.routers import auth_users
from app.services import account_lifecycle as lifecycle
from app.tenancy import init_tenancy_schema

_URL = os.getenv("ACCOUNT_TEST_DATABASE_URL") or os.getenv("STUDY_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _URL, reason="Isolated ACCOUNT_TEST_DATABASE_URL not configured"),
]


@pytest_asyncio.fixture
async def db(monkeypatch):
    schema = "account_test_" + uuid.uuid4().hex
    setup = await asyncpg.connect(_URL)
    await setup.execute(f'CREATE SCHEMA "{schema}"')
    pool = None
    try:
        pool = await asyncpg.create_pool(
            _URL, min_size=1, max_size=4, server_settings={"search_path": f"{schema},public"}
        )
        monkeypatch.setattr(core_db, "_pool", pool)
        async with pool.acquire() as conn:
            await init_db(conn)
        await core_db.ensure_tasks_table()  # also creates user_sessions
        async with pool.acquire() as conn:
            await init_tenancy_schema(conn)
            await init_org_subscriptions_schema(conn)
        monkeypatch.setattr(auth_users, "get_pool", lambda: pool)

        async def _no_audit(*a, **k):
            return None

        async def _no_revoke(*a, **k):
            return None

        monkeypatch.setattr(auth_users, "write_audit", _no_audit)
        monkeypatch.setattr(auth_users, "revoke_user_tokens", _no_revoke)
        yield pool
    finally:
        if pool:
            await pool.close()
        await setup.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await setup.close()


def _client():
    app = FastAPI()
    app.include_router(auth_users.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _user(conn, email, password="correct horse battery"):
    uid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, name, password_hash, email_verified) VALUES ($1,$2,$3,$4,true)",
        uid, email, "Test", hash_password(password) if password else None,
    )
    return uid


async def _org(conn, name, members):
    oid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ($1,$2,$3)", oid, name, f"{name}-{oid.hex[:6]}"
    )
    for uid, role in members:
        await conn.execute(
            "INSERT INTO organization_members (organization_id, user_id, role) VALUES ($1,$2,$3)",
            oid, uid, role,
        )
    return oid


def _auth(uid, email):
    return {"Authorization": f"Bearer {make_access_token(str(uid), email)}"}


async def test_export_includes_owned_rows_and_never_secrets(db):
    async with db.acquire() as conn:
        uid = await _user(conn, "me@example.com")
        other = await _user(conn, "other@example.com")
        await conn.execute(
            "INSERT INTO projects (user_id, name) VALUES ($1,'Mine'),($2,'Theirs')", uid, other
        )
        await conn.execute(
            "INSERT INTO user_sessions (id, user_id, refresh_token, ip_address, user_agent, expires_at) "
            "VALUES ($1,$2,'super-secret-refresh','1.2.3.4','UA',NOW() + interval '1 day')",
            uuid.uuid4(), uid,
        )
        await conn.execute(
            "INSERT INTO subscriptions (email, stripe_subscription_id, status) VALUES ($1,'sub_x','active')",
            "me@example.com",
        )
    async with _client() as c:
        r = await c.get("/api/auth/me/export", headers=_auth(uid, "me@example.com"))
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["profile"]["email"] == "me@example.com"
    assert "password_hash" not in body["profile"]
    assert [p["name"] for p in body["data"]["projects"]] == ["Mine"]
    assert body["data"]["user_sessions"][0]["ip_address"] == "1.2.3.4"
    assert body["data"]["subscriptions"][0]["status"] == "active"
    raw = json.dumps(body)
    assert "super-secret-refresh" not in raw and "refresh_token" not in raw
    assert "$argon2" not in raw and "$2b$" not in raw


async def test_oauth_account_can_delete_by_confirming_email(db):
    async with db.acquire() as conn:
        uid = await _user(conn, "oauth@example.com", password=None)
    async with _client() as c:
        r = await c.request(
            "DELETE", "/api/auth/me", json={"email": "OAuth@example.com"},
            headers=_auth(uid, "oauth@example.com"),
        )
    assert r.status_code == 200, r.text
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM users") == 0


async def test_password_account_still_needs_password(db):
    async with db.acquire() as conn:
        uid = await _user(conn, "pw@example.com")
    async with _client() as c:
        r = await c.request(
            "DELETE", "/api/auth/me", json={"email": "pw@example.com"},
            headers=_auth(uid, "pw@example.com"),
        )
        assert r.status_code == 400
        r = await c.request(
            "DELETE", "/api/auth/me", json={"email": "pw@example.com", "password": "wrong-password"},
            headers=_auth(uid, "pw@example.com"),
        )
        assert r.status_code == 400
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM users") == 1


async def test_delete_cancels_billing_and_removes_solo_org(db):
    async with db.acquire() as conn:
        uid = await _user(conn, "solo@example.com")
        oid = await _org(conn, "solo", [(uid, "owner")])
        await conn.execute(
            "INSERT INTO org_subscriptions (organization_id, stripe_subscription_id, status, plan_id) "
            "VALUES ($1,'sub_org','active','pro')", oid,
        )
        await conn.execute(
            "INSERT INTO subscriptions (email, stripe_subscription_id, status) VALUES ($1,'sub_legacy','active')",
            "solo@example.com",
        )
    cancelled = []
    with patch("stripe.api_key", "sk_test_x"), patch(
        "stripe.Subscription.cancel", side_effect=lambda sid: cancelled.append(sid)
    ):
        async with _client() as c:
            r = await c.request(
                "DELETE", "/api/auth/me",
                json={"email": "solo@example.com", "password": "correct horse battery"},
                headers=_auth(uid, "solo@example.com"),
            )
    assert r.status_code == 200, r.text
    assert sorted(cancelled) == ["sub_legacy", "sub_org"]
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT deleted_at IS NOT NULL FROM organizations WHERE id=$1", oid)
        assert await conn.fetchval("SELECT status FROM org_subscriptions WHERE organization_id=$1", oid) == "canceled"
        assert await conn.fetchval("SELECT status FROM subscriptions") == "canceled"
        assert await conn.fetchval("SELECT count(*) FROM users") == 0


async def test_billing_failure_deletes_nothing(db):
    import stripe

    async with db.acquire() as conn:
        uid = await _user(conn, "fail@example.com")
        oid = await _org(conn, "fail", [(uid, "owner")])
        await conn.execute(
            "INSERT INTO org_subscriptions (organization_id, stripe_subscription_id, status, plan_id) "
            "VALUES ($1,'sub_fail','active','pro')", oid,
        )
    with patch("stripe.api_key", "sk_test_x"), patch(
        "stripe.Subscription.cancel", side_effect=stripe.APIConnectionError("down")
    ):
        async with _client() as c:
            r = await c.request(
                "DELETE", "/api/auth/me",
                json={"email": "fail@example.com", "password": "correct horse battery"},
                headers=_auth(uid, "fail@example.com"),
            )
    assert r.status_code == 502
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM users") == 1
        assert await conn.fetchval("SELECT deleted_at FROM organizations WHERE id=$1", oid) is None


async def test_billing_unconfigured_with_active_subscription_blocks(db):
    async with db.acquire() as conn:
        uid = await _user(conn, "nokey@example.com")
        await conn.execute(
            "INSERT INTO subscriptions (email, stripe_subscription_id, status) VALUES ($1,'sub_k','active')",
            "nokey@example.com",
        )
    with patch("stripe.api_key", None):
        async with _client() as c:
            r = await c.request(
                "DELETE", "/api/auth/me",
                json={"email": "nokey@example.com", "password": "correct horse battery"},
                headers=_auth(uid, "nokey@example.com"),
            )
    assert r.status_code == 502
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM users") == 1


async def test_sole_owner_of_shared_org_must_transfer_first(db):
    async with db.acquire() as conn:
        uid = await _user(conn, "boss@example.com")
        mate = await _user(conn, "mate@example.com")
        await _org(conn, "team", [(uid, "owner"), (mate, "developer")])
    async with _client() as c:
        r = await c.request(
            "DELETE", "/api/auth/me",
            json={"email": "boss@example.com", "password": "correct horse battery"},
            headers=_auth(uid, "boss@example.com"),
        )
    assert r.status_code == 409
    assert r.json()["detail"]["organizations"] == ["team"]
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM users") == 2


async def test_co_owned_org_survives_and_keeps_billing(db):
    async with db.acquire() as conn:
        uid = await _user(conn, "a@example.com")
        co = await _user(conn, "b@example.com")
        oid = await _org(conn, "shared", [(uid, "owner"), (co, "owner")])
        await conn.execute(
            "INSERT INTO org_subscriptions (organization_id, stripe_subscription_id, status, plan_id) "
            "VALUES ($1,'sub_shared','active','pro')", oid,
        )
    with patch("stripe.api_key", "sk_test_x"), patch("stripe.Subscription.cancel") as cancel:
        async with _client() as c:
            r = await c.request(
                "DELETE", "/api/auth/me",
                json={"email": "a@example.com", "password": "correct horse battery"},
                headers=_auth(uid, "a@example.com"),
            )
    assert r.status_code == 200, r.text
    cancel.assert_not_called()
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT deleted_at FROM organizations WHERE id=$1", oid) is None
        assert await conn.fetchval("SELECT status FROM org_subscriptions") == "active"


async def test_register_records_terms_version(db):
    from app.core.legal import TERMS_VERSION

    async def _no_mail(*a, **k):
        return None

    with patch.object(auth_users, "send_verification_email", _no_mail):
        async with _client() as c:
            r = await c.post(
                "/api/auth/register",
                json={"name": "New", "email": "new@example.com", "password": "long enough pw"},
            )
    assert r.status_code == 201, r.text
    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT terms_version, terms_accepted_at FROM users")
    assert row["terms_version"] == TERMS_VERSION and row["terms_accepted_at"] is not None
