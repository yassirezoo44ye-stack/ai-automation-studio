"""
Real-PostgreSQL integration test harness — Testing Foundation P0 slice.

Every other test in this repo (tests/, tests/security/) mocks asyncpg
entirely — no test anywhere runs a query against a real Postgres instance.
This package is the deliberate exception: it provisions a real, ephemeral
database per test session, runs the app's own production schema-creation
functions against it (app.core.db.init_db, app.tenancy.init_tenancy_schema,
app.tenancy.enable_scoped_rls — the exact functions app.factory.lifespan()
calls, not a hand-maintained copy), and exercises TenancyService/RLS
end-to-end: request/auth context -> TenancyService -> real connection/
transaction -> real PostgreSQL Row Level Security -> result.

Design constraints (see docs/testing-foundation-p0.md for the full
rationale):

  - Skips cleanly, not failing, wherever a real Postgres isn't reachable
    (no Docker daemon, no local install, no CI service wired up yet) --
    the rest of the suite must stay green everywhere this package can't
    run. Set PG_INTEGRATION_ADMIN_DSN to point at one; otherwise this
    defaults to the same test/test convention app/.github/workflows/
    ci.yml's postgres:16 service already uses, at 127.0.0.1:5432.

  - The application-role connection used for schema creation and every
    test in this package is deliberately NOT the admin/superuser
    connection. Postgres superusers bypass Row Level Security
    unconditionally, with no override -- if schema setup or the tests
    themselves ran as a superuser, app/tenancy/rls.py's FORCE ROW LEVEL
    SECURITY would be silently meaningless and every "RLS blocks
    cross-tenant access" assertion in this package would pass for the
    wrong reason. A dedicated, ordinary (non-superuser) role is created
    for this purpose and becomes the owner of every table it creates --
    exactly the scenario app/tenancy/rls.py's own docstring describes
    ("the app's own DB role owns these tables... FORCE is required").

  - One real database per test SESSION (not per test) -- schema creation
    is the expensive part; individual tests share it and clean up their
    own rows. Session-scoped provisioning runs via a synchronous fixture
    using its own throwaway asyncio.run() calls, deliberately decoupled
    from pytest-asyncio's per-test event loop (this package's
    asyncpg.Pool objects are always created and closed within a single
    test's own event loop via function-scoped async fixtures below) --
    an asyncpg Pool is bound to the loop that created it, so a
    session-scoped Pool shared across function-scoped test loops would
    break.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

ADMIN_DSN = os.environ.get(
    "PG_INTEGRATION_ADMIN_DSN", "postgresql://test:test@127.0.0.1:5432/postgres",
)
APP_ROLE = "axon_pgtest_app"
APP_ROLE_PASSWORD = "axon_pgtest_app"


def _app_dsn(db_name: str) -> str:
    admin_host_part = ADMIN_DSN.split("@", 1)[-1].split("/", 1)[0]
    return f"postgresql://{APP_ROLE}:{APP_ROLE_PASSWORD}@{admin_host_part}/{db_name}"


async def _pg_reachable() -> bool:
    try:
        import asyncpg
        conn = await asyncpg.connect(ADMIN_DSN, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


def _pg_reachable_sync() -> bool:
    try:
        return asyncio.run(_pg_reachable())
    except Exception:
        return False


# Computed once at collection time — a few-hundred-ms, timeout-bounded probe.
PG_AVAILABLE = _pg_reachable_sync()

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE,
    reason=(
        "Real PostgreSQL not reachable at PG_INTEGRATION_ADMIN_DSN "
        f"({ADMIN_DSN.split('@')[-1]}) — tests/db_integration/ skipped. "
        "Set PG_INTEGRATION_ADMIN_DSN or run a local/CI postgres:16 instance "
        "to exercise these."
    ),
)


async def _ensure_app_role(admin_conn) -> None:
    exists = await admin_conn.fetchval(
        "SELECT 1 FROM pg_roles WHERE rolname=$1", APP_ROLE,
    )
    if not exists:
        # Deliberately NOT superuser — see module docstring. CREATEDB lets
        # it own the tables it creates in each ephemeral database.
        await admin_conn.execute(
            f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE_PASSWORD}' CREATEDB"
        )


@pytest.fixture(scope="session")
def pg_test_database_url() -> str:
    """Provisions one ephemeral database for the whole test session, owned
    by the non-superuser APP_ROLE, with the app's real schema (users,
    tenancy tables, RLS policies) already applied. Drops it on teardown."""
    if not PG_AVAILABLE:
        pytest.skip("real PostgreSQL not reachable")

    db_name = f"axon_pgtest_{uuid.uuid4().hex[:12]}"

    async def _setup() -> None:
        import asyncpg

        admin_conn = await asyncpg.connect(ADMIN_DSN)
        try:
            await _ensure_app_role(admin_conn)
            await admin_conn.execute(f'CREATE DATABASE "{db_name}" OWNER {APP_ROLE}')
        finally:
            await admin_conn.close()

        app_dsn = _app_dsn(db_name)
        pool = await asyncpg.create_pool(app_dsn, min_size=1, max_size=5)
        try:
            from app.core.db import init_db
            from app.tenancy import init_tenancy_schema, enable_scoped_rls

            async with pool.acquire() as conn:
                await init_db(conn)
            async with pool.acquire() as conn:
                await init_tenancy_schema(conn)
            async with pool.acquire() as conn:
                await enable_scoped_rls(conn)
        finally:
            await pool.close()

    asyncio.run(_setup())

    yield _app_dsn(db_name)

    async def _teardown() -> None:
        import asyncpg

        admin_conn = await asyncpg.connect(ADMIN_DSN)
        try:
            # Drop any lingering connections first, or DROP DATABASE fails.
            await admin_conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=$1 AND pid <> pg_backend_pid()",
                db_name,
            )
            await admin_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        finally:
            await admin_conn.close()

    asyncio.run(_teardown())


@pytest_asyncio.fixture
async def pg_pool(pg_test_database_url: str) -> AsyncIterator["asyncpg.Pool"]:  # noqa: F821
    """Function-scoped real asyncpg.Pool against the session's ephemeral
    database — created and closed within this one test's own event loop,
    so it never crosses a pytest-asyncio loop boundary.

    Also installs itself as app.core.db's module-level pool for the
    duration of the test (restoring whatever was there before on
    teardown). app.core.db.acquire_scoped() — the actual function
    TenancyService and every RLS-scoped query in the app calls — reads
    that global rather than taking a pool argument, matching how the real
    app wires a single process-wide pool. Exercising the real
    acquire_scoped() (not a reimplementation of it) requires this.

    Also resets app.tenancy.service's process-wide get_tenancy_service()
    singleton around the test. That singleton binds to whatever pool was
    active on its first call and never rebinds — without resetting it, a
    test in this package could silently pick up a stale TenancyService
    left over from a different test (or a mocked one from the rest of the
    suite, if ever run in the same process), rather than one bound to
    this test's real pool."""
    import asyncpg
    from app.core import db as db_module
    from app.tenancy import service as tenancy_service_module

    pool = await asyncpg.create_pool(pg_test_database_url, min_size=1, max_size=5)
    previous_pool = db_module._pool
    previous_tenancy_service = tenancy_service_module._service
    db_module.set_pool(pool)
    tenancy_service_module._service = None
    try:
        yield pool
    finally:
        tenancy_service_module._service = previous_tenancy_service
        db_module.set_pool(previous_pool)
        await pool.close()


