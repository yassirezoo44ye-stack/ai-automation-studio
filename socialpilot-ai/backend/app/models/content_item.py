from __future__ import annotations

import enum
import uuid

from sqlalchemy import ARRAY, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ContentItemStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class ContentItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A saved, editable piece of content in the org's library — the
    persisted output of a generation (or a manually-created/edited item).
    `hook`/`cta`/`media_concept`/`pillar_id` and any other generation
    extras live in `metadata_` rather than as dedicated columns, to keep
    this schema from growing a column per provider-shaped field."""

    __tablename__ = "content_items"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL (not CASCADE): deleting a strategy must not silently wipe out
    # content a user already saved to their library.
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_strategies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_generations.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False, default=list)
    status: Mapped[ContentItemStatus] = mapped_column(
        Enum(ContentItemStatus, name="content_item_status"), nullable=False, default=ContentItemStatus.DRAFT
    )
    # Column named `metadata_` (attribute) / `metadata` (DB column) — `metadata`
    # is a reserved attribute name on SQLAlchemy's DeclarativeBase.
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContentItem id={self.id} platform={self.platform!r} status={self.status}>"
