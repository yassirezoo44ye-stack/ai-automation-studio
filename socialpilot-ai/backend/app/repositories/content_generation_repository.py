from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_generation import ContentGeneration


class ContentGenerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, organization_id: uuid.UUID, **fields) -> ContentGeneration:
        generation = ContentGeneration(organization_id=organization_id, **fields)
        self._session.add(generation)
        await self._session.flush()
        return generation

    async def get(self, *, generation_id: uuid.UUID, organization_id: uuid.UUID) -> ContentGeneration | None:
        stmt = select(ContentGeneration).where(
            ContentGeneration.id == generation_id, ContentGeneration.organization_id == organization_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
