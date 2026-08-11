from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        action: str,
        user_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            user_id=user_id,
            organization_id=organization_id,
            resource_type=resource_type,
            resource_id=resource_id,
            event_metadata=metadata or {},
            ip_address=ip_address,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
