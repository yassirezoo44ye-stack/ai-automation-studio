from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.content_pillar import ContentPillar
from app.models.content_strategy import ContentStrategy


class ContentStrategyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, organization_id: uuid.UUID, **fields) -> ContentStrategy:
        strategy = ContentStrategy(organization_id=organization_id, **fields)
        self._session.add(strategy)
        await self._session.flush()
        return strategy

    async def get(self, *, strategy_id: uuid.UUID, organization_id: uuid.UUID) -> ContentStrategy | None:
        """Tenant boundary lives here, not just in the router: the WHERE
        clause always includes organization_id, so a strategy_id from
        another org can never resolve even if somehow guessed/leaked."""
        stmt = select(ContentStrategy).where(
            ContentStrategy.id == strategy_id, ContentStrategy.organization_id == organization_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_pillars(self, *, strategy_id: uuid.UUID, organization_id: uuid.UUID) -> ContentStrategy | None:
        stmt = (
            select(ContentStrategy)
            .options(selectinload(ContentStrategy.pillars))
            .where(ContentStrategy.id == strategy_id, ContentStrategy.organization_id == organization_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[ContentStrategy]:
        stmt = (
            select(ContentStrategy)
            .where(ContentStrategy.organization_id == organization_id)
            .order_by(ContentStrategy.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, strategy: ContentStrategy) -> None:
        await self._session.delete(strategy)
        await self._session.flush()


class ContentPillarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, organization_id: uuid.UUID, strategy_id: uuid.UUID, **fields) -> ContentPillar:
        pillar = ContentPillar(organization_id=organization_id, strategy_id=strategy_id, **fields)
        self._session.add(pillar)
        await self._session.flush()
        return pillar

    async def get(self, *, pillar_id: uuid.UUID, organization_id: uuid.UUID) -> ContentPillar | None:
        stmt = select(ContentPillar).where(
            ContentPillar.id == pillar_id, ContentPillar.organization_id == organization_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_strategy(self, *, strategy_id: uuid.UUID, organization_id: uuid.UUID) -> list[ContentPillar]:
        stmt = (
            select(ContentPillar)
            .where(ContentPillar.strategy_id == strategy_id, ContentPillar.organization_id == organization_id)
            .order_by(ContentPillar.priority.desc(), ContentPillar.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, pillar: ContentPillar) -> None:
        await self._session.delete(pillar)
        await self._session.flush()
