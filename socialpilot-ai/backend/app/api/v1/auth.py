from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_request_context
from app.core.config import get_settings
from app.core.cookies import (
    clear_csrf_cookie,
    clear_refresh_cookie,
    set_csrf_cookie,
    set_refresh_cookie,
)
from app.core.db import get_db
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import limiter
from app.core.security import csrf_tokens_match
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
)
from app.schemas.organization import OrganizationMembership
from app.schemas.user import UserPublic
from app.services.auth_service import AuthResult, AuthService, RequestContext
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _to_response(result: AuthResult, response: Response) -> AccessTokenResponse:
    set_refresh_cookie(response, token=result.refresh_token_raw, expires_at=result.refresh_token_expires_at)
    set_csrf_cookie(response, token=result.csrf_token, expires_at=result.refresh_token_expires_at)
    return AccessTokenResponse(
        access_token=result.access_token,
        expires_in=result.access_token_expires_in,
        csrf_token=result.csrf_token,
        user=UserPublic.model_validate(result.user),
        organizations=[
            OrganizationMembership(id=org.id, name=org.name, slug=org.slug, role=role)
            for org, role in result.memberships
        ],
    )


def _require_csrf(request: Request) -> None:
    cookie_value = request.cookies.get(settings.csrf_cookie_name)
    header_value = request.headers.get("x-csrf-token")
    if not csrf_tokens_match(cookie_value, header_value):
        raise AuthenticationError("Missing or invalid CSRF token")


@router.post("/register", response_model=AccessTokenResponse, status_code=201)
@limiter.limit(settings.auth_rate_limit)
async def register(
    request: Request,
    payload: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
) -> AccessTokenResponse:
    service = AuthService(db)
    result = await service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
        ctx=ctx,
    )
    return _to_response(result, response)


@router.post("/login", response_model=AccessTokenResponse)
@limiter.limit(settings.auth_rate_limit)
async def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
) -> AccessTokenResponse:
    service = AuthService(db)
    result = await service.login(email=payload.email, password=payload.password, ctx=ctx)
    return _to_response(result, response)


@router.post("/refresh", response_model=AccessTokenResponse)
@limiter.limit(settings.auth_rate_limit)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
) -> AccessTokenResponse:
    _require_csrf(request)
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise AuthenticationError("Missing refresh token")
    service = AuthService(db)
    result = await service.refresh(raw_refresh_token=raw_token, ctx=ctx)
    return _to_response(result, response)


@router.post("/logout", status_code=204, response_model=None)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        # Logout is destructive to the session but not a state change an attacker
        # gains from (it can only end a session, not hijack one) — still require
        # CSRF match when a refresh cookie is actually present, for defense in depth.
        _require_csrf(request)
    service = AuthService(db)
    await service.logout(raw_refresh_token=raw_token, user_id=None)
    clear_refresh_cookie(response)
    clear_csrf_cookie(response)


@router.get("/me", response_model=MeResponse)
async def me(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    memberships = await OrganizationService(db).list_memberships_for_user(user.id)
    return MeResponse(
        user=UserPublic.model_validate(user),
        organizations=[
            OrganizationMembership(id=org.id, name=org.name, slug=org.slug, role=role)
            for org, role in memberships
        ],
    )


@router.post("/change-password", status_code=204, response_model=None)
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = AuthService(db)
    await service.change_password(
        user=user, current_password=payload.current_password, new_password=payload.new_password
    )
    clear_refresh_cookie(response)
    clear_csrf_cookie(response)
