"""FastAPI dependency-injection helpers: current user, tenant resolution, RBAC."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from app.core.security import TokenError, decode_access_token
from app.models.organization_member import OrganizationMember, OrganizationRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.auth_service import RequestContext
from app.services.organization_service import OrganizationService

_bearer_scheme = HTTPBearer(auto_error=False)


def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Malformed token subject") from exc

    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User no longer available")
    return user


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active:
        raise AuthenticationError("Account deactivated")
    return user


def require_org_member() -> Callable:
    """Dependency factory resolving `organization_id` (path param) + the current
    user into an `OrganizationMember`, 404ing if the org doesn't exist and 403ing
    if the user isn't a member — this is the tenant-isolation boundary every
    org-scoped endpoint must depend on."""

    async def _dep(
        organization_id: uuid.UUID,
        user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> OrganizationMember:
        org_service = OrganizationService(db)
        org = await org_service.get_by_id(organization_id)
        if org is None:
            raise NotFoundError("Organization not found")
        member = await org_service.get_member(organization_id=organization_id, user_id=user.id)
        if member is None:
            # Same response as "not found" — never leak whether an org exists to
            # a non-member (IDOR/enumeration hardening).
            raise NotFoundError("Organization not found")
        return member

    return _dep


def require_role(*allowed_roles: OrganizationRole) -> Callable:
    async def _dep(member: OrganizationMember = Depends(require_org_member())) -> OrganizationMember:
        if member.role not in allowed_roles:
            raise AuthorizationError(
                f"Role '{member.role.value}' is not permitted to perform this action"
            )
        return member

    return _dep
