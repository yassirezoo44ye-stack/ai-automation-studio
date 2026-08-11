from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant. Every domain-owned row elsewhere in the schema carries
    `organization_id` and is scoped to one row here."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    members: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization id={self.id} slug={self.slug!r}>"
