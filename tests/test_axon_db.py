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
    "organization:read", "organization:manage", "members:read", "members:manage", "roles:manage",
    "api_keys:manage", "integrations:read", "integrations:manage", "webhooks:manage",
    "workflows:read", "workflows:write", "workflows:execute", "agents:read", "agents:write",
    "agents:execute", "costs:read", "billing:manage", "audit:read",
})
MANAGER_SCOPES = ALL_SCOPES - {"organization:manage", "billing:manage", "roles:manage"}
MEMBER_SCOPES = frozenset({
    "organization:read", "members:read", "integrations:read", "workflows:read", "workflows:write",
    "workflows:execute", "agents:read", "agents:write", "agents:execute",
})
TEST_KEY = "k1:Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo"
PW_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub+b+dWRWJTmaaJObG"


def sql(statement: str):
    from sqlalchemy import text
    return text(statement)


async def _scalar(session, statement, **params):
    return (await session.execute(sql(statement), params)).scalar()


async def _rows(session, statement, **params):
    return (await session.execute(sql(statement), params)).all()


def hexkey() -> str:
    return os.urandom(32).hex()


def prefix() -> str:
    return "axk_" + uuid.uuid4().hex[:12]


@pytest.fixture
async def world(db):
    """Org A (admin, manager, member) and org B (admin), all created through the signup function."""
    tag = uuid.uuid4().hex[:8]
    ids: dict[str, object] = {"slug_a": f"a-{tag}", "slug_b": f"b-{tag}"}
    async with db.system_session("test fixture") as s:
        for org, slug in (("a", ids["slug_a"]), ("b", ids["slug_b"])):
            row = (await s.execute(sql(
                "SELECT * FROM axon.provision_organization(:s, :n, :e, :p, 'Admin')"),
                {"s": slug, "n": f"Org {org.upper()}", "e": f"admin@{org}.test", "p": PW_HASH})).one()
            ids[f"org_{org}"], ids[f"admin_{org}"] = row.organization_id, row.user_id
        for who in ("manager", "member"):
            ids[f"{who}_a"] = await _scalar(
                s, "INSERT INTO axon.users (organization_id, email, hashed_password, role) "
                   "VALUES (:o, :e, :p, :r) RETURNING id",
                o=ids["org_a"], e=f"{who}@a.test", p=PW_HASH, r=who)
    return ids


def ctx(world, org: str, user: str, scopes=ALL_SCOPES) -> TenantContext:
    return TenantContext(world[f"org_{org}"], world[user], frozenset(scopes))


