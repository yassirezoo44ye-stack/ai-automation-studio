from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class OrganizationRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


# Roles that may manage members, billing, and org settings.
MANAGE_ROLES = (OrganizationRole.OWNER, OrganizationRole.ADMIN)
# Roles that may create/edit content and automations.
CONTENT_ROLES = (OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.EDITOR)
# Every member can view.
VIEW_ROLES = (
    OrganizationRole.OWNER,
    OrganizationRole.ADMIN,
    OrganizationRole.EDITOR,
    OrganizationRole.VIEWER,
)


class OrganizationMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Join row: a user's role within one organization. This is the tenancy
    boundary every authorization check resolves against."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member_org_user"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[OrganizationRole] = mapped_column(
        Enum(OrganizationRole, name="organization_role"), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OrgMember org={self.organization_id} user={self.user_id} role={self.role}>"
