"""Real PostgreSQL BYOK isolation tests. Uses disposable CI database only."""
import asyncio
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio

from app.ai.credential_rls import RLS_SQL, scoped_credential_transaction
from app.ai.user_credentials import SCHEMA_SQL, get_key_for_execution, put_key, revoke_key

DSN = os.environ.get("BYOK_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="Disposable PostgreSQL DSN required")


@pytest_asyncio.fixture
async def db_pool(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("BYOK_FERNET_KEY", Fernet.generate_key().decode())
    admin = await asyncpg.connect(DSN)
    schema = "byok_test_" + uuid.uuid4().hex[:16]
    # CI uses disposable Postgres; app role is non-owner, non-superuser.
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO byok_app')
    await admin.execute(f'SET search_path TO "{schema}"')
    await admin.execute(SCHEMA_SQL)
    await admin.execute(RLS_SQL)
    await admin.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".ai_user_credentials TO byok_app')
    pool = await asyncpg.create_pool(
        dsn=os.environ["BYOK_TEST_APP_DATABASE_URL"],
        min_size=1, max_size=2,
        server_settings={"search_path": schema},
    )
    try:
        yield pool
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


@pytest.mark.asyncio
async def test_real_rls_scope_and_reused_connection(db_pool):
    org_a, org_b, user_a, user_b = [str(uuid.uuid4()) for _ in range(4)]
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user") is False
        assert await conn.fetchval("SELECT count(*) FROM ai_user_credentials") == 0
        # A rejected statement aborts its transaction. Catch outside the
        # transaction manager so rollback happens before the next query.
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            async with scoped_credential_transaction(conn, org_id=org_a, user_id=user_a):
                await put_key(conn, org_id=org_a, user_id=user_a, provider="openai", api_key="A-secret")
                assert await get_key_for_execution(conn, org_id=org_a, user_id=user_a, provider="openai") == "A-secret"
                await put_key(conn, org_id=org_b, user_id=user_b, provider="openai", api_key="wrong")
        assert await conn.fetchval("SELECT count(*) FROM ai_user_credentials") == 0
        async with scoped_credential_transaction(conn, org_id=org_a, user_id=user_a):
            await put_key(conn, org_id=org_a, user_id=user_a, provider="openai", api_key="A-secret")
        assert await conn.fetchval("SELECT count(*) FROM ai_user_credentials") == 0
        async with scoped_credential_transaction(conn, org_id=org_a, user_id=user_b):
            assert await get_key_for_execution(conn, org_id=org_a, user_id=user_a, provider="openai") is None
            assert not await revoke_key(conn, org_id=org_a, user_id=user_a, provider="openai")
        async with scoped_credential_transaction(conn, org_id=org_b, user_id=user_a):
            assert await get_key_for_execution(conn, org_id=org_a, user_id=user_a, provider="openai") is None
        async with scoped_credential_transaction(conn, org_id=org_a, user_id=user_a):
            assert await get_key_for_execution(conn, org_id=org_a, user_id=user_a, provider="openai") == "A-secret"


@pytest.mark.asyncio
async def test_real_rls_concurrent_tenants(db_pool):
    ids = [(str(uuid.uuid4()), str(uuid.uuid4())) for _ in range(2)]
    async def worker(org, user, value):
        async with db_pool.acquire() as conn:
            async with scoped_credential_transaction(conn, org_id=org, user_id=user):
                await put_key(conn, org_id=org, user_id=user, provider="openai", api_key=value)
                await asyncio.sleep(0.02)
                assert await get_key_for_execution(conn, org_id=org, user_id=user, provider="openai") == value
    await asyncio.gather(*(worker(*pair, f"secret-{i}") for i, pair in enumerate(ids)))
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM ai_user_credentials") == 0
        async with scoped_credential_transaction(conn, org_id=ids[0][0], user_id=ids[0][1]):
            assert await get_key_for_execution(conn, org_id=ids[1][0], user_id=ids[1][1], provider="openai") is None


@pytest.mark.asyncio
async def test_real_rls_blocks_unscoped_insert_and_update(db_pool):
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    async with db_pool.acquire() as conn:
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await put_key(conn, org_id=org, user_id=user, provider="openai", api_key="unscoped")
        async with scoped_credential_transaction(conn, org_id=org, user_id=user):
            await put_key(conn, org_id=org, user_id=user, provider="openai", api_key="original")
        # A separate transaction without identity cannot see or mutate the row.
        assert await conn.fetchval("SELECT count(*) FROM ai_user_credentials") == 0
        assert await conn.execute("UPDATE ai_user_credentials SET encrypted_key='tampered'") == "UPDATE 0"
        async with scoped_credential_transaction(conn, org_id=org, user_id=user):
            assert await get_key_for_execution(conn, org_id=org, user_id=user, provider="openai") == "original"


@pytest.mark.asyncio
async def test_real_rls_pool_reuse_does_not_leak_scope(db_pool):
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    async with db_pool.acquire() as conn:
        async with scoped_credential_transaction(conn, org_id=org, user_id=user):
            await put_key(conn, org_id=org, user_id=user, provider="openai", api_key="private")
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM ai_user_credentials") == 0
        assert await get_key_for_execution(conn, org_id=org, user_id=user, provider="openai") is None
        async with scoped_credential_transaction(conn, org_id=org, user_id=user):
            assert await get_key_for_execution(conn, org_id=org, user_id=user, provider="openai") == "private"

@pytest.mark.asyncio
async def test_real_postgres_staged_key_rotation(db_pool, monkeypatch):
    """Verify previous-key reads and new-key writes against real RLS rows."""
    from cryptography.fernet import Fernet, InvalidToken
    old, new = Fernet.generate_key(), Fernet.generate_key()
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    monkeypatch.setenv("BYOK_FERNET_KEY", old.decode("ascii"))
    monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
    async with db_pool.acquire() as conn:
        async with scoped_credential_transaction(conn, org_id=org, user_id=user):
            await put_key(conn, org_id=org, user_id=user, provider="openai", api_key="old-secret")
            old_ciphertext = await conn.fetchval(
                "SELECT encrypted_key FROM ai_user_credentials WHERE provider='openai'"
            )
        monkeypatch.setenv("BYOK_FERNET_KEY", new.decode("ascii"))
        monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", old.decode("ascii"))
        async with scoped_credential_transaction(conn, org_id=org, user_id=user):
            assert await get_key_for_execution(conn, org_id=org, user_id=user, provider="openai") == "old-secret"
            await put_key(conn, org_id=org, user_id=user, provider="openai", api_key="new-secret")
            new_ciphertext = await conn.fetchval(
                "SELECT encrypted_key FROM ai_user_credentials WHERE provider='openai'"
            )
        assert Fernet(old).decrypt(old_ciphertext.encode()) == b"old-secret"
        assert Fernet(new).decrypt(new_ciphertext.encode()) == b"new-secret"
        with pytest.raises(InvalidToken):
            Fernet(old).decrypt(new_ciphertext.encode())
        monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
        async with scoped_credential_transaction(conn, org_id=org, user_id=user):
            assert await get_key_for_execution(conn, org_id=org, user_id=user, provider="openai") == "new-secret"

@pytest.mark.asyncio
async def test_real_postgres_reencrypt_user_credentials_with_rls(db_pool, monkeypatch):
    """Migration changes only scoped rows; old key can then be retired."""
    from cryptography.fernet import Fernet, InvalidToken
    from app.ai.credential_rotation import rotate_user_credentials
    old, new = Fernet.generate_key(), Fernet.generate_key()
    org, user_a, user_b = [str(uuid.uuid4()) for _ in range(3)]
    monkeypatch.setenv("BYOK_FERNET_KEY", old.decode())
    monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
    async with db_pool.acquire() as conn:
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_a):
            await put_key(conn, org_id=org, user_id=user_a, provider="openai", api_key="user-a")
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_b):
            await put_key(conn, org_id=org, user_id=user_b, provider="openai", api_key="user-b")
        monkeypatch.setenv("BYOK_FERNET_KEY", new.decode())
        monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", old.decode())
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_a):
            assert await rotate_user_credentials(conn, org_id=org, user_id=user_a) == {"scanned": 1, "rotated": 1}
            assert await get_key_for_execution(conn, org_id=org, user_id=user_a, provider="openai") == "user-a"
        monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_a):
            assert await get_key_for_execution(conn, org_id=org, user_id=user_a, provider="openai") == "user-a"
        with pytest.raises(InvalidToken):
            async with scoped_credential_transaction(conn, org_id=org, user_id=user_b):
                await get_key_for_execution(conn, org_id=org, user_id=user_b, provider="openai")

