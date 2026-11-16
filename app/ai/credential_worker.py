"""One-scope BYOK rotation worker; caller owns the transaction and authorization.

Run inside scoped_credential_transaction with a restricted DB role.
The claim, re-encryption, verification, and completion must share ONE
transaction: any exception rolls back the claim and ciphertext together.
No public API, tenant enumeration, or automatic key retirement.
"""
from __future__ import annotations
from app.ai.credential_lease import claim_checkpoint, finish_checkpoint
from app.ai.credential_rls import scoped_credential_transaction
from app.ai.credential_rotation import rotate_user_credentials
from app.ai.credential_verification import verify_user_primary_key

async def rotate_and_verify_scope(conn, *, org_id: str, user_id: str) -> dict[str, int | bool | str]:
    token = await claim_checkpoint(conn, org_id=org_id, user_id=user_id)
    if token is None:
        return {"claimed": False, "verified": False}
    rotated = await rotate_user_credentials(conn, org_id=org_id, user_id=user_id)
    verification = await verify_user_primary_key(conn, org_id=org_id, user_id=user_id)
    if rotated["scanned"] == 0 or not verification["complete"] or verification["scanned"] != rotated["scanned"]:
        # Must raise to roll back all ciphertext changes, not persist 'verified'.
        raise RuntimeError("BYOK scope verification failed; transaction must roll back")
    if not await finish_checkpoint(conn, org_id=org_id, user_id=user_id, lease_token=token, verified=True):
        raise RuntimeError("BYOK lease expired or changed; transaction must roll back")
    return {"claimed": True, "verified": True, "scanned": rotated["scanned"]}


async def run_scoped_rotation(conn, *, org_id: str, user_id: str) -> dict[str, int | bool | str]:
    """Public worker entrypoint for trusted, already-authorized scope IDs.

    Owns the transaction so a failed rotation cannot commit a claimed lease
    or partially re-encrypted credentials. Never expose as an HTTP endpoint.
    """
    async with scoped_credential_transaction(conn, org_id=org_id, user_id=user_id):
        return await rotate_and_verify_scope(conn, org_id=org_id, user_id=user_id)
