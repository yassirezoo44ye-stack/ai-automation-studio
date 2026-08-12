from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.content_pillar import ContentPillar


class ContentStrategy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The structured brand/business context a workspace generates content
    against. Every AI generation call (see app/services/content_service.py)
    is grounded in one of these — there is no "generate with no strategy"
    path, by design (Step 6 of the Phase 2 spec)."""

    __tablename__ = "content_strategies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_audience: Mapped[str] = mapped_column(Text, nullable=False, default="")
    goals: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tone: Mapped[str] = mapped_column(String(80), nullable=False, default="engaging")
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="english")
    brand_voice: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Free-form extras that don't warrant their own column yet — e.g.
    # {"platforms": ["x", "linkedin"], "content_mix": {"text": 0.6, "image": 0.3, "video": 0.1}}
    content_preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    pillars: Mapped[list["ContentPillar"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContentStrategy id={self.id} name={self.name!r} org={self.organization_id}>"
