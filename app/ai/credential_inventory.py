"""Read-only snapshot of BYOK credential scope inventory.

Privileged audit-only connection required. Never use the application role.
This reports opaque UUID pairs and row counts, never ciphertext or API keys.
A snapshot is NOT proof that concurrent writes stopped; retirement requires
a separate write freeze and a fresh final audit.
"""
from __future__ import annotations

async def read_rotation_inventory(conn) -> list[dict[str, str | int]]:
    rows = await conn.fetch(
        """SELECT org_id, user_id, count(*)::integer AS credential_count
           FROM ai_user_credentials
           GROUP BY org_id, user_id ORDER BY org_id, user_id"""
    )
    return [
        {"org_id": str(row["org_id"]), "user_id": str(row["user_id"]),
         "credential_count": row["credential_count"]}
        for row in rows
    ]

async def read_rotation_coverage(conn) -> dict[str, int]:
    row = await conn.fetchrow(
        """WITH scopes AS (
             SELECT org_id, user_id FROM ai_user_credentials GROUP BY org_id, user_id
           )
           SELECT count(*)::integer AS expected,
                  count(c.org_id)::integer AS enrolled,
                  count(*) FILTER (WHERE c.status='verified')::integer AS verified
           FROM scopes s LEFT JOIN ai_credential_rotation_checkpoints c
           ON c.org_id=s.org_id AND c.user_id=s.user_id"""
    )
    return {"expected": row["expected"], "enrolled": row["enrolled"],
            "verified": row["verified"]}
