from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.content_strategy import ContentStrategy


class ContentPillar(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One recurring theme within a strategy (e.g. "AI Tools", "Case
    Studies") — generation requests can target a specific pillar so content
    doesn't drift into one repetitive topic."""

    __tablename__ = "content_pillars"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_strategies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Relative weight/order among a strategy's pillars — purely advisory
    # (e.g. for distributing generation across pillars in a later phase);
    # not enforced to sum to 100.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    strategy: Mapped["ContentStrategy"] = relationship(back_populates="pillars")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContentPillar id={self.id} name={self.name!r} strategy={self.strategy_id}>"
