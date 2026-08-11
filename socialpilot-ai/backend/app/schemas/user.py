from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class UserPublic(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_verified: bool
    created_at: datetime
