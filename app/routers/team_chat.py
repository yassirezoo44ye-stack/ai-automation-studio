"""
Teams/Organizations real-time chat — REST surface.

GET    /api/orgs/{org_id}/chat/messages                    general room history
POST   /api/orgs/{org_id}/chat/messages                    post to general room
GET    /api/orgs/{org_id}/teams/{team_id}/chat/messages    team room history
POST   /api/orgs/{org_id}/teams/{team_id}/chat/messages    post to team room
DELETE /api/orgs/{org_id}/chat/messages/{message_id}       delete own message (either room)

New messages also broadcast over the existing WS `_ConnectionManager`
(app/routers/ws.py) on topic `chat:org:{org_id}` or `chat:team:{team_id}` —
see /ws/chat/{room_key} for the live side. This mirrors the notifications
dispatcher's own pattern: a REST write, then a direct broadcast call, no
extra event-bus indirection needed for a single-source event like a chat
post.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.chat import get_chat_service
from app.tenancy import OrgContext, get_tenancy_service, require_permission

router = APIRouter(prefix="/api/orgs", tags=["team-chat"])


class PostMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


async def _require_team_in_org(org_id: str, team_id: str) -> None:
    team = await get_tenancy_service().get_team(org_id, team_id)
    if team is None:
        raise HTTPException(404, "Team not found")


@router.get("/{org_id}/chat/messages")
async def list_general_messages(
    before: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    ctx: OrgContext = Depends(require_permission("chat", "read")),
):
    messages = await get_chat_service().list_messages(
        organization_id=ctx.org_id, team_id=None, before=before, limit=limit,
    )
    return {"messages": messages, "has_more": len(messages) == limit}


@router.post("/{org_id}/chat/messages", status_code=201)
async def post_general_message(
    body: PostMessageRequest,
    ctx: OrgContext = Depends(require_permission("chat", "create")),
):
    from app.routers.ws import manager as ws_manager
    try:
        message = await get_chat_service().create_message(
            organization_id=ctx.org_id, team_id=None, user_id=ctx.user_id, body=body.body,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await ws_manager.broadcast(f"chat:org:{ctx.org_id}", message)
    return message


@router.get("/{org_id}/teams/{team_id}/chat/messages")
async def list_team_messages(
    team_id: str,
    before: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    ctx: OrgContext = Depends(require_permission("chat", "read")),
):
    await _require_team_in_org(ctx.org_id, team_id)
    messages = await get_chat_service().list_messages(
        organization_id=ctx.org_id, team_id=team_id, before=before, limit=limit,
    )
    return {"messages": messages, "has_more": len(messages) == limit}


@router.post("/{org_id}/teams/{team_id}/chat/messages", status_code=201)
async def post_team_message(
    team_id: str,
    body: PostMessageRequest,
    ctx: OrgContext = Depends(require_permission("chat", "create")),
):
    await _require_team_in_org(ctx.org_id, team_id)
    from app.routers.ws import manager as ws_manager
    try:
        message = await get_chat_service().create_message(
            organization_id=ctx.org_id, team_id=team_id, user_id=ctx.user_id, body=body.body,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await ws_manager.broadcast(f"chat:team:{team_id}", message)
    return message


@router.delete("/{org_id}/chat/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: str,
    ctx: OrgContext = Depends(require_permission("chat", "read")),
):
    """Any org member may attempt this — ChatService.delete_message() itself
    enforces ownership (WHERE user_id=$2), so a non-owner's request simply
    matches no row rather than needing a separate authorization branch here."""
    deleted = await get_chat_service().delete_message(message_id=message_id, user_id=ctx.user_id)
    if not deleted:
        raise HTTPException(404, "Message not found")