@pg
class TestTenantIsolation:
    async def test_session_sees_only_its_organization(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            orgs = {r[0] for r in await _rows(s, "SELECT id FROM axon.organizations")}
            users = {r[0] for r in await _rows(s, "SELECT organization_id FROM axon.users")}
            assert orgs == {world["org_a"]}
            assert users == {world["org_a"]}
            assert current_tenant().tenant_id == world["org_a"]
        assert current_tenant() is None
        async with db.tenant_session(ctx(world, "b", "admin_b")) as s:
            assert {r[0] for r in await _rows(s, "SELECT id FROM axon.organizations")} == {world["org_b"]}
            assert await _scalar(s, "SELECT count(*) FROM axon.users") == 1

    async def test_runtime_role_is_applied(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            assert await _scalar(s, "SELECT current_user") == "axon_app"
            assert await _scalar(s, "SELECT axon.current_tenant_id()") == world["org_a"]

    async def test_same_email_allowed_in_two_organizations(self, db, world):
        async with db.tenant_session(ctx(world, "b", "admin_b")) as s:
            await s.execute(sql("INSERT INTO axon.users (organization_id, email, hashed_password) "
                                "VALUES (:o, 'member@a.test', :p)"), {"o": world["org_b"], "p": PW_HASH})

    async def test_session_without_tenant_refuses_to_run(self, db, world):
        session = db.session_factory()
        try:
            with pytest.raises(TenantContextError):
                await session.execute(sql("SELECT 1"))
        finally:
            await session.close()

    async def test_axon_app_without_tenant_sees_nothing(self, db, world):
        """Fail closed at the database layer, not only in Python."""
        async with db.engine.connect() as conn:
            await conn.execute(sql("SET LOCAL ROLE axon_app"))
            for table in ("organizations", "users", "api_keys", "ai_cost_metrics", "integration_credentials",
                          "webhook_endpoints", "refresh_tokens", "audit_events", "roles"):
                assert (await conn.execute(sql(f"SELECT count(*) FROM axon.{table}"))).scalar() == 0, table
            await conn.rollback()

    async def test_cannot_write_into_another_organization(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="row-level security"):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql("INSERT INTO axon.ai_cost_metrics (organization_id, model_name, provider) "
                                    "VALUES (:o, 'claude-opus-5-5', 'anthropic')"), {"o": world["org_b"]})

    async def test_users_cannot_move_between_organizations(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql("UPDATE axon.users SET organization_id = :b WHERE id = :u"),
                                {"b": world["org_b"], "u": world["member_a"]})

    async def test_context_survives_mid_session_commit(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.organizations") == 1
            await s.commit()  # GUCs are transaction-local; after_begin must re-apply them
            assert await _scalar(s, "SELECT axon.current_tenant_id()") == world["org_a"]
            assert await _scalar(s, "SELECT current_user") == "axon_app"

    async def test_no_leak_to_next_pooled_checkout(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            pid = await _scalar(s, "SELECT pg_backend_pid()")
        async with db.engine.connect() as conn:
            assert (await conn.execute(sql("SELECT pg_backend_pid()"))).scalar() == pid  # same connection
            assert (await conn.execute(sql("SELECT axon.current_tenant_id()"))).scalar() is None
            assert (await conn.execute(sql("SELECT current_user"))).scalar() != "axon_app"
            assert (await conn.execute(sql("SELECT axon.current_scopes()"))).scalar() == []

    async def test_error_rolls_back_and_releases_context(self, db, world):
        with pytest.raises(RuntimeError):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql("UPDATE axon.organizations SET name = 'renamed'"))
                raise RuntimeError("boom")
        assert current_tenant() is None
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            assert await _scalar(s, "SELECT name FROM axon.organizations") == "Org A"

    async def test_system_session_rejected_inside_tenant_session(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")):
            with pytest.raises(TenantContextError):
                async with db.system_session("nested"):
                    pass

    async def test_system_session_requires_reason(self, db):
        with pytest.raises(ValueError):
            async with db.system_session(" "):
                pass

    async def test_concurrent_sessions_keep_their_own_organization(self, pg_url, world):
        cfg = settings.model_copy(update={"db_pool_size": 4, "db_max_overflow": 0})
        database = Database(cfg, url=pg_url)
        try:
            async def probe(org, user):
                async with database.tenant_session(ctx(world, org, user)) as s:
                    await asyncio.sleep(0.01)
                    return await _scalar(s, "SELECT id FROM axon.organizations"), current_tenant().tenant_id

            results = await asyncio.gather(*(
                probe(*(("a", "admin_a") if i % 2 else ("b", "admin_b"))) for i in range(12)))
            for seen, bound in results:
                assert seen == bound
        finally:
            await database.dispose()

    async def test_get_db_session_dependency_is_scoped(self, db, world):
        from app.core import db as dbmod
        app = FastAPI()
        context = ctx(world, "b", "admin_b")

        @app.middleware("http")
        async def fake_auth(request: Request, call_next):
            if request.headers.get("x-test-auth") == "yes":
                setattr(request.state, REQUEST_TENANT_ATTR, context)
            return await call_next(request)

        @app.get("/orgs")
        async def orgs(session=Depends(dbmod.get_db_session)):  # noqa: B008
            return [str(r[0]) for r in await _rows(session, "SELECT id FROM axon.organizations")]

        previous = dbmod._database
        dbmod.set_database(db)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                ok = await c.get("/orgs", headers={"x-test-auth": "yes"})
                anon = await c.get("/orgs")
        finally:
            dbmod.set_database(previous)
        assert ok.status_code == 200 and ok.json() == [str(world["org_b"])]
        assert anon.status_code == 401


@pg
class TestRolesAndScopes:
    async def test_roles_come_from_database(self, db, world):
        async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
            assert set(await _scalar(s, "SELECT axon.role_scope_list(:o, 'admin')", o=world["org_a"])) == ALL_SCOPES
            assert set(await _scalar(s, "SELECT axon.role_scope_list(:o, 'manager')", o=world["org_a"])) == MANAGER_SCOPES
            assert set(await _scalar(s, "SELECT axon.role_scope_list(:o, 'member')", o=world["org_a"])) == MEMBER_SCOPES

    async def test_unknown_role_rejected(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="unknown role"):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql("INSERT INTO axon.users (organization_id, email, hashed_password, role) "
                                    "VALUES (:o, 'x@a.test', :p, 'superuser')"), {"o": world["org_a"], "p": PW_HASH})

    async def test_manager_cannot_promote_to_admin(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="cannot grant scope"):
            async with db.tenant_session(ctx(world, "a", "manager_a", MANAGER_SCOPES)) as s:
                await s.execute(sql("UPDATE axon.users SET role = 'admin' WHERE id = :u"), {"u": world["member_a"]})

    async def test_member_cannot_promote_self(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="cannot grant scope"):
            async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
                await s.execute(sql("UPDATE axon.users SET role = 'manager' WHERE id = :u"), {"u": world["member_a"]})

    async def test_member_can_update_own_profile_only(self, db, world):
        async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
            own = await s.execute(sql("UPDATE axon.users SET full_name = 'Me', last_login_at = now() WHERE id = :u"),
                                  {"u": world["member_a"]})
            other = await s.execute(sql("UPDATE axon.users SET full_name = 'Hacked' WHERE id = :u"),
                                    {"u": world["admin_a"]})
            assert own.rowcount == 1
            assert other.rowcount == 0  # RLS hides the row from UPDATE

    async def test_last_admin_cannot_be_removed(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="at least one active admin"):
            async with db.tenant_session(ctx(world, "b", "admin_b")) as s:
                await s.execute(sql("UPDATE axon.users SET is_active = false WHERE id = :u"), {"u": world["admin_b"]})
        with pytest.raises(DBAPIError, match="at least one active admin"):
            async with db.tenant_session(ctx(world, "b", "admin_b")) as s:
                await s.execute(sql("DELETE FROM axon.users WHERE id = :u"), {"u": world["admin_b"]})

    async def test_system_roles_are_read_only(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            res = await s.execute(sql("UPDATE axon.roles SET name = 'pwned' WHERE key = 'member'"))
            assert res.rowcount == 0

    async def test_custom_role_cannot_carry_unheld_scope(self, db, world):
        from sqlalchemy.exc import DBAPIError
        holder = ctx(world, "a", "manager_a", MANAGER_SCOPES | {"roles:manage"})
        with pytest.raises(DBAPIError, match="cannot grant scope"):
            async with db.tenant_session(holder) as s:
                rid = await _scalar(s, "INSERT INTO axon.roles (organization_id, key, name) "
                                       "VALUES (:o, 'billing_bot', 'B') RETURNING id", o=world["org_a"])
                await s.execute(sql("INSERT INTO axon.role_scopes VALUES (:r, 'billing:manage')"), {"r": rid})

    async def test_find_login_user_needs_org_slug(self, db, world):
        async with db.system_session("login lookup") as s:
            row = (await s.execute(sql("SELECT * FROM axon.find_login_user(:s, ' ADMIN@a.test ')"),
                                   {"s": world["slug_a"]})).one()
            other = (await s.execute(sql("SELECT * FROM axon.find_login_user(:s, 'admin@a.test')"),
                                     {"s": world["slug_b"]})).all()
        assert row.user_id == world["admin_a"] and row.role == "admin" and row.is_active
        assert set(row.scopes) == ALL_SCOPES
        assert other == []


@pg
class TestApiKeys:
    INSERT = ("INSERT INTO axon.api_keys (organization_id, user_id, name, key_prefix, hashed_key, scopes) "
              "VALUES (:o, :u, 'ci', :p, :h, :s) RETURNING id")

    async def test_key_cannot_exceed_creator_scopes(self, db, world):
        from sqlalchemy.exc import DBAPIError
        creator = ctx(world, "a", "manager_a", {"api_keys:manage", "workflows:read"})
        base = {"o": world["org_a"], "u": world["manager_a"]}
        async with db.tenant_session(creator) as s:
            await s.execute(sql(self.INSERT), {**base, "p": prefix(), "h": hexkey(), "s": ["workflows:read"]})
        with pytest.raises(DBAPIError, match="cannot grant scope"):
            async with db.tenant_session(creator) as s:
                await s.execute(sql(self.INSERT), {**base, "p": prefix(), "h": hexkey(), "s": ["billing:manage"]})
        with pytest.raises(DBAPIError, match="unknown scope"):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql(self.INSERT), {**base, "p": prefix(), "h": hexkey(), "s": ["root:everything"]})

    async def test_key_owner_must_belong_to_organization(self, db, world):
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql(self.INSERT), {"o": world["org_a"], "u": world["admin_b"], "p": prefix(),
                                                   "h": hexkey(), "s": ["workflows:read"]})

    async def test_default_scope_and_format_checks(self, db, world):
        from sqlalchemy.exc import DBAPIError
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            scopes = await _scalar(
                s, "INSERT INTO axon.api_keys (organization_id, user_id, name, key_prefix, hashed_key) "
                   "VALUES (:o, :u, 'd', :p, :h) RETURNING scopes",
                o=world["org_a"], u=world["admin_a"], p=prefix(), h=hexkey())
            assert scopes == ["workflows:read"]
        with pytest.raises(DBAPIError, match="check constraint"):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql(self.INSERT), {"o": world["org_a"], "u": world["admin_a"], "p": prefix(),
                                                   "h": "plaintext-secret-key", "s": []})

    async def test_lookup_and_touch(self, db, world):
        digest = hexkey()
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            key_id = await _scalar(s, self.INSERT, o=world["org_a"], u=world["member_a"], p=prefix(), h=digest,
                                   s=["workflows:execute"])
        async with db.system_session("api key auth") as s:
            row = (await s.execute(sql("SELECT * FROM axon.lookup_api_key(:h)"), {"h": digest})).one()
        assert (row.api_key_id, row.organization_id, row.user_id) == (key_id, world["org_a"], world["member_a"])
        # The key itself has no api_keys:manage, yet usage is recorded.
        principal = TenantContext(world["org_a"], world["member_a"], frozenset(row.scopes), key_id)
        async with db.tenant_session(principal) as s:
            await s.execute(sql("SELECT axon.touch_api_key(:k)"), {"k": key_id})
            await s.execute(sql("SELECT axon.touch_api_key(:k)"), {"k": key_id})
            assert await _scalar(s, "SELECT axon.current_tenant_id()") == world["org_a"]
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            assert await _scalar(s, "SELECT last_used_at IS NOT NULL FROM axon.api_keys WHERE id = :k", k=key_id)

    async def test_touch_ignores_keys_of_other_organizations(self, db, world):
        digest = hexkey()
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            key_id = await _scalar(s, self.INSERT, o=world["org_a"], u=world["admin_a"], p=prefix(), h=digest,
                                   s=["workflows:read"])
        async with db.tenant_session(ctx(world, "b", "admin_b")) as s:
            await s.execute(sql("SELECT axon.touch_api_key(:k)"), {"k": key_id})
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            assert await _scalar(s, "SELECT last_used_at FROM axon.api_keys WHERE id = :k", k=key_id) is None

    async def test_revoked_or_expired_keys_not_found(self, db, world):
        revoked, expired = hexkey(), hexkey()
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            for digest, extra in ((revoked, "is_active = false"), (expired, "expires_at = now() - interval '1 s'")):
                kid = await _scalar(s, self.INSERT, o=world["org_a"], u=world["admin_a"], p=prefix(), h=digest,
                                    s=["workflows:read"])
                await s.execute(sql(f"UPDATE axon.api_keys SET {extra} WHERE id = :k"), {"k": kid})
        async with db.system_session("api key auth") as s:
            for digest in (revoked, expired):
                assert (await s.execute(sql("SELECT * FROM axon.lookup_api_key(:h)"), {"h": digest})).all() == []

    async def test_key_material_is_immutable(self, db, world):
        from sqlalchemy.exc import DBAPIError
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            kid = await _scalar(s, self.INSERT, o=world["org_a"], u=world["admin_a"], p=prefix(), h=hexkey(),
                                s=["workflows:read"])
        with pytest.raises(DBAPIError):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql("UPDATE axon.api_keys SET hashed_key = :h WHERE id = :k"), {"h": hexkey(), "k": kid})


