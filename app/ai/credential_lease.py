"""Restricted-worker BYOK checkpoint leases.

All operations require a trusted caller inside scoped_credential_transaction.
The database enforces tenant isolation; this module never enumerates tenants.
"""
from __future__ import annotations
import uuid
from datetime import timedelta

async def claim_checkpoint(conn, *, org_id: str, user_id: str, lease_seconds: int = 300) -> str | None:
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 30 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be 30..3600")
    org, user = uuid.UUID(org_id), uuid.UUID(user_id)
    token = uuid.uuid4()
    # Single conditional update is atomic even with competing workers.
    row = await conn.fetchrow(
        """UPDATE ai_credential_rotation_checkpoints
           SET status='running', attempt=attempt+1, lease_token=$3,
               lease_expires_at=now()+($4::integer * interval '1 second'),
               last_error_code=NULL, updated_at=now()
           WHERE org_id=$1 AND user_id=$2
             AND (status='pending' OR (status='running' AND lease_expires_at < now()))
           RETURNING lease_token""",
        org, user, token, lease_seconds,
    )
    return str(row["lease_token"]) if row else None


async def finish_checkpoint(conn, *, org_id: str, user_id: str, lease_token: str, verified: bool, error_code: str | None = None) -> bool:
    if not isinstance(verified, bool):
        raise ValueError("verified must be boolean")
    if verified and error_code is not None:
        raise ValueError("verified checkpoint cannot contain an error")
    if not verified and error_code not in {"DECRYPT_FAILED", "VERIFY_FAILED", "ROTATION_FAILED"}:
        raise ValueError("failed checkpoint requires an approved error code")
    org, user, token = uuid.UUID(org_id), uuid.UUID(user_id), uuid.UUID(lease_token)
    row = await conn.fetchrow(
        """UPDATE ai_credential_rotation_checkpoints
           SET status=$4, lease_token=NULL, lease_expires_at=NULL,
               last_error_code=$5, updated_at=now()
           WHERE org_id=$1 AND user_id=$2 AND lease_token=$3
             AND status='running' AND lease_expires_at > now()
           RETURNING status""",
        org, user, token, "verified" if verified else "failed", error_code,
    )
    return row is not None
