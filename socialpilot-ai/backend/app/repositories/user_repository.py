from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower().strip())
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, *, email: str, hashed_password: str, full_name: str) -> User:
        user = User(email=email.lower().strip(), hashed_password=hashed_password, full_name=full_name)
        self._session.add(user)
        await self._session.flush()
        return user

    async def save(self, user: User) -> None:
        self._session.add(user)
        await self._session.flush()
