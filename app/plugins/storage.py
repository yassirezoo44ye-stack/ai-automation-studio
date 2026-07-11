"""
Storage API backing store — namespaced per-installation key/value storage,
backing PluginContext.storage_get/put/delete. Distinct from StorageProvider
(provider_types.py) — that's a plugin OFFERING storage to the platform,
this is the platform offering storage TO a plugin.
"""
from __future__ import annotations

import json
import uuid
from typing import Any


async def get_plugin_value(installation_id: str, key: str) -> Any:
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM plugin_storage WHERE installation_id=$1 AND key=$2",
            uuid.UUID(installation_id), key,
        )
    if row is None:
        return None
    value = row["value"]
    return json.loads(value) if isinstance(value, str) else value


async def put_plugin_value(installation_id: str, key: str, value: Any) -> None:
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO plugin_storage (installation_id, key, value)
               VALUES ($1,$2,$3)
               ON CONFLICT (installation_id, key) DO UPDATE SET
                 value=EXCLUDED.value, updated_at=NOW()""",
            uuid.UUID(installation_id), key, json.dumps(value),
        )


async def delete_plugin_value(installation_id: str, key: str) -> bool:
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        result = await conn.execute(
            "DELETE FROM plugin_storage WHERE installation_id=$1 AND key=$2",
            uuid.UUID(installation_id), key,
        )
    return result != "DELETE 0"
