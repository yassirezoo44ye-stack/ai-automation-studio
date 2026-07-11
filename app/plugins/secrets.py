"""
Secret API backing store — per-installation encrypted key/value secrets,
backing PluginContext.get_secret/set_secret. Values are encrypted at rest
with Fernet (symmetric, authenticated encryption) keyed from this app's
existing SESSION_SECRET — deliberately not hand-rolled: encryption is one
of the few things this codebase's "hand-roll it, no new dependency" pattern
(used for e.g. marketplace's version comparator) does NOT apply to.

No endpoint anywhere returns value_encrypted or a decrypted value in bulk —
only get_plugin_secret(installation_id, key) resolves one value at a time,
for use inside a plugin's own PluginContext.
"""
from __future__ import annotations

import base64
import hashlib
import uuid
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    from app.core.config import SESSION_SECRET
    # Fernet requires a 32-byte urlsafe-base64 key; derive one deterministically
    # from SESSION_SECRET so no separate key-management step is needed.
    digest = hashlib.sha256(SESSION_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


async def get_plugin_secret(installation_id: str, key: str) -> Optional[str]:
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value_encrypted FROM plugin_secrets WHERE installation_id=$1 AND key=$2",
            uuid.UUID(installation_id), key,
        )
    if row is None:
        return None
    try:
        return _fernet().decrypt(row["value_encrypted"].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


async def set_plugin_secret(installation_id: str, key: str, value: str) -> None:
    from app.core.db import get_pool
    encrypted = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO plugin_secrets (installation_id, key, value_encrypted)
               VALUES ($1,$2,$3)
               ON CONFLICT (installation_id, key) DO UPDATE SET
                 value_encrypted=EXCLUDED.value_encrypted, updated_at=NOW()""",
            uuid.UUID(installation_id), key, encrypted,
        )


async def delete_plugin_secret(installation_id: str, key: str) -> bool:
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        result = await conn.execute(
            "DELETE FROM plugin_secrets WHERE installation_id=$1 AND key=$2",
            uuid.UUID(installation_id), key,
        )
    return result != "DELETE 0"
