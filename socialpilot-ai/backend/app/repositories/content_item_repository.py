from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_item import ContentItem


class ContentItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, organization_id: uuid.UUID, **fields) -> ContentItem:
        item = ContentItem(organization_id=organization_id, **fields)
        self._session.add(item)
        await self._session.flush()
        return item

    async def get(self, *, item_id: uuid.UUID, organization_id: uuid.UUID) -> ContentItem | None:
        stmt = select(ContentItem).where(ContentItem.id == item_id, ContentItem.organization_id == organization_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_org(
        self, organization_id: uuid.UUID, *, platform: str | None = None, status: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[ContentItem]:
        stmt = select(ContentItem).where(ContentItem.organization_id == organization_id)
        if platform is not None:
            stmt = stmt.where(ContentItem.platform == platform)
        if status is not None:
            stmt = stmt.where(ContentItem.status == status)
        stmt = stmt.order_by(ContentItem.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, item: ContentItem) -> None:
        await self._session.delete(item)
        await self._session.flush()
