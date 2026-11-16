"""Opt-in, organization-scoped BYOK credential vault (not wired to APIs).

Only verified identity-context callers may supply org_id/user_id. Secrets are
encrypted at rest; never return ciphertext or plaintext through an API.
"""
from __future__ import annotations

import uuid

from cryptography.fernet import Fernet

from app.core.auth import derive_fernet_key

ALLOWED_PROVIDERS = frozenset({"openai", "anthropic", "gemini", "openrouter", "groq"})

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_user_credentials (
    org_id UUID NOT NULL,
    user_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN
        ('openai','anthropic','gemini','openrouter','groq')),
    encrypted_key TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id, provider)
);
"""


def _validate_provider(provider: str) -> str:
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError("Unsupported BYOK provider")
    return provider


def _cipher() -> Fernet:
    # Domain separation from existing OAuth and plugin secret encryption.
    return Fernet(derive_fernet_key("ai-user-credentials"))


async def put_key(conn, *, org_id: str, user_id: str, provider: str, api_key: str) -> None:
    _validate_provider(provider)
    if not api_key or not api_key.strip() or len(api_key) > 8192:
        raise ValueError("Invalid credential")
    encrypted = _cipher().encrypt(api_key.encode("utf-8")).decode("ascii")
    await conn.execute(
        """INSERT INTO ai_user_credentials (org_id,user_id,provider,encrypted_key)
           VALUES ($1,$2,$3,$4)
           ON CONFLICT (org_id,user_id,provider) DO UPDATE SET
               encrypted_key=EXCLUDED.encrypted_key, updated_at=now()""",
        uuid.UUID(org_id), uuid.UUID(user_id), provider, encrypted,
    )


async def get_key_for_execution(conn, *, org_id: str, user_id: str, provider: str) -> str | None:
    """Internal server-side use only, after identity and org membership checks."""
    _validate_provider(provider)
    row = await conn.fetchrow(
        """SELECT encrypted_key FROM ai_user_credentials
           WHERE org_id=$1 AND user_id=$2 AND provider=$3""",
        uuid.UUID(org_id), uuid.UUID(user_id), provider,
    )
    if row is None:
        return None
    # Fail closed on key rotation or corrupt ciphertext; never return fallback.
    return _cipher().decrypt(row["encrypted_key"].encode("ascii")).decode("utf-8")


async def revoke_key(conn, *, org_id: str, user_id: str, provider: str) -> bool:
    _validate_provider(provider)
    result = await conn.execute(
        """DELETE FROM ai_user_credentials
           WHERE org_id=$1 AND user_id=$2 AND provider=$3""",
        uuid.UUID(org_id), uuid.UUID(user_id), provider,
    )
    return result == "DELETE 1"
