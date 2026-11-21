"""Real local PostgreSQL + ASGI journeys; no provider requests or production data.

Run after scripts/ci_schema_check.py with LOCAL_SECURITY_TEST_DATABASE_URL
pointing at the disposable loopback database. No production DSN is accepted.
"""
import asyncio
import datetime
import os
import secrets
import uuid
from urllib.parse import urlparse

import asyncpg
import httpx
import pytest
import pytest_asyncio

from app.core import db
from app.core.passwords import hash_password, verify_password
from app.factory import create_app
from app.routers.auth_users import _reset_token_digest


@pytest_asyncio.fixture
async def journey():
    dsn = os.getenv("LOCAL_SECURITY_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Disposable local PostgreSQL required")
    parsed = urlparse(dsn)
    loopback = parsed.hostname in {"127.0.0.1", "localhost"}
    local_db = loopback and parsed.path == "/flow_integration"
    ci_db = os.getenv("CI") == "true" and loopback and parsed.path == "/test_axon" and parsed.username == "test"
    if not (local_db or ci_db):
        pytest.fail("Refusing a database other than the dedicated local integration database")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    previous = db.get_pool()
    db.set_pool(pool)
    users = [uuid.uuid4(), uuid.uuid4()]
    password = "Local-Test-Password-2026"
    emails = [f"local-flow-{uid.hex}@example.com" for uid in users]
    try:
        async with pool.acquire() as conn:
            for uid, email in zip(users, emails):
                await conn.execute(
                    "INSERT INTO users(id,email,name,password_hash,email_verified) VALUES($1,$2,$3,$4,true)",
                    uid, email, "Local security test", hash_password(password),
                )
        app = create_app()
        transport = httpx.ASGITransport(app=app, client=(f"127.0.0.{users[0].int % 200 + 2}", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield client, pool, users, emails, password
    finally:
        # Only records created by this fixture in the disposable DB.
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE id=ANY($1::uuid[])", users)
        db.set_pool(previous)
        await pool.close()


async def login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_project_persistence_and_cross_user_denial(journey):
    client, pool, users, emails, password = journey
    a, b = [await login(client, email, password) for email in emails]
    headers = {"Authorization": f"Bearer {a['access_token']}"}
    name = "محلي <script>alert(1)</script> ' ; SELECT 1"
    created = await client.post("/api/projects", headers=headers, json={"name": name})
    assert created.status_code == 201, created.text
    pid = uuid.UUID(created.json()["id"])
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id,name FROM projects WHERE id=$1", pid)
    assert row["user_id"] == users[0]
    assert row["name"] == name
    allowed = await client.get(f"/api/projects/{pid}", headers=headers)
    denied = await client.get(f"/api/projects/{pid}", headers={"Authorization": f"Bearer {b['access_token']}"})
    assert allowed.status_code == 200
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_twenty_refreshes_rotate_real_sessions_without_lockout(journey):
    client, pool, users, emails, password = journey
    session = await login(client, emails[0], password)
    original = current = session["refresh_token"]
    for _ in range(20):
        response = await client.post("/api/auth/refresh", json={"refresh_token": current})
        assert response.status_code == 200, response.text
        rotated = response.json()["refresh_token"]
        assert rotated != current
        current = rotated
    replay = await client.post("/api/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM user_sessions WHERE user_id=$1 AND refresh_token=$2", users[0], current) == 1


@pytest.mark.asyncio
async def test_password_reset_consumed_once_under_real_concurrency(journey):
    client, pool, users, emails, password = journey
    await login(client, emails[0], password)
    raw = secrets.token_urlsafe(32)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO password_reset_tokens(token,user_id,expires_at) VALUES($1,$2,$3)",
            _reset_token_digest(raw), users[0], datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30),
        )
    replacement = "Local-Replacement-Password-2026"
    responses = await asyncio.gather(*[
        client.post("/api/auth/reset-password", json={"token": raw, "password": replacement})
        for _ in range(2)
    ])
    assert sorted(r.status_code for r in responses) == [200, 400]
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM password_reset_tokens WHERE user_id=$1", users[0]) == 0
        assert await conn.fetchval("SELECT count(*) FROM user_sessions WHERE user_id=$1", users[0]) == 0
        stored = await conn.fetchval("SELECT password_hash FROM users WHERE id=$1", users[0])
    assert verify_password(replacement, stored)
    assert not verify_password(password, stored)


@pytest.mark.asyncio
async def test_validation_never_reflects_rejected_password(journey):
    client, *_ = journey
    secret = "Never-Reflect-Local-Test-Password-" * 8
    response = await client.post("/api/auth/register", json={"name": "Local test", "email": "test@example.com", "password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert all("input" not in error and "ctx" not in error for error in response.json()["errors"])
