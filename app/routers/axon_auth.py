"""
Axon auth HTTP API — mounted under /api/axon.

The legacy api_auth_middleware in app/factory.py lets /api/axon/ through
(PUBLIC_PREFIXES) because every route here enforces its own authentication
through app.core.axon_auth dependencies; anonymous routes (register, login,
refresh, webhook receiver) are rate limited per client IP.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core import axon_auth as auth
from app.core.axon_auth import (
    AuthenticatedDep,
    AuthError,
    ClientInfo,
    Principal,
    UserDep,
    requires,
)
from app.core.rate_limit import require_rate_limit_async

router = APIRouter(prefix="/api/axon", tags=["axon-auth"])

ApiKeysAdmin = Annotated[Principal, Depends(requires("api_keys:manage"))]
WebhooksAdmin = Annotated[Principal, Depends(requires("webhooks:manage"))]

MAX_WEBHOOK_BODY = 1024 * 1024  # 1 MiB


def _limit(prefix: str, max_calls: int, window: int = 60):
    async def _dep(request: Request) -> None:
        await require_rate_limit_async(request, key_prefix=f"axon:{prefix}", max_calls=max_calls, window=window)
    return _dep


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterIn(_Body):
    organization_name: str = Field(min_length=1, max_length=255)
    organization_slug: str = Field(min_length=3, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    full_name: str | None = Field(default=None, max_length=255)


class LoginIn(_Body):
    organization_slug: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class RefreshIn(_Body):
    refresh_token: str = Field(min_length=1, max_length=200)


class PasswordIn(_Body):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class ApiKeyIn(_Body):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=50)
    expires_at: datetime | None = None


class WebhookIn(_Body):
    name: str = Field(min_length=1, max_length=80)
    tolerance_seconds: int = Field(default=300, ge=30, le=900)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


# ── sessions ─────────────────────────────────────────────────────────────────

@router.post("/auth/register", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(_limit("register", 5, 3600))])
async def register(body: RegisterIn, request: Request, response: Response) -> dict[str, Any]:
    _no_store(response)
    pair = await auth.register(
        organization_name=body.organization_name, organization_slug=body.organization_slug,
        email=body.email, password=body.password, full_name=body.full_name,
        client=ClientInfo.from_request(request),
    )
    return pair.as_response()


@router.post("/auth/login", dependencies=[Depends(_limit("login", 20))])
async def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    _no_store(response)
    pair = await auth.login(organization_slug=body.organization_slug, email=body.email, password=body.password,
                            client=ClientInfo.from_request(request))
    return pair.as_response()


@router.post("/auth/refresh", dependencies=[Depends(_limit("refresh", 60))])
async def refresh(body: RefreshIn, request: Request, response: Response) -> dict[str, Any]:
    _no_store(response)
    pair = await auth.refresh(body.refresh_token, client=ClientInfo.from_request(request))
    return pair.as_response()


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, principal: UserDep) -> Response:
    await auth.logout(principal, client=ClientInfo.from_request(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/logout-all")
async def logout_all(request: Request, principal: UserDep) -> dict[str, int]:
    return {"tokens_revoked": await auth.logout_all(principal, client=ClientInfo.from_request(request))}


@router.post("/auth/password")
async def change_password(body: PasswordIn, request: Request, response: Response,
                          principal: UserDep) -> dict[str, Any]:
    _no_store(response)
    pair = await auth.change_password(principal, current_password=body.current_password,
                                      new_password=body.new_password, client=ClientInfo.from_request(request))
    return pair.as_response()


@router.get("/auth/me")
async def me(principal: AuthenticatedDep) -> dict[str, Any]:
    return {
        "kind": principal.kind,
        "organization_id": str(principal.organization_id),
        "user_id": str(principal.user_id) if principal.user_id else None,
        "api_key_id": str(principal.api_key_id) if principal.api_key_id else None,
        "session_id": str(principal.session_id) if principal.session_id else None,
        "scopes": sorted(principal.scopes),
    }


# ── API keys ─────────────────────────────────────────────────────────────────

@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(body: ApiKeyIn, request: Request, response: Response,
                         principal: ApiKeysAdmin) -> dict[str, Any]:
    _no_store(response)
    key = await auth.create_api_key(principal, name=body.name, scopes=body.scopes, expires_at=body.expires_at,
                                    client=ClientInfo.from_request(request))
    return {"id": str(key.id), "name": key.name, "prefix": key.prefix, "scopes": list(key.scopes),
            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            "created_at": key.created_at.isoformat(), "key": key.plaintext}


@router.get("/api-keys")
async def list_api_keys(principal: ApiKeysAdmin) -> list[dict[str, Any]]:
    return await auth.list_api_keys(principal)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID, request: Request,
                         principal: ApiKeysAdmin) -> Response:
    if not await auth.revoke_api_key(principal, key_id, client=ClientInfo.from_request(request)):
        raise AuthError(status.HTTP_404_NOT_FOUND, "not_found", "API key not found or already revoked")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── webhooks ─────────────────────────────────────────────────────────────────

@router.post("/webhook-endpoints", status_code=status.HTTP_201_CREATED)
async def create_webhook(body: WebhookIn, request: Request, response: Response,
                         principal: WebhooksAdmin) -> dict[str, Any]:
    _no_store(response)
    hook = await auth.create_webhook_endpoint(principal, name=body.name, tolerance_seconds=body.tolerance_seconds,
                                              client=ClientInfo.from_request(request))
    return {"id": str(hook.id), "name": hook.name, "tolerance_seconds": hook.tolerance_seconds,
            "secret": hook.secret, "url": f"/api/axon/webhooks/{hook.id}"}


@router.post("/webhook-endpoints/{endpoint_id}/rotate-secret")
async def rotate_webhook(endpoint_id: uuid.UUID, request: Request, response: Response,
                         principal: WebhooksAdmin) -> dict[str, str]:
    _no_store(response)
    secret = await auth.rotate_webhook_secret(principal, endpoint_id, client=ClientInfo.from_request(request))
    return {"id": str(endpoint_id), "secret": secret}


@router.post("/webhooks/{endpoint_id}", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(_limit("webhook", 600))])
async def receive_webhook(endpoint_id: uuid.UUID, request: Request) -> dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_WEBHOOK_BODY):
        raise AuthError(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload_too_large", "Payload too large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BODY:
            raise AuthError(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload_too_large", "Payload too large")
    delivery = await auth.verify_webhook_delivery(endpoint_id, headers=dict(request.headers), body=bytes(body))
    return {"accepted": True, "delivery_id": delivery.delivery_id}
