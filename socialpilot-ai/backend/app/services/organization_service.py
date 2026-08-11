from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrganizationRole
from app.repositories.organization_repository import (
    OrganizationMemberRepository,
    OrganizationRepository,
)
from app.utils.slugify import unique_slug


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orgs = OrganizationRepository(session)
        self._members = OrganizationMemberRepository(session)

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return await self._orgs.get_by_id(organization_id)

    async def create_with_owner(self, *, name: str, owner_id: uuid.UUID) -> Organization:
        slug = unique_slug(name)
        # Extremely unlikely collision given the random suffix, but stay correct.
        while await self._orgs.get_by_slug(slug) is not None:
            slug = unique_slug(name)
        org = await self._orgs.create(name=name, slug=slug, owner_id=owner_id)
        await self._members.add(organization_id=org.id, user_id=owner_id, role=OrganizationRole.OWNER)
        return org

    async def list_memberships_for_user(
        self, user_id: uuid.UUID
    ) -> list[tuple[Organization, OrganizationRole]]:
        orgs = await self._orgs.list_for_user(user_id)
        results: list[tuple[Organization, OrganizationRole]] = []
        for org in orgs:
            member = await self._members.get(organization_id=org.id, user_id=user_id)
            if member is not None:
                results.append((org, member.role))
        return results

    async def get_member(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationMember | None:
        return await self._members.get(organization_id=organization_id, user_id=user_id)

    async def list_members(self, organization_id: uuid.UUID) -> list[OrganizationMember]:
        return await self._members.list_for_org(organization_id)

    async def rename(self, organization: Organization, *, new_name: str) -> Organization:
        organization.name = new_name
        self._session.add(organization)
        await self._session.flush()
        return organization
