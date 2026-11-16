"""Verify one BYOK user's ciphertext is readable by the primary key alone.

This is a scoped, read-only diagnostic; not proof of deployment-wide rotation.
Caller must use a verified identity and scoped_credential_transaction.
"""
from __future__ import annotations
import uuid
from cryptography.fernet import Fernet, InvalidToken
from app.ai.user_credentials import _cipher

async def verify_user_primary_key(conn, *, org_id: str, user_id: str) -> dict[str, int | bool]:
    org, user = uuid.UUID(org_id), uuid.UUID(user_id)
    # Validate full key configuration, including malformed previous keys.
    primary = _cipher()._fernets[0]
    rows = await conn.fetch(
        """SELECT encrypted_key FROM ai_user_credentials
           WHERE org_id=$1 AND user_id=$2 ORDER BY provider""", org, user
    )
    invalid = 0
    for row in rows:
        try:
            primary.decrypt(row["encrypted_key"].encode("ascii"))
        except (InvalidToken, UnicodeError, ValueError):
            invalid += 1
    return {"scanned": len(rows), "not_primary": invalid, "complete": invalid == 0}
