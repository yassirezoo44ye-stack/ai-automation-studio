from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_org_member, require_role
from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.models.organization_member import OrganizationMember, OrganizationRole
from app.models.user import User
from app.schemas.organization import (
    OrganizationMemberPublic,
    OrganizationMembership,
    OrganizationPublic,
)
from app.schemas.organization_update import OrganizationUpdateRequest
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationMembership])
async def list_my_organizations(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationMembership]:
    memberships = await OrganizationService(db).list_memberships_for_user(user.id)
    return [
        OrganizationMembership(id=org.id, name=org.name, slug=org.slug, role=role)
        for org, role in memberships
    ]


@router.get("/{organization_id}", response_model=OrganizationPublic)
async def get_organization(
    organization_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_member()),
    db: AsyncSession = Depends(get_db),
) -> OrganizationPublic:
    org = await OrganizationService(db).get_by_id(organization_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return OrganizationPublic.model_validate(org)


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberPublic])
async def list_members(
    organization_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_member()),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationMemberPublic]:
    members = await OrganizationService(db).list_members(organization_id)
    return [OrganizationMemberPublic.model_validate(m) for m in members]


@router.patch("/{organization_id}", response_model=OrganizationPublic)
async def rename_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdateRequest,
    member: OrganizationMember = Depends(
        require_role(OrganizationRole.OWNER, OrganizationRole.ADMIN)
    ),
    db: AsyncSession = Depends(get_db),
) -> OrganizationPublic:
    service = OrganizationService(db)
    org = await service.get_by_id(organization_id)
    if org is None:
        raise NotFoundError("Organization not found")
    org = await service.rename(org, new_name=payload.name)
    return OrganizationPublic.model_validate(org)
