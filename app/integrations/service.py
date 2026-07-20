"""
IntegrationService — the single entry point routers call. Ties together
the registry, credential store, sync engine, permission checks, events,
metrics, and audit logging so no caller has to remember to wire all of
that by hand for every provider.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.integrations.types import IntegrationCredential, IntegrationStatus

log = logging.getLogger(__name__)


class IntegrationError(Exception):
    pass


class IntegrationService:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def connect(
        self, *, provider_id: str, organization_id: str, user_id: str,
        secrets: dict[str, str], metadata: Optional[dict[str, Any]] = None,
        granted_scopes: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        from app.integrations.registry import get_integration_registry
        from app.integrations.credential_store import get_credential_store
        from app.integrations.permissions import validate_requested_scopes
        from app.integrations.events import publish_connected
        from app.integrations.metrics import record_connection_change

        provider = get_integration_registry().require(provider_id)
        granted_scopes = granted_scopes or []
        problems = validate_requested_scopes(provider, granted_scopes)
        if problems:
            raise IntegrationError("; ".join(problems))

        credential = IntegrationCredential(
            provider_id=provider_id, organization_id=organization_id,
            provider_type=provider.provider_type, secrets=secrets, metadata=metadata or {},
        )
        healthy = await provider.test_connection(credential)
        if not healthy:
            raise IntegrationError(f"connection test failed for {provider_id}")

        await get_credential_store(self._pool).save(credential)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO integrations
                    (organization_id, provider_id, provider_type, status, granted_scopes, connected_by)
                VALUES ($1,$2,$3,'connected',$4,$5)
                ON CONFLICT (organization_id, provider_id) DO UPDATE SET
                    status='connected', granted_scopes=EXCLUDED.granted_scopes,
                    connected_by=EXCLUDED.connected_by, updated_at=NOW()
                """,
                uuid.UUID(organization_id), provider_id, provider.provider_type.value,
                granted_scopes, uuid.UUID(user_id),
            )
            await conn.execute(
                "INSERT INTO activity_logs (organization_id, actor_id, action, resource, resource_id) "
                "VALUES ($1,$2,'integration.connected','integration',$3)",
                uuid.UUID(organization_id), uuid.UUID(user_id), provider_id,
            )

        await publish_connected(provider_id, organization_id)
        record_connection_change(connected=True)
        return {"provider_id": provider_id, "status": IntegrationStatus.CONNECTED.value}

    async def disconnect(self, *, provider_id: str, organization_id: str, user_id: str) -> bool:
        from app.integrations.registry import get_integration_registry
        from app.integrations.credential_store import get_credential_store
        from app.integrations.events import publish_disconnected
        from app.integrations.metrics import record_connection_change

        credential = await get_credential_store(self._pool).load(provider_id, organization_id)
        if credential is None:
            return False

        provider = get_integration_registry().get(provider_id)
        if provider is not None:
            try:
                await provider.disconnect(credential)
            except Exception:
                log.warning("provider.disconnect() failed for %s (continuing)", provider_id, exc_info=True)

        await get_credential_store(self._pool).delete(provider_id, organization_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE integrations SET status='disconnected', updated_at=NOW() "
                "WHERE organization_id=$1 AND provider_id=$2",
                uuid.UUID(organization_id), provider_id,
            )
            await conn.execute(
                "INSERT INTO activity_logs (organization_id, actor_id, action, resource, resource_id) "
                "VALUES ($1,$2,'integration.disconnected','integration',$3)",
                uuid.UUID(organization_id), uuid.UUID(user_id), provider_id,
            )

        await publish_disconnected(provider_id, organization_id)
        record_connection_change(connected=False)
        return True

    async def list_connections(self, *, organization_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT provider_id, provider_type, status, granted_scopes, connected_at, last_sync_at
                   FROM integrations WHERE organization_id=$1 ORDER BY connected_at DESC""",
                uuid.UUID(organization_id),
            )
        return [dict(r) for r in rows]

    async def trigger_sync(self, *, provider_id: str, organization_id: str) -> str:
        from app.integrations.registry import get_integration_registry
        from app.integrations.sync_engine import get_sync_engine

        provider = get_integration_registry().require(provider_id)
        if not provider.capabilities().sync:
            raise IntegrationError(f"{provider_id} does not support sync")

        async with self._pool.acquire() as conn:
            owned = await conn.fetchval(
                "SELECT 1 FROM integrations WHERE organization_id=$1 AND provider_id=$2 AND status != 'disconnected'",
                uuid.UUID(organization_id), provider_id,
            )
        if not owned:
            raise IntegrationError(f"{provider_id} is not connected for this organization")

        return await get_sync_engine(self._pool).schedule_sync(provider_id=provider_id, organization_id=organization_id)

    async def sync_history(self, *, provider_id: str, organization_id: str, limit: int = 20) -> list[dict[str, Any]]:
        from app.integrations.sync_engine import get_sync_engine
        return await get_sync_engine(self._pool).list_history(provider_id=provider_id, organization_id=organization_id, limit=limit)

    async def receive_webhook(
        self, *, provider_id: str, organization_id: str, headers: dict[str, str], body: bytes,
    ) -> None:
        from app.integrations.registry import get_integration_registry
        from app.integrations.credential_store import get_credential_store
        from app.integrations.webhooks import receive_webhook
        from app.integrations.events import publish_webhook_received
        from app.integrations.metrics import record_webhook_received

        provider = get_integration_registry().require(provider_id)
        if not provider.capabilities().webhooks:
            raise IntegrationError(f"{provider_id} does not support webhooks")

        credential = await get_credential_store(self._pool).load(provider_id, organization_id)
        if credential is None:
            raise IntegrationError(f"{provider_id} is not connected for this organization")

        await receive_webhook(provider=provider, credential=credential, headers=headers, body=body, pool=self._pool)
        await publish_webhook_received(provider_id, organization_id)
        record_webhook_received()


_service: Optional[IntegrationService] = None


def get_integration_service(pool=None) -> IntegrationService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = IntegrationService(pool)
    return _service
