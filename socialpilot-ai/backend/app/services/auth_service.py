from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationRole
from app.models.user import User
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.organization_service import OrganizationService

settings = get_settings()


@dataclass
class AuthResult:
    user: User
    memberships: list[tuple[Organization, OrganizationRole]]
    access_token: str
    access_token_expires_in: int
    refresh_token_raw: str
    refresh_token_expires_at: datetime
    csrf_token: str


@dataclass
class RequestContext:
    ip_address: str | None = None
    user_agent: str | None = None


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)
        self._audit = AuditLogRepository(session)
        self._orgs = OrganizationService(session)

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        organization_name: str | None,
        ctx: RequestContext,
    ) -> AuthResult:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise ConflictError("An account with this email already exists")

        user = await self._users.create(
            email=email, hashed_password=hash_password(password), full_name=full_name
        )
        org_name = organization_name or f"{full_name}'s Workspace"
        org = await self._orgs.create_with_owner(name=org_name, owner_id=user.id)

        await self._audit.record(
            action="auth.register",
            user_id=user.id,
            organization_id=org.id,
            resource_type="user",
            resource_id=str(user.id),
            ip_address=ctx.ip_address,
        )
        return await self._issue_tokens(user, ctx=ctx)

    async def login(self, *, email: str, password: str, ctx: RequestContext) -> AuthResult:
        user = await self._users.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            await self._audit.record(
                action="auth.login_failed",
                metadata={"email": email},
                ip_address=ctx.ip_address,
            )
            # `app.core.db.get_db` rolls back the whole request transaction on any
            # raised exception, and we're about to raise one deliberately (as an
            # expected rejection, not a bug) — commit now so the audit trail for
            # this failed attempt survives that rollback.
            await self._session.commit()
            raise AuthenticationError("Invalid email or password")
        if not user.is_active:
            raise AuthenticationError("This account has been deactivated")

        await self._audit.record(
            action="auth.login",
            user_id=user.id,
            resource_type="user",
            resource_id=str(user.id),
            ip_address=ctx.ip_address,
        )
        return await self._issue_tokens(user, ctx=ctx)

    async def refresh(self, *, raw_refresh_token: str, ctx: RequestContext) -> AuthResult:
        token_hash = hash_token(raw_refresh_token)
        existing = await self._refresh_tokens.get_by_hash(token_hash)
        if existing is None:
            raise AuthenticationError("Invalid refresh token")
        if existing.revoked_at is None and not existing.is_active:
            raise AuthenticationError("Refresh token expired")

        user = await self._users.get_by_id(existing.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account no longer available")

        # Atomically claim the token: this is the compare-and-swap that decides
        # the single winner when this same raw token is presented concurrently
        # (worker retry, double-submit, or genuine token theft racing the
        # legitimate client). Losers — including replay of an already-rotated
        # token — land here with `claimed is None`.
        claimed = await self._refresh_tokens.claim_for_rotation(token_hash)
        if claimed is None:
            await self._refresh_tokens.revoke_all_for_user(existing.user_id)
            await self._audit.record(
                action="auth.refresh_token_reuse_detected",
                user_id=existing.user_id,
                ip_address=ctx.ip_address,
            )
            # See the matching comment in `login()`: commit before raising so the
            # session-chain revocation actually takes effect instead of being
            # rolled back along with this rejected request.
            await self._session.commit()
            raise AuthenticationError("Refresh token has already been used")

        result = await self._issue_tokens(user, ctx=ctx)
        # Link the rotation for audit/debugging purposes (best-effort).
        new_hash = hash_token(result.refresh_token_raw)
        new_token = await self._refresh_tokens.get_by_hash(new_hash)
        if new_token is not None:
            claimed.replaced_by_id = new_token.id
            self._session.add(claimed)
            await self._session.flush()

        await self._audit.record(
            action="auth.refresh",
            user_id=user.id,
            ip_address=ctx.ip_address,
        )
        return result

    async def logout(self, *, raw_refresh_token: str | None, user_id: uuid.UUID | None) -> None:
        if raw_refresh_token:
            token_hash = hash_token(raw_refresh_token)
            existing = await self._refresh_tokens.get_by_hash(token_hash)
            if existing is not None and existing.revoked_at is None:
                await self._refresh_tokens.revoke(existing)
        if user_id is not None:
            await self._audit.record(action="auth.logout", user_id=user_id)

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")
        user.hashed_password = hash_password(new_password)
        await self._users.save(user)
        # Force re-login everywhere else.
        await self._refresh_tokens.revoke_all_for_user(user.id)
        await self._audit.record(action="auth.password_changed", user_id=user.id)

    async def get_user_or_raise(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def _issue_tokens(self, user: User, *, ctx: RequestContext) -> AuthResult:
        access_token = create_access_token(user_id=user.id, email=user.email)
        raw_refresh, refresh_hash, expires_at = generate_refresh_token()
        await self._refresh_tokens.create(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=expires_at,
            user_agent=ctx.user_agent,
            ip_address=ctx.ip_address,
        )
        memberships = await self._orgs.list_memberships_for_user(user.id)
        return AuthResult(
            user=user,
            memberships=memberships,
            access_token=access_token,
            access_token_expires_in=settings.access_token_ttl_minutes * 60,
            refresh_token_raw=raw_refresh,
            refresh_token_expires_at=expires_at,
            csrf_token=generate_csrf_token(),
        )
