from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GenerationType(str, enum.Enum):
    IDEAS = "ideas"
    POST = "post"


class GenerationStatus(str, enum.Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ContentGeneration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An audit record of one AI generation call — request, outcome, and
    the raw structured result (or error) — regardless of whether any of
    its output was ever saved as a ContentItem. Generation in Phase 2 is
    synchronous (no job queue yet), so this is written once, after the
    provider call returns, not updated through a pending state."""

    __tablename__ = "content_generations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_strategies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    generation_type: Mapped[GenerationType] = mapped_column(
        Enum(GenerationType, name="content_generation_type"), nullable=False
    )
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus, name="content_generation_status"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    result: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContentGeneration id={self.id} type={self.generation_type} status={self.status}>"