@pytest.mark.asyncio
async def test_real_postgres_primary_key_coverage_is_tenant_scoped(db_pool, monkeypatch):
    """Verification counts only current tenant's ciphertext without exposing it."""
    from cryptography.fernet import Fernet
    from app.ai.credential_verification import verify_user_primary_key
    old, new = Fernet.generate_key(), Fernet.generate_key()
    org, user_a, user_b = [str(uuid.uuid4()) for _ in range(3)]
    monkeypatch.setenv("BYOK_FERNET_KEY", old.decode())
    monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
    async with db_pool.acquire() as conn:
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_a):
            await put_key(conn, org_id=org, user_id=user_a, provider="openai", api_key="a")
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_b):
            await put_key(conn, org_id=org, user_id=user_b, provider="openai", api_key="b")
        monkeypatch.setenv("BYOK_FERNET_KEY", new.decode())
        monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", old.decode())
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_a):
            assert await verify_user_primary_key(conn, org_id=org, user_id=user_a) == {
                "scanned": 1, "not_primary": 1, "unreadable": 0, "complete": False
            }
            await put_key(conn, org_id=org, user_id=user_a, provider="openai", api_key="a-new")
            assert await verify_user_primary_key(conn, org_id=org, user_id=user_a) == {
                "scanned": 1, "not_primary": 0, "unreadable": 0, "complete": True
            }
        async with scoped_credential_transaction(conn, org_id=org, user_id=user_b):
            assert await verify_user_primary_key(conn, org_id=org, user_id=user_b) == {
                "scanned": 1, "not_primary": 1, "unreadable": 0, "complete": False
            }