@pg
class TestCostMetrics:
    async def test_record_and_read(self, db, world):
        async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
            await s.execute(sql(
                "INSERT INTO axon.ai_cost_metrics (organization_id, user_id, model_name, provider, "
                "prompt_tokens, completion_tokens, estimated_cost_usd) "
                "VALUES (:o, :u, 'claude-sonnet-5-5', 'anthropic', 1200, 300, 0.012345)"),
                {"o": world["org_a"], "u": world["member_a"]})
            # Members record usage but cannot read the organization's spend.
            assert await _scalar(s, "SELECT count(*) FROM axon.ai_cost_metrics") == 0
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            total = await _scalar(s, "SELECT sum(estimated_cost_usd) FROM axon.ai_cost_metrics")
            assert str(total) == "0.012345"
        async with db.tenant_session(ctx(world, "b", "admin_b")) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.ai_cost_metrics") == 0

    async def test_negative_values_rejected(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="check constraint"):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql("INSERT INTO axon.ai_cost_metrics (organization_id, model_name, provider, "
                                    "prompt_tokens) VALUES (:o, 'm', 'openai', -5)"), {"o": world["org_a"]})

    async def test_metrics_are_append_only(self, db, world):
        from sqlalchemy.exc import DBAPIError
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            await s.execute(sql("INSERT INTO axon.ai_cost_metrics (organization_id, model_name, provider) "
                                "VALUES (:o, 'm', 'openai')"), {"o": world["org_a"]})
        with pytest.raises(DBAPIError, match="append-only"):
            async with db.system_session("tamper attempt") as s:
                await s.execute(sql("UPDATE axon.ai_cost_metrics SET estimated_cost_usd = 0"))


