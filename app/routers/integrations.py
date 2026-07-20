"""
Integration SDK — org-scoped REST surface. Personal-inbox-style
endpoints don't apply here (integrations are an org resource, like
API keys/marketplace installs), so every route goes through
require_permission() + OrgContext, matching organizations.py's convention.

Webhook receipt is the one exception: inbound webhooks come from an
external sender that can't attach an org bearer token, so that route has
no auth dependency — it's authenticated by the provider's own signature
verification instead (same pattern as /api/stripe/webhook).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.integrations import IntegrationError, get_integration_registry, get_integration_service
from app.integrations.webhooks import WebhookDuplicateError, WebhookVerificationError
from app.tenancy.context import OrgContext, require_permission

router = APIRouter(prefix="/api/orgs/{org_id}/integrations", tags=["integrations"])


@router.get("/providers")
async def list_providers(ctx: OrgContext = Depends(require_permission("integrations", "read"))):
    """Available provider implementations (registered, not necessarily
    connected for this org yet)."""
    return {"providers": [
        {
            "provider_id": p.provider_id,
            "display_name": p.display_name,
            "provider_type": p.provider_type.value,
            "capabilities": p.capabilities().__dict__,
            "scopes": [s.__dict__ for s in p.scopes()],
        }
        for p in get_integration_registry().list_providers()
    ]}


@router.get("")
async def list_connections(ctx: OrgContext = Depends(require_permission("integrations", "read"))):
    connections = await get_integration_service().list_connections(organization_id=ctx.org_id)
    return {"integrations": connections}


class ConnectRequest(BaseModel):
    secrets: dict[str, str]
    metadata: Optional[dict] = None
    granted_scopes: list[str] = []


@router.post("/{provider_id}/connect", status_code=201)
async def connect(
    provider_id: str, body: ConnectRequest,
    ctx: OrgContext = Depends(require_permission("integrations", "manage")),
):
    try:
        return await get_integration_service().connect(
            provider_id=provider_id, organization_id=ctx.org_id, user_id=ctx.user_id,
            secrets=body.secrets, metadata=body.metadata, granted_scopes=body.granted_scopes,
        )
    except KeyError:
        raise HTTPException(404, f"Unknown provider: {provider_id!r}")
    except IntegrationError as e:
        raise HTTPException(400, str(e))


@router.delete("/{provider_id}", status_code=204)
async def disconnect(
    provider_id: str, ctx: OrgContext = Depends(require_permission("integrations", "manage")),
):
    ok = await get_integration_service().disconnect(
        provider_id=provider_id, organization_id=ctx.org_id, user_id=ctx.user_id,
    )
    if not ok:
        raise HTTPException(404, "Not connected")


@router.post("/{provider_id}/sync", status_code=202)
async def trigger_sync(
    provider_id: str, ctx: OrgContext = Depends(require_permission("integrations", "manage")),
):
    try:
        run_id = await get_integration_service().trigger_sync(provider_id=provider_id, organization_id=ctx.org_id)
    except KeyError:
        raise HTTPException(404, f"Unknown provider: {provider_id!r}")
    except IntegrationError as e:
        raise HTTPException(400, str(e))
    return {"run_id": run_id}


@router.get("/{provider_id}/sync-history")
async def sync_history(
    provider_id: str, limit: int = 20,
    ctx: OrgContext = Depends(require_permission("integrations", "read")),
):
    return {"runs": await get_integration_service().sync_history(
        provider_id=provider_id, organization_id=ctx.org_id, limit=limit,
    )}


@router.post("/{provider_id}/webhook")
async def receive_webhook(provider_id: str, org_id: str, request: Request):
    body = await request.body()
    try:
        await get_integration_service().receive_webhook(
            provider_id=provider_id, organization_id=org_id,
            headers={k.lower(): v for k, v in request.headers.items()}, body=body,
        )
    except KeyError:
        raise HTTPException(404, f"Unknown provider: {provider_id!r}")
    except WebhookVerificationError:
        raise HTTPException(401, "Signature verification failed")
    except WebhookDuplicateError:
        return {"status": "duplicate, already processed"}
    except IntegrationError as e:
        raise HTTPException(400, str(e))
    return {"status": "received"}
