from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only record of security/business-relevant events.

    `organization_id` is nullable because some events (e.g. a failed login before
    the org is known) aren't org-scoped yet. Never write secrets into `metadata`.
    """

    __tablename__ = "audit_logs"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog action={self.action!r} user={self.user_id} org={self.organization_id}>"