@pg
class TestRefreshTokens:
    INSERT = ("INSERT INTO axon.refresh_tokens (organization_id, user_id, family_id, token_hash, expires_at) "
              "VALUES (:o, :u, :f, :h, now() + interval '7 days') RETURNING id")

    async def test_rotation_flow(self, db, world):
        family, first, second = uuid.uuid4(), hexkey(), hexkey()
        me = ctx(world, "a", "member_a", MEMBER_SCOPES)
        async with db.tenant_session(me) as s:
            await s.execute(sql(self.INSERT), {"o": world["org_a"], "u": world["member_a"], "f": family, "h": first})
        async with db.system_session("refresh lookup") as s:
            found = (await s.execute(sql("SELECT * FROM axon.find_refresh_token(:h)"), {"h": first})).one()
        assert found.user_id == world["member_a"] and found.used_at is None and found.user_is_active
        async with db.tenant_session(me) as s:
            await s.execute(sql("UPDATE axon.refresh_tokens SET used_at = now() WHERE id = :t"), {"t": found.token_id})
            await s.execute(sql(self.INSERT), {"o": world["org_a"], "u": world["member_a"], "f": family, "h": second})
            # Reuse detected → revoke the whole family.
            revoked = await s.execute(sql(
                "UPDATE axon.refresh_tokens SET revoked_at = now(), revoked_reason = 'reuse_detected' "
                "WHERE family_id = :f"), {"f": family})
            assert revoked.rowcount == 2

    async def test_cannot_issue_tokens_for_someone_else(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="row-level security"):
            async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
                await s.execute(sql(self.INSERT), {"o": world["org_a"], "u": world["admin_a"], "f": uuid.uuid4(),
                                                   "h": hexkey()})

    async def test_other_users_tokens_invisible_without_members_manage(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            await s.execute(sql(self.INSERT), {"o": world["org_a"], "u": world["admin_a"], "f": uuid.uuid4(),
                                               "h": hexkey()})
        async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.refresh_tokens WHERE user_id = :u",
                                 u=world["admin_a"]) == 0

    async def test_token_hash_must_be_digest(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="check constraint"):
            async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
                await s.execute(sql(self.INSERT), {"o": world["org_a"], "u": world["member_a"], "f": uuid.uuid4(),
                                                   "h": "raw-refresh-token-value"})


