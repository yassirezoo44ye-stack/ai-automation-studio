from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.content_item import ContentItem
from app.repositories.content_item_repository import ContentItemRepository
from app.schemas.content import ContentItemCreate, ContentItemUpdate


class ContentItemService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._items = ContentItemRepository(session)

    async def create(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, payload: ContentItemCreate,
    ) -> ContentItem:
        fields = payload.model_dump()
        fields["metadata_"] = fields.pop("metadata")
        return await self._items.create(organization_id=organization_id, user_id=user_id, **fields)

    async def list_for_org(
        self, organization_id: uuid.UUID, *, platform: str | None = None, status: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[ContentItem]:
        return await self._items.list_for_org(
            organization_id, platform=platform, status=status, limit=limit, offset=offset
        )

    async def get_or_raise(self, *, item_id: uuid.UUID, organization_id: uuid.UUID) -> ContentItem:
        item = await self._items.get(item_id=item_id, organization_id=organization_id)
        if item is None:
            raise NotFoundError("Content item not found")
        return item

    async def update(self, item: ContentItem, *, payload: ContentItemUpdate) -> ContentItem:
        updates = payload.model_dump(exclude_unset=True)
        if "metadata" in updates:
            updates["metadata_"] = updates.pop("metadata")
        for field, value in updates.items():
            setattr(item, field, value)
        self._session.add(item)
        await self._session.flush()
        # See ContentStrategyService.update()'s comment: `updated_at` is
        # server-computed and left expired after an UPDATE flush; refresh
        # here (still inside an awaited context) so returning/serializing
        # this object afterwards doesn't hit a MissingGreenlet lazy-load.
        await self._session.refresh(item)
        return item

    async def delete(self, item: ContentItem) -> None:
        await self._items.delete(item)
