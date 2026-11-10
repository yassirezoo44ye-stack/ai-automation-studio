"""
Axon tenant-scoped database layer (app/core/db.py).

Unit tests run everywhere. The PostgreSQL tests apply init_db.sql to a
throwaway database and prove tenant isolation end to end; they run when
AXON_TEST_DATABASE_URL points at a server where the login may CREATE DATABASE
(and CREATE ROLE, for axon_app), e.g.:

    AXON_TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres pytest tests/test_axon_db.py
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import TokenCipher, settings
from app.core.db import (
    REQUEST_TENANT_ATTR,
    Database,
    ScopeError,
    TenantContext,
    TenantContextError,
    TenantDep,
    build_async_url,
    current_tenant,
    require_scopes,
    scope_covers,
)

TENANT = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


# ═════════════════════════════════════════════════════════════════════════════
# Unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestTenantContext:
    def test_valid_context(self):
        ctx = TenantContext(TENANT, USER, {"workflows:read", "agents:*"})
        assert isinstance(ctx.scopes, frozenset)
        assert ctx.has_scope("workflows:read")
        assert ctx.has_scope("agents:execute")
        assert not ctx.has_scope("workflows:write")

    @pytest.mark.parametrize("tenant", [str(TENANT), None, 42])
    def test_tenant_must_be_uuid(self, tenant):
        with pytest.raises(TenantContextError):
            TenantContext(tenant)  # type: ignore[arg-type]

    @pytest.mark.parametrize("scope", [
        "workflows", "Workflows:read", "workflows:read extra", "a:b;DROP", "", "x: y",
    ])
    def test_malformed_scopes_rejected(self, scope):
        # Spaces matter: scopes travel to Postgres space-separated.
        with pytest.raises(TenantContextError):
            TenantContext(TENANT, scopes=frozenset({scope}))

    def test_require_scope(self):
        ctx = TenantContext(TENANT, scopes=frozenset({"members:read"}))
        ctx.require_scope("members:read")
        with pytest.raises(ScopeError, match="members:manage"):
            ctx.require_scope("members:read", "members:manage")

    def test_context_is_immutable(self):
        ctx = TenantContext(TENANT)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.tenant_id = uuid.uuid4()  # type: ignore[misc]


@pytest.mark.parametrize("held, required, expected", [
    ({"a:read"}, "a:read", True),
    ({"a:read"}, "a:write", False),
    ({"a:*"}, "a:write", True),
    ({"a:*"}, "b:read", False),
    ({"*"}, "anything:at_all", True),
    (set(), "a:read", False),
])
def test_scope_covers(held, required, expected):
    assert scope_covers(frozenset(held), required) is expected


class TestBuildAsyncUrl:
    def test_driver_rewritten(self):
        url, args = build_async_url("postgresql://u:p@db:5432/axon")
        assert url.drivername == "postgresql+asyncpg"
        assert url.database == "axon"
        assert args == {}

    def test_postgres_alias_accepted(self):
        url, _ = build_async_url("postgres://u:p@db/axon")
        assert url.drivername == "postgresql+asyncpg"

    @pytest.mark.parametrize("mode, expected", [("require", "require"), ("disable", False),
                                                ("verify-full", "verify-full")])
    def test_sslmode_moved_to_connect_args(self, mode, expected):
        url, args = build_async_url(f"postgresql://u:p@db/axon?sslmode={mode}&application_name=x")
        assert "sslmode" not in url.query
        assert url.query.get("application_name") == "x"
        assert args["ssl"] == expected

    def test_bad_sslmode_rejected(self):
        with pytest.raises(ValueError):
            build_async_url("postgresql://u:p@db/axon?sslmode=sometimes")

    def test_non_postgres_rejected(self):
        with pytest.raises(ValueError):
            build_async_url("mysql://u:p@db/axon")


class TestFastAPIDependencies:
    @staticmethod
    def _app(ctx: TenantContext | None) -> FastAPI:
        app = FastAPI()

        @app.middleware("http")
        async def fake_auth(request: Request, call_next):
            if ctx is not None:
                setattr(request.state, REQUEST_TENANT_ATTR, ctx)
            return await call_next(request)

        @app.get("/who")
        async def who(c: TenantDep):
            return {"tenant": str(c.tenant_id)}

        @app.post("/run", dependencies=[Depends(require_scopes("workflows:execute"))])
        async def run():
            return {"ok": True}

        return app

    async def _call(self, ctx, method, path):
        async with AsyncClient(transport=ASGITransport(app=self._app(ctx)), base_url="http://t") as c:
            return await c.request(method, path)

    async def test_missing_context_is_401(self):
        assert (await self._call(None, "GET", "/who")).status_code == 401
        assert (await self._call(None, "POST", "/run")).status_code == 401

    async def test_context_passed_through(self):
        r = await self._call(TenantContext(TENANT), "GET", "/who")
        assert r.json() == {"tenant": str(TENANT)}

    async def test_scope_enforced(self):
        no = TenantContext(TENANT, scopes=frozenset({"workflows:read"}))
        yes = TenantContext(TENANT, scopes=frozenset({"workflows:*"}))
        assert (await self._call(no, "POST", "/run")).status_code == 403
        assert (await self._call(yes, "POST", "/run")).status_code == 200

    def test_require_scopes_rejects_bad_declaration(self):
        with pytest.raises(ValueError):
            require_scopes("not a scope")


# ═════════════════════════════════════════════════════════════════════════════
# PostgreSQL integration tests
# ═════════════════════════════════════════════════════════════════════════════

ADMIN_URL = os.getenv("AXON_TEST_DATABASE_URL", "")
INIT_SQL = Path(__file__).resolve().parent.parent / "init_db.sql"

pg = pytest.mark.skipif(not ADMIN_URL, reason="AXON_TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def pg_url():
    """Create a throwaway database, apply init_db.sql twice (idempotency), drop it after."""
    import asyncpg
    from sqlalchemy.engine import make_url

    name = f"axon_test_{uuid.uuid4().hex[:10]}"
    admin = make_url(ADMIN_URL)
    target = admin.set(database=name).render_as_string(hide_password=False)
    script = INIT_SQL.read_text()

    async def setup():
        conn = await asyncpg.connect(ADMIN_URL)
        try:
            await conn.execute(f'CREATE DATABASE "{name}"')
        finally:
            await conn.close()
        conn = await asyncpg.connect(target)
        try:
            await conn.execute(script)
            await conn.execute(script)
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


@pytest.fixture
async def db(pg_url):
    # pool_size=1 / no overflow: every session reuses the SAME connection, so
    # any tenant state leaking across checkouts would be caught.
    cfg = settings.model_copy(update={
        "database_url": SecretStr(pg_url), "db_pool_size": 1, "db_max_overflow": 0,
        "db_rls_role": "axon_app",
    })
    database = Database(cfg, url=pg_url)
    yield database
    await database.dispose()


ALL_SCOPES = frozenset({
    "tenant:read", "tenant:manage", "members:read", "members:manage", "roles:manage",
    "api_keys:manage", "integrations:read", "integrations:manage", "webhooks:manage",
    "workflows:read", "workflows:write", "workflows:execute", "agents:read", "agents:write",
    "agents:execute", "billing:read", "billing:manage", "audit:read",
})
ADMIN_SCOPES = ALL_SCOPES - {"tenant:manage", "billing:manage"}


async def _scalar(session, sql, **params):
    from sqlalchemy import text
    return (await session.execute(text(sql), params)).scalar()


async def _rows(session, sql, **params):
    from sqlalchemy import text
    return (await session.execute(text(sql), params)).all()


@pytest.fixture
async def world(db):
    """Two tenants, each with an owner; tenant A also has an admin and a viewer."""
    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8]
    ids: dict[str, uuid.UUID] = {}
    async with db.system_session("test fixture") as s:
        for who in ("owner_a", "owner_b", "admin_a", "viewer_a"):
            ids[who] = await _scalar(
                s, "INSERT INTO axon.users (email) VALUES (:e) RETURNING id", e=f"{who}-{tag}@axon.test",
            )
        ids["tenant_a"] = await _scalar(s, "SELECT axon.provision_tenant(:s, 'A', :o)", s=f"a-{tag}", o=ids["owner_a"])
        ids["tenant_b"] = await _scalar(s, "SELECT axon.provision_tenant(:s, 'B', :o)", s=f"b-{tag}", o=ids["owner_b"])
        for who, role in (("admin_a", "admin"), ("viewer_a", "viewer")):
            await s.execute(text(
                "INSERT INTO axon.memberships (tenant_id, user_id, role_id) "
                "SELECT :t, :u, id FROM axon.roles WHERE tenant_id IS NULL AND key = :r"
            ), {"t": ids["tenant_a"], "u": ids[who], "r": role})
    return ids


def ctx(world, tenant: str, user: str, scopes=ALL_SCOPES) -> TenantContext:
    return TenantContext(world[tenant], world[user], frozenset(scopes))


@pg
class TestTenantIsolation:
    async def test_session_sees_only_its_tenant(self, db, world):
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            tenants = {r[0] for r in await _rows(s, "SELECT id FROM axon.tenants")}
            members = {r[0] for r in await _rows(s, "SELECT tenant_id FROM axon.memberships")}
            assert tenants == {world["tenant_a"]}
            assert members == {world["tenant_a"]}
            assert current_tenant().tenant_id == world["tenant_a"]
        assert current_tenant() is None

        async with db.tenant_session(ctx(world, "tenant_b", "owner_b")) as s:
            assert {r[0] for r in await _rows(s, "SELECT id FROM axon.tenants")} == {world["tenant_b"]}

    async def test_runtime_role_is_applied(self, db, world):
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            assert await _scalar(s, "SELECT current_user") == "axon_app"
            assert await _scalar(s, "SELECT axon.current_tenant_id()") == world["tenant_a"]

    async def test_users_of_other_tenants_are_invisible(self, db, world):
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            visible = {r[0] for r in await _rows(s, "SELECT id FROM axon.users")}
        assert world["owner_b"] not in visible
        assert {world["owner_a"], world["admin_a"], world["viewer_a"]} <= visible

    async def test_session_without_tenant_refuses_to_run(self, db, world):
        from sqlalchemy import text
        session = db._factory()
        try:
            with pytest.raises(TenantContextError):
                await session.execute(text("SELECT 1"))
        finally:
            await session.close()

    async def test_axon_app_without_tenant_sees_nothing(self, db, world):
        """Fail closed at the database layer, not only in Python."""
        async with db.engine.connect() as conn:
            from sqlalchemy import text
            await conn.execute(text("SET LOCAL ROLE axon_app"))
            for table in ("tenants", "memberships", "api_keys", "integration_credentials",
                          "webhook_endpoints", "audit_events", "roles"):
                assert (await conn.execute(text(f"SELECT count(*) FROM axon.{table}"))).scalar() == 0, table
            await conn.rollback()

    async def test_cannot_write_into_another_tenant(self, db, world):
        from sqlalchemy.exc import DBAPIError
        cipher = TokenCipher.from_spec("k1:" + "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo")
        token = cipher.encrypt("t", tenant_id=world["tenant_b"], purpose="integration:slack")
        with pytest.raises(DBAPIError, match="row-level security"):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(
                    __import__("sqlalchemy").text(
                        "INSERT INTO axon.integration_credentials (tenant_id, provider, ciphertext, key_id) "
                        "VALUES (:t, 'slack', :c, 'k1')"
                    ),
                    {"t": world["tenant_b"], "c": token},
                )

    async def test_cannot_move_rows_to_another_tenant(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(__import__("sqlalchemy").text(
                    "UPDATE axon.tenants SET id = :b WHERE id = :a"), {"a": world["tenant_a"], "b": world["tenant_b"]})

    async def test_context_survives_mid_session_commit(self, db, world):
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.tenants") == 1
            await s.commit()  # GUCs are transaction-local; after_begin must re-apply them
            assert await _scalar(s, "SELECT axon.current_tenant_id()") == world["tenant_a"]
            assert await _scalar(s, "SELECT current_user") == "axon_app"

    async def test_no_leak_to_next_pooled_checkout(self, db, world):
        from sqlalchemy import text
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            pid = await _scalar(s, "SELECT pg_backend_pid()")
        async with db.engine.connect() as conn:
            assert (await conn.execute(text("SELECT pg_backend_pid()"))).scalar() == pid  # same connection
            assert (await conn.execute(text("SELECT axon.current_tenant_id()"))).scalar() is None
            assert (await conn.execute(text("SELECT current_user"))).scalar() != "axon_app"
            assert (await conn.execute(text("SELECT axon.current_scopes()"))).scalar() == []

    async def test_error_rolls_back_and_releases_context(self, db, world):
        with pytest.raises(RuntimeError):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(__import__("sqlalchemy").text(
                    "UPDATE axon.tenants SET name = 'renamed' WHERE id = :t"), {"t": world["tenant_a"]})
                raise RuntimeError("boom")
        assert current_tenant() is None
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            assert await _scalar(s, "SELECT name FROM axon.tenants") == "A"

    async def test_system_session_rejected_inside_tenant_session(self, db, world):
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")):
            with pytest.raises(TenantContextError):
                async with db.system_session("nested"):
                    pass

    async def test_system_session_requires_reason(self, db):
        with pytest.raises(ValueError):
            async with db.system_session(" "):
                pass

    async def test_concurrent_sessions_keep_their_own_tenant(self, pg_url, world):
        cfg = settings.model_copy(update={"db_pool_size": 4, "db_max_overflow": 0})
        database = Database(cfg, url=pg_url)
        try:
            async def probe(tenant, user):
                async with database.tenant_session(ctx(world, tenant, user)) as s:
                    await asyncio.sleep(0.01)
                    seen = await _scalar(s, "SELECT id FROM axon.tenants")
                    return seen, current_tenant().tenant_id

            results = await asyncio.gather(*(
                probe(*(("tenant_a", "owner_a") if i % 2 else ("tenant_b", "owner_b"))) for i in range(12)
            ))
            for seen, bound in results:
                assert seen == bound
        finally:
            await database.dispose()


@pg
class TestScopesAndRbac:
    async def test_viewer_cannot_read_credentials_or_audit(self, db, world):
        viewer = ctx(world, "tenant_a", "viewer_a", {"tenant:read", "members:read", "workflows:read", "agents:read"})
        cipher = TokenCipher.from_spec("k1:" + "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo")
        from sqlalchemy import text
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            await s.execute(text(
                "INSERT INTO axon.integration_credentials (tenant_id, provider, ciphertext, key_id) "
                "VALUES (:t, 'github', :c, 'k1')"),
                {"t": world["tenant_a"], "c": cipher.encrypt("gh", tenant_id=world["tenant_a"], purpose="integration:github")})
            await s.execute(text("INSERT INTO axon.audit_events (tenant_id, action) VALUES (:t, 'integration.connect')"),
                            {"t": world["tenant_a"]})
        async with db.tenant_session(viewer) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.integration_credentials") == 0
            assert await _scalar(s, "SELECT count(*) FROM axon.audit_events") == 0
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.integration_credentials") == 1
            assert await _scalar(s, "SELECT count(*) FROM axon.audit_events") >= 1

    async def test_admin_cannot_promote_anyone_to_owner(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="cannot grant scope"):
            async with db.tenant_session(ctx(world, "tenant_a", "admin_a", ADMIN_SCOPES)) as s:
                await s.execute(__import__("sqlalchemy").text(
                    "UPDATE axon.memberships SET role_id = (SELECT id FROM axon.roles WHERE key='owner' AND tenant_id IS NULL) "
                    "WHERE user_id = :u"), {"u": world["admin_a"]})

    async def test_member_without_members_manage_cannot_change_roles(self, db, world):
        viewer = ctx(world, "tenant_a", "viewer_a", {"members:read"})
        async with db.tenant_session(viewer) as s:
            res = await s.execute(__import__("sqlalchemy").text(
                "UPDATE axon.memberships SET status = 'suspended' WHERE user_id = :u"), {"u": world["owner_a"]})
            assert res.rowcount == 0  # RLS hides the rows from UPDATE entirely

    async def test_api_key_cannot_exceed_creator_scopes(self, db, world):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        dev = ctx(world, "tenant_a", "admin_a", {"api_keys:manage", "workflows:read"})
        insert = text(
            "INSERT INTO axon.api_keys (tenant_id, name, key_prefix, key_hash, scopes) "
            "VALUES (:t, 'k', :p, :h, :s)")
        async with db.tenant_session(dev) as s:
            await s.execute(insert, {"t": world["tenant_a"], "p": "axk_" + uuid.uuid4().hex[:12],
                                     "h": os.urandom(32), "s": ["workflows:read"]})
        with pytest.raises(DBAPIError, match="cannot grant scope"):
            async with db.tenant_session(dev) as s:
                await s.execute(insert, {"t": world["tenant_a"], "p": "axk_" + uuid.uuid4().hex[:12],
                                         "h": os.urandom(32), "s": ["billing:manage"]})
        with pytest.raises(DBAPIError, match="unknown scope"):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(insert, {"t": world["tenant_a"], "p": "axk_" + uuid.uuid4().hex[:12],
                                         "h": os.urandom(32), "s": ["root:everything"]})

    async def test_api_key_lookup_is_pre_auth_and_preserves_context(self, db, world):
        from sqlalchemy import text
        prefix = "axk_" + uuid.uuid4().hex[:12]
        digest = os.urandom(32)
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            await s.execute(text(
                "INSERT INTO axon.api_keys (tenant_id, name, key_prefix, key_hash, scopes) "
                "VALUES (:t, 'ci', :p, :h, ARRAY['workflows:execute'])"),
                {"t": world["tenant_a"], "p": prefix, "h": digest})
        # From tenant B's session the definer function still resolves the key...
        async with db.tenant_session(ctx(world, "tenant_b", "owner_b")) as s:
            row = (await s.execute(text("SELECT * FROM axon.lookup_api_key(:p)"), {"p": prefix})).one()
            assert row.tenant_id == world["tenant_a"] and bytes(row.key_hash) == digest
            # ...without disturbing B's own context afterwards.
            assert await _scalar(s, "SELECT axon.current_tenant_id()") == world["tenant_b"]
            assert await _scalar(s, "SELECT count(*) FROM axon.api_keys") == 0

    async def test_api_key_material_is_immutable(self, db, world):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        prefix = "axk_" + uuid.uuid4().hex[:12]
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            await s.execute(text(
                "INSERT INTO axon.api_keys (tenant_id, name, key_prefix, key_hash) VALUES (:t, 'k', :p, :h)"),
                {"t": world["tenant_a"], "p": prefix, "h": os.urandom(32)})
        with pytest.raises(DBAPIError, match="immutable"):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(text("UPDATE axon.api_keys SET key_hash = :h WHERE key_prefix = :p"),
                                {"h": os.urandom(32), "p": prefix})

    async def test_last_owner_cannot_be_removed(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="at least one active owner"):
            async with db.tenant_session(ctx(world, "tenant_b", "owner_b")) as s:
                await s.execute(__import__("sqlalchemy").text(
                    "DELETE FROM axon.memberships WHERE user_id = :u"), {"u": world["owner_b"]})

    async def test_system_roles_are_read_only(self, db, world):
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            res = await s.execute(__import__("sqlalchemy").text(
                "UPDATE axon.roles SET name = 'pwned' WHERE key = 'viewer'"))
            assert res.rowcount == 0

    async def test_custom_role_cannot_carry_unheld_scope(self, db, world):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        admin = ctx(world, "tenant_a", "admin_a", ADMIN_SCOPES)
        with pytest.raises(DBAPIError, match="cannot grant scope"):
            async with db.tenant_session(admin) as s:
                rid = await _scalar(s, "INSERT INTO axon.roles (tenant_id, key, name) VALUES (:t, 'billing_bot', 'B') "
                                       "RETURNING id", t=world["tenant_a"])
                await s.execute(text("INSERT INTO axon.role_scopes VALUES (:r, 'billing:manage')"), {"r": rid})


@pg
class TestSecretsAndWebhooks:
    async def test_plaintext_credentials_rejected(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="check constraint"):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(__import__("sqlalchemy").text(
                    "INSERT INTO axon.integration_credentials (tenant_id, provider, ciphertext, key_id) "
                    "VALUES (:t, 'openai', 'sk-plaintext-key', 'k1')"), {"t": world["tenant_a"]})

    async def test_encrypted_credential_round_trip_and_swap_attack(self, db, world):
        from sqlalchemy import text
        cipher = TokenCipher.from_spec("k1:" + "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo")
        token_a = cipher.encrypt("xoxb-tenant-a", tenant_id=world["tenant_a"], purpose="integration:slack")
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            await s.execute(text(
                "INSERT INTO axon.integration_credentials (tenant_id, provider, account_label, ciphertext, key_id) "
                "VALUES (:t, 'slack', 'swap-test', :c, 'k1')"), {"t": world["tenant_a"], "c": token_a})
            stored = await _scalar(s, "SELECT ciphertext FROM axon.integration_credentials WHERE account_label='swap-test'")
        assert "xoxb" not in stored
        assert cipher.decrypt(stored, tenant_id=world["tenant_a"], purpose="integration:slack") == "xoxb-tenant-a"
        # Even if the ciphertext were copied into tenant B's row, B cannot open it.
        from app.core.config import TokenDecryptionError
        with pytest.raises(TokenDecryptionError):
            cipher.decrypt(stored, tenant_id=world["tenant_b"], purpose="integration:slack")

    async def test_webhook_replay_rejected(self, db, world):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        cipher = TokenCipher.from_spec("k1:" + "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo")
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            ep = await _scalar(s, "INSERT INTO axon.webhook_endpoints (tenant_id, name, secret_ciphertext) "
                                  "VALUES (:t, 'hook', :c) RETURNING id", t=world["tenant_a"],
                               c=cipher.encrypt("whsec", tenant_id=world["tenant_a"], purpose="webhook:secret"))
        receiver = ctx(world, "tenant_a", "viewer_a", set())
        insert = text("INSERT INTO axon.webhook_deliveries (endpoint_id, tenant_id, delivery_id) VALUES (:e, :t, :d)")
        params = {"e": ep, "t": world["tenant_a"], "d": "evt_0123456789"}
        async with db.tenant_session(receiver) as s:
            await s.execute(insert, params)
        with pytest.raises(IntegrityError):
            async with db.tenant_session(receiver) as s:
                await s.execute(insert, params)

    async def test_audit_log_is_append_only(self, db, world):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
            await s.execute(text("INSERT INTO axon.audit_events (tenant_id, action) VALUES (:t, 'member.invite')"),
                            {"t": world["tenant_a"]})
        with pytest.raises(DBAPIError):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(text("UPDATE axon.audit_events SET action = 'tampered'"))
        with pytest.raises(DBAPIError):
            async with db.tenant_session(ctx(world, "tenant_a", "owner_a")) as s:
                await s.execute(text("DELETE FROM axon.audit_events"))
        # Not even the schema owner may rewrite history.
        with pytest.raises(DBAPIError, match="append-only"):
            async with db.system_session("tamper attempt") as s:
                await s.execute(text("UPDATE axon.audit_events SET action = 'tampered'"))
