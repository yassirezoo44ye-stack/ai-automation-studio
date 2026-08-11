from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def claim_for_rotation(self, token_hash: str) -> RefreshToken | None:
        """Atomically mark a still-active token as revoked and return it — or
        return None if it was already revoked/consumed (by a concurrent
        request, or replay) or never existed.

        This is a compare-and-swap on `revoked_at IS NULL` expressed as a
        single `UPDATE ... RETURNING`. Postgres takes a row lock on the
        matched row for the duration of the caller's transaction, so if two
        requests race to rotate the same token, the second one's UPDATE
        blocks until the first commits, then sees `revoked_at` already set
        and matches zero rows — exactly one caller ever gets a non-None
        result back. This is what makes refresh-token rotation safe under
        concurrent/duplicate requests (worker retries, double-clicks, token
        theft race).
        """
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(RefreshToken)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        await self._session.flush()
        return row

    async def revoke(self, token: RefreshToken, *, replaced_by_id: uuid.UUID | None = None) -> None:
        token.revoked_at = datetime.now(timezone.utc)
        if replaced_by_id is not None:
            token.replaced_by_id = replaced_by_id
        self._session.add(token)
        await self._session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        result = await self._session.execute(stmt)
        now = datetime.now(timezone.utc)
        for token in result.scalars().all():
            token.revoked_at = now
            self._session.add(token)
        await self._session.flush()
