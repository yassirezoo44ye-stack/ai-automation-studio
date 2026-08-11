from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrganizationRole


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, org_id: uuid.UUID) -> Organization | None:
        return await self._session.get(Organization, org_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(Organization.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, *, name: str, slug: str, owner_id: uuid.UUID) -> Organization:
        org = Organization(name=name, slug=slug, owner_id=owner_id)
        self._session.add(org)
        await self._session.flush()
        return org

    async def list_for_user(self, user_id: uuid.UUID) -> list[Organization]:
        stmt = (
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class OrganizationMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, role: OrganizationRole
    ) -> OrganizationMember:
        member = OrganizationMember(organization_id=organization_id, user_id=user_id, role=role)
        self._session.add(member)
        await self._session.flush()
        return member

    async def get(self, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationMember | None:
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[OrganizationMember]:
        stmt = (
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(OrganizationMember.organization_id == organization_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
