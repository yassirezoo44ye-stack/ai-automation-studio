"""Enroll one authorized BYOK credential scope into the rotation checkpoint table.

No tenant enumeration, secrets, or privilege escalation. Caller must provide
verified org/user identity and use scoped_credential_transaction.
"""
from __future__ import annotations
import uuid

async def enroll_credential_scope(conn, *, org_id: str, user_id: str) -> bool:
    org, user = uuid.UUID(org_id), uuid.UUID(user_id)
    row = await conn.fetchrow(
        """INSERT INTO ai_credential_rotation_checkpoints (org_id, user_id)
           SELECT $1, $2 WHERE EXISTS (
               SELECT 1 FROM ai_user_credentials WHERE org_id=$1 AND user_id=$2
           )
           ON CONFLICT (org_id, user_id) DO NOTHING
           RETURNING org_id""",
        org, user,
    )
    return row is not None
