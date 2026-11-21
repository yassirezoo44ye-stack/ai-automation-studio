"""Opt-in, per-user BYOK ciphertext re-encryption.

Run only with a verified tenant scope inside scoped_credential_transaction.
Does not enumerate users or change database schema. Callers must retain
previous keys until an independent full-coverage audit is complete.
"""
from __future__ import annotations

import uuid

from cryptography.fernet import InvalidToken

from app.ai.user_credentials import _cipher


async def rotate_user_credentials(conn, *, org_id: str, user_id: str, batch_size: int = 50) -> dict[str, int]:
    """Re-encrypt a bounded user's credentials with the configured primary key.

    Caller MUST open scoped_credential_transaction with the authenticated
    org_id/user_id. This function intentionally cannot change the RLS scope.
    On any invalid token, abort the surrounding transaction (fail closed).
    """
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    org, user = uuid.UUID(org_id), uuid.UUID(user_id)
    cipher = _cipher()
    rows = await conn.fetch(
        """SELECT provider, encrypted_key FROM ai_user_credentials
           WHERE org_id=$1 AND user_id=$2 ORDER BY provider LIMIT $3
           FOR UPDATE""", org, user, batch_size,
    )
    rotated = 0
    for row in rows:
        token = row["encrypted_key"].encode("ascii")
        # MultiFernet.rotate() decrypts with any configured key, re-encrypts
        # with the primary, and preserves the original token timestamp.
        new_token = cipher.rotate(token).decode("ascii")
        result = await conn.execute(
            """UPDATE ai_user_credentials SET encrypted_key=$4, updated_at=now()
               WHERE org_id=$1 AND user_id=$2 AND provider=$3 AND encrypted_key=$5""",
            org, user, row["provider"], new_token, row["encrypted_key"],
        )
        if result != "UPDATE 1":
            raise RuntimeError("Credential changed concurrently; transaction must roll back")
        rotated += 1
    return {"scanned": len(rows), "rotated": rotated}
