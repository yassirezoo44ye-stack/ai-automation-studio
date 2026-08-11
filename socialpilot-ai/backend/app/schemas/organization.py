from __future__ import annotations

import uuid

from app.models.organization_member import OrganizationRole
from app.schemas.common import ORMModel


class OrganizationPublic(ORMModel):
    id: uuid.UUID
    name: str
    slug: str


class OrganizationMembership(OrganizationPublic):
    role: OrganizationRole


class OrganizationMemberPublic(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role: OrganizationRole