@pytest_asyncio.fixture
async def two_orgs(pg_pool) -> dict:
    """Two real organizations, each with one real user as its 'owner'
    member — created through the real TenancyService (app/tenancy/
    service.py), not hand-inserted rows, so the fixture itself exercises
    the same INSERT path production traffic uses."""
    from app.tenancy.service import TenancyService

    svc = TenancyService(pg_pool)
    async with pg_pool.acquire() as conn:
        user_a = await conn.fetchval(
            "INSERT INTO users (email) VALUES ($1) RETURNING id",
            f"a-{uuid.uuid4().hex[:8]}@example.com",
        )
        user_b = await conn.fetchval(
            "INSERT INTO users (email) VALUES ($1) RETURNING id",
            f"b-{uuid.uuid4().hex[:8]}@example.com",
        )

    org_a = await svc.create_organization(name=f"Org A {uuid.uuid4().hex[:6]}", creator_id=str(user_a))
    org_b = await svc.create_organization(name=f"Org B {uuid.uuid4().hex[:6]}", creator_id=str(user_b))

    return {
        "svc": svc,
        "pool": pg_pool,
        "org_a": str(org_a["id"]),
        "org_b": str(org_b["id"]),
        "user_a": str(user_a),
        "user_b": str(user_b),
    }
