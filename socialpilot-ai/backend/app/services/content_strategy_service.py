from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.content_pillar import ContentPillar
from app.models.content_strategy import ContentStrategy
from app.repositories.content_strategy_repository import (
    ContentPillarRepository,
    ContentStrategyRepository,
)
from app.schemas.content import ContentPillarCreate, ContentPillarUpdate, ContentStrategyCreate, ContentStrategyUpdate


class ContentStrategyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._strategies = ContentStrategyRepository(session)
        self._pillars = ContentPillarRepository(session)

    async def create(self, *, organization_id: uuid.UUID, payload: ContentStrategyCreate) -> ContentStrategy:
        return await self._strategies.create(organization_id=organization_id, **payload.model_dump())

    async def list_for_org(self, organization_id: uuid.UUID) -> list[ContentStrategy]:
        return await self._strategies.list_for_org(organization_id)

    async def get_or_raise(self, *, strategy_id: uuid.UUID, organization_id: uuid.UUID) -> ContentStrategy:
        strategy = await self._strategies.get(strategy_id=strategy_id, organization_id=organization_id)
        if strategy is None:
            raise NotFoundError("Content strategy not found")
        return strategy

    async def update(self, strategy: ContentStrategy, *, payload: ContentStrategyUpdate) -> ContentStrategy:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(strategy, field, value)
        self._session.add(strategy)
        await self._session.flush()
        # `updated_at` is server-computed (onupdate=func.now(), see mixins.py) —
        # after an UPDATE flush SQLAlchemy marks it expired rather than
        # populating it inline, and a later *synchronous* touch of it (e.g.
        # Pydantic's model_validate serializing the response) can't lazily
        # reload it — there's no event loop to await through at that point,
        # so it raises MissingGreenlet instead. Refreshing here, still inside
        # an awaited context, gets the real server value up front.
        await self._session.refresh(strategy)
        return strategy

    async def delete(self, strategy: ContentStrategy) -> None:
        await self._strategies.delete(strategy)

    # --- Pillars -------------------------------------------------------------

    async def add_pillar(
        self, *, strategy: ContentStrategy, organization_id: uuid.UUID, payload: ContentPillarCreate,
    ) -> ContentPillar:
        return await self._pillars.create(
            organization_id=organization_id, strategy_id=strategy.id, **payload.model_dump()
        )

    async def list_pillars(self, *, strategy_id: uuid.UUID, organization_id: uuid.UUID) -> list[ContentPillar]:
        return await self._pillars.list_for_strategy(strategy_id=strategy_id, organization_id=organization_id)

    async def get_pillar_or_raise(self, *, pillar_id: uuid.UUID, organization_id: uuid.UUID) -> ContentPillar:
        pillar = await self._pillars.get(pillar_id=pillar_id, organization_id=organization_id)
        if pillar is None:
            raise NotFoundError("Content pillar not found")
        return pillar

    async def update_pillar(self, pillar: ContentPillar, *, payload: ContentPillarUpdate) -> ContentPillar:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(pillar, field, value)
        self._session.add(pillar)
        await self._session.flush()
        await self._session.refresh(pillar)  # see the comment in update() above
        return pillar

    async def delete_pillar(self, pillar: ContentPillar) -> None:
        await self._pillars.delete(pillar)
