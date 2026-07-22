"""
CredentialStore — encrypted-at-rest persistence for integration
credentials. Same Fernet-from-SESSION_SECRET derivation as
app/plugins/secrets.py (deliberately not hand-rolled — see that module's
docstring for why encryption is the one exception to this codebase's
"no new dependency" default), applied to the integrations schema instead
of plugin_secrets so each subsystem owns its own table.
"""
from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.auth import derive_fernet_key
from app.integrations.types import IntegrationCredential, ProviderType


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(derive_fernet_key("integrations"))


class CredentialStore:
    """Interface every credential backend implements. The default
    PostgresCredentialStore below is what the app actually uses; the
    interface exists so tests (and any future backend, e.g. a KMS-backed
    store) can substitute a fake without touching callers."""

    async def save(self, credential: IntegrationCredential) -> None:
        raise NotImplementedError

    async def load(self, provider_id: str, organization_id: str) -> Optional[IntegrationCredential]:
        raise NotImplementedError

    async def delete(self, provider_id: str, organization_id: str) -> bool:
        raise NotImplementedError

    async def list_for_org(self, organization_id: str) -> list[IntegrationCredential]:
        raise NotImplementedError


class PostgresCredentialStore(CredentialStore):
    def __init__(self, pool):
        self._pool = pool

    async def save(self, credential: IntegrationCredential) -> None:
        encrypted = _fernet().encrypt(json.dumps(credential.secrets).encode("utf-8")).decode("utf-8")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO integration_credentials
                    (provider_id, organization_id, provider_type, secrets_encrypted, metadata, expires_at)
                VALUES ($1,$2,$3,$4,$5,to_timestamp($6))
                ON CONFLICT (provider_id, organization_id) DO UPDATE SET
                    secrets_encrypted = EXCLUDED.secrets_encrypted,
                    metadata = EXCLUDED.metadata,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                """,
                credential.provider_id, uuid.UUID(credential.organization_id), credential.provider_type.value,
                encrypted, json.dumps(credential.metadata), credential.expires_at,
            )

    async def load(self, provider_id: str, organization_id: str) -> Optional[IntegrationCredential]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT provider_id, organization_id, provider_type, secrets_encrypted, metadata,
                          extract(epoch from expires_at) AS expires_at
                   FROM integration_credentials WHERE provider_id=$1 AND organization_id=$2""",
                provider_id, uuid.UUID(organization_id),
            )
        if row is None:
            return None
        try:
            secrets_dict = json.loads(_fernet().decrypt(row["secrets_encrypted"].encode("utf-8")).decode("utf-8"))
        except InvalidToken:
            return None
        return IntegrationCredential(
            provider_id=row["provider_id"], organization_id=str(row["organization_id"]),
            provider_type=ProviderType(row["provider_type"]), secrets=secrets_dict,
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            expires_at=row["expires_at"],
        )

    async def delete(self, provider_id: str, organization_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM integration_credentials WHERE provider_id=$1 AND organization_id=$2",
                provider_id, uuid.UUID(organization_id),
            )
        return not result.endswith(" 0")

    async def list_for_org(self, organization_id: str) -> list[IntegrationCredential]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT provider_id, organization_id, provider_type, secrets_encrypted, metadata,
                          extract(epoch from expires_at) AS expires_at
                   FROM integration_credentials WHERE organization_id=$1""",
                uuid.UUID(organization_id),
            )
        out = []
        for row in rows:
            try:
                secrets_dict = json.loads(_fernet().decrypt(row["secrets_encrypted"].encode("utf-8")).decode("utf-8"))
            except InvalidToken:
                continue
            out.append(IntegrationCredential(
                provider_id=row["provider_id"], organization_id=str(row["organization_id"]),
                provider_type=ProviderType(row["provider_type"]), secrets=secrets_dict,
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                expires_at=row["expires_at"],
            ))
        return out


_store: Optional[CredentialStore] = None


def get_credential_store(pool=None) -> CredentialStore:
    global _store
    if _store is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _store = PostgresCredentialStore(pool)
    return _store
