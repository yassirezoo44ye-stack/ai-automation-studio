"""Opt-in BYOK RLS schema and transaction scope.

Unlike app.tenancy.rls's permissive unscoped policies, this policy denies
all access without BOTH org and user transaction-local settings.
Not called by application startup; requires a reviewed migration.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

RLS_SQL = """
ALTER TABLE ai_user_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_user_credentials FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS byok_private_scope ON ai_user_credentials;
CREATE POLICY byok_private_scope ON ai_user_credentials
    FOR ALL
    USING (
        org_id = nullif(current_setting('app.byok_org_id', true), '')::uuid
        AND user_id = nullif(current_setting('app.byok_user_id', true), '')::uuid
    )
    WITH CHECK (
        org_id = nullif(current_setting('app.byok_org_id', true), '')::uuid
        AND user_id = nullif(current_setting('app.byok_user_id', true), '')::uuid
    );
"""


@asynccontextmanager
async def scoped_credential_transaction(conn, *, org_id: str, user_id: str):
    """Set private transaction-local RLS identity; never persist on pool conn.

    Caller MUST obtain org_id/user_id from verified OrgContext. DB role must
    not have BYPASSRLS or superuser privileges.
    """
    org = str(uuid.UUID(org_id))
    user = str(uuid.UUID(user_id))
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.byok_org_id', $1, true)", org)
        await conn.execute("SELECT set_config('app.byok_user_id', $1, true)", user)
        yield conn
