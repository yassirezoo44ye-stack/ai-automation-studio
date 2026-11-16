"""RLS policy and transaction scope tests (not a PostgreSQL integration test)."""
import uuid

import pytest

from app.ai.credential_rls import RLS_SQL, scoped_credential_transaction


def test_policy_is_fail_closed_for_missing_context():
    assert "FORCE ROW LEVEL SECURITY" in RLS_SQL
    assert "app.byok_org_id" in RLS_SQL
    assert "app.byok_user_id" in RLS_SQL
    assert " IS NULL OR " not in RLS_SQL
    assert "WITH CHECK" in RLS_SQL


@pytest.mark.asyncio
async def test_transaction_local_scope():
    calls = []
    class Tx:
        async def __aenter__(self):
            calls.append("begin")
        async def __aexit__(self, *args):
            calls.append("end")
    class Conn:
        def transaction(self):
            return Tx()
        async def execute(self, query, *args):
            calls.append((query, args))
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    async with scoped_credential_transaction(Conn(), org_id=org, user_id=user):
        assert calls[0] == "begin"
    assert calls[-1] == "end"
    assert calls[1][1] == (org,) and calls[2][1] == (user,)
    assert all("true)" in entry[0] for entry in calls[1:3])


@pytest.mark.asyncio
async def test_invalid_identity_rejected_before_db_transaction():
    class Conn:
        def transaction(self):
            raise AssertionError("DB must not be touched")
    with pytest.raises(ValueError):
        async with scoped_credential_transaction(Conn(), org_id="bad", user_id=str(uuid.uuid4())):
            pass