@pg
class TestSecretsAndWebhooks:
    async def test_plaintext_credentials_rejected(self, db, world):
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError, match="check constraint"):
            async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                await s.execute(sql("INSERT INTO axon.integration_credentials (organization_id, provider, "
                                    "ciphertext, key_id) VALUES (:o, 'openai', 'sk-plaintext-key', 'k1')"),
                                {"o": world["org_a"]})

    async def test_credentials_need_integrations_read(self, db, world):
        cipher = TokenCipher.from_spec(TEST_KEY)
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            await s.execute(sql("INSERT INTO axon.integration_credentials (organization_id, provider, ciphertext, "
                                "key_id) VALUES (:o, 'github', :c, 'k1')"),
                            {"o": world["org_a"],
                             "c": cipher.encrypt("gh", tenant_id=world["org_a"], purpose="integration:github")})
        async with db.tenant_session(ctx(world, "a", "member_a", {"workflows:read"})) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.integration_credentials") == 0
        async with db.tenant_session(ctx(world, "a", "member_a", MEMBER_SCOPES)) as s:
            assert await _scalar(s, "SELECT count(*) FROM axon.integration_credentials") == 1

    async def test_encrypted_credential_round_trip_and_swap_attack(self, db, world):
        from app.core.config import TokenDecryptionError
        cipher = TokenCipher.from_spec(TEST_KEY)
        token = cipher.encrypt("xoxb-org-a", tenant_id=world["org_a"], purpose="integration:slack")
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            await s.execute(sql("INSERT INTO axon.integration_credentials (organization_id, provider, ciphertext, "
                                "key_id) VALUES (:o, 'slack', :c, 'k1')"), {"o": world["org_a"], "c": token})
            stored = await _scalar(s, "SELECT ciphertext FROM axon.integration_credentials WHERE provider = 'slack'")
        assert "xoxb" not in stored
        assert cipher.decrypt(stored, tenant_id=world["org_a"], purpose="integration:slack") == "xoxb-org-a"
        with pytest.raises(TokenDecryptionError):
            cipher.decrypt(stored, tenant_id=world["org_b"], purpose="integration:slack")

    async def test_webhook_lookup_and_replay_rejected(self, db, world):
        from sqlalchemy.exc import IntegrityError
        cipher = TokenCipher.from_spec(TEST_KEY)
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            ep = await _scalar(s, "INSERT INTO axon.webhook_endpoints (organization_id, name, secret_ciphertext) "
                                  "VALUES (:o, 'hook', :c) RETURNING id", o=world["org_a"],
                               c=cipher.encrypt("whsec", tenant_id=world["org_a"], purpose="webhook:secret"))
        async with db.system_session("webhook receiver") as s:
            found = (await s.execute(sql("SELECT * FROM axon.lookup_webhook_endpoint(:e)"), {"e": ep})).one()
        assert found.organization_id == world["org_a"]
        assert cipher.decrypt(found.secret_ciphertext, tenant_id=world["org_a"], purpose="webhook:secret") == "whsec"
        receiver = TenantContext(found.organization_id)
        insert = sql("INSERT INTO axon.webhook_deliveries (endpoint_id, organization_id, delivery_id) "
                     "VALUES (:e, :o, :d)")
        params = {"e": ep, "o": world["org_a"], "d": "evt_0123456789"}
        async with db.tenant_session(receiver) as s:
            await s.execute(insert, params)
        with pytest.raises(IntegrityError):
            async with db.tenant_session(receiver) as s:
                await s.execute(insert, params)

    async def test_audit_log_is_append_only(self, db, world):
        from sqlalchemy.exc import DBAPIError
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            await s.execute(sql("INSERT INTO axon.audit_events (organization_id, action) VALUES (:o, 'member.invite')"),
                            {"o": world["org_a"]})
        for statement in ("UPDATE axon.audit_events SET action = 'tampered'", "DELETE FROM axon.audit_events"):
            with pytest.raises(DBAPIError):
                async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
                    await s.execute(sql(statement))
        with pytest.raises(DBAPIError, match="append-only"):
            async with db.system_session("tamper attempt") as s:
                await s.execute(sql("UPDATE axon.audit_events SET action = 'tampered'"))

    async def test_deleting_organization_cascades_everything(self, db, world):
        async with db.tenant_session(ctx(world, "a", "admin_a")) as s:
            await s.execute(sql("INSERT INTO axon.audit_events (organization_id, action) VALUES (:o, 'x.y.z')"),
                            {"o": world["org_a"]})
            await s.execute(sql("INSERT INTO axon.ai_cost_metrics (organization_id, model_name, provider) "
                                "VALUES (:o, 'm', 'openai')"), {"o": world["org_a"]})
        async with db.system_session("offboarding") as s:
            await s.execute(sql("DELETE FROM axon.organizations WHERE id = :o"), {"o": world["org_a"]})
            for table in ("users", "audit_events", "ai_cost_metrics"):
                assert await _scalar(s, f"SELECT count(*) FROM axon.{table} WHERE organization_id = :o",
                                     o=world["org_a"]) == 0
