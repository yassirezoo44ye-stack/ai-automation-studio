from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember
    from app.models.refresh_token import RefreshToken


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who can log in. Global — not tenant-scoped.

    Tenancy lives at the OrganizationMember level: one user can belong to many
    organizations with different roles in each.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    memberships: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User id={self.id} email={self.email!r}>"
