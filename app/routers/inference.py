"""
AI Inference router — thin HTTP transport layer only.

All business logic lives in app.core.ai (platform, engine, services).
This file contains:
  - Request/response Pydantic models (HTTP contract)
  - Route definitions
  - Parameter extraction helpers

Zero AI logic. Zero provider imports.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai import memory as mem
from app.ai.models import (
    CompletionRequest, Message, ProviderID, ToolSchema,
)
from app.core.ai.platform import platform
from app.core.auth import owner_user_id
from app.core.db import get_pool
from app.core.rate_limit import ai_rate_limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _user_id(request: Request) -> str:
    """Resolve the caller's real user id the same way every other router in
    this codebase does (chat.py, build.py, package.py, design.py, ...) —
    NOT the request.state.user_id this module used to read, which nothing
    in the app ever sets (a dead, isolated identity mechanism that made
    every ownership filter below a no-op). Raises 401 if the caller's
    token doesn't resolve to a real account, matching owner_user_id's
    behavior everywhere else it's used."""
    async with get_pool().acquire() as conn:
        return str(await owner_user_id(conn, request))


async def _org_id(request: Request) -> Optional[str]:
    # tenant_context_middleware (app/factory.py) only stashes the raw
    # X-Organization-Id header value on request.state.org_id — by its own
    # docstring, it "never grants or denies anything"; membership is each
    # consumer's job. Quota-checking and usage-recording an AI completion
    # against an org is exactly that kind of consumer, so this verifies
    # membership (not just presence) before trusting the header, the same
    # way app.core.org_quota.check_org_quota does for the legacy routers.
    from app.tenancy.context import optional_org_id
    return await optional_org_id(request)


def _pool():
    return get_pool()


async def _require_conversation_ownership(conversation_id: Optional[str], user_id: str) -> None:
    """Reject an unowned conversation_id with 404 before spending a
    provider call on it. AIGateway itself already no-ops on an unowned
    conversation_id (empty history in, dropped write out — see
    memory.is_owned_by), so this check is redundant for correctness; it
    exists purely to fail fast instead of paying for inference against a
    request that's going to have its history/memory silently discarded
    anyway."""
    if conversation_id and not await mem.is_owned_by(_pool(), conversation_id, user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


# ── HTTP request models ───────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str
    content: str


class InferenceRequest(BaseModel):
    messages:           list[ChatMessage]
    provider:           Optional[ProviderID] = None
    model:              Optional[str]        = None
    fallback_providers: list[ProviderID]     = []
    max_tokens:         int                  = Field(2048, ge=1, le=32000)
    temperature:        float                = Field(0.7, ge=0.0, le=2.0)
    top_p:              Optional[float]      = None
    system:             Optional[str]        = None
    tools:              Optional[list[ToolSchema]] = None
    conversation_id:    Optional[str]        = None
    prompt_id:          Optional[str]        = None
    prompt_variables:   dict[str, str]       = {}
    cache_ttl:          Optional[int]        = None
    memory_enabled:     bool                 = False
    timeout:            float                = Field(60.0, ge=1.0, le=300.0)
    max_retries:        int                  = Field(2, ge=0, le=5)
    auto_execute_tools: bool                 = True


def _to_gateway_request(req: InferenceRequest) -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role=m.role, content=m.content) for m in req.messages],  # type: ignore[arg-type]
        provider=req.provider,
        model=req.model,
        fallback_providers=req.fallback_providers,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
        system=req.system,
        tools=req.tools,
        conversation_id=req.conversation_id,
        prompt_id=req.prompt_id,
        prompt_variables=req.prompt_variables,
        cache_ttl=req.cache_ttl,
        memory_enabled=req.memory_enabled,
        timeout=req.timeout,
        max_retries=req.max_retries,
    )


# ── Inference endpoints ───────────────────────────────────────────────────────


class AIChatRequest(BaseModel):
    """Simple single-turn request from the App Builder copilot (explain/debug).

    Intentionally minimal — mirrors exactly what AICopilotPanel.send() posts:
      { message, context?, app_name? }
    and returns { response } so the frontend needs no changes.
    """
    message:  str           = Field(..., min_length=1, max_length=8000)
    context:  Optional[str] = None
    app_name: Optional[str] = None


@router.post("/chat")
async def ai_chat(req: AIChatRequest, request: Request):
    """Single-turn AI chat for the App Builder copilot (explain / debug actions).

    Wraps the InferenceEngine in the same way /complete does, but with a
    simpler request model that matches what the frontend already sends.
    No conversation history — each call is stateless.
    """
    ai_rate_limit(request)
    uid = await _user_id(request)

    system_parts = ["أنت مساعد برمجة ذكي متخصص في تطبيقات Flow. أجب بإيجاز وعملية."]
    if req.context:
        system_parts.append(f"السياق: {req.context}")
    if req.app_name:
        system_parts.append(f"التطبيق: {req.app_name}")

    p = platform if platform._pool else platform.__class__(pool=_pool())
    completion_req = CompletionRequest(
        messages=[Message(role="user", content=req.message)],  # type: ignore[arg-type]
        system="\n".join(system_parts),
        max_tokens=1024,
        temperature=0.7,
    )
    resp = await p.complete(
        completion_req,
        user_id=uid,
        org_id=await _org_id(request),
        auto_tools=False,
    )
    return {"response": resp.content}


@router.post("/complete")
async def complete(req: InferenceRequest, request: Request):
    """Non-streaming AI completion. Delegates entirely to InferenceEngine."""
    ai_rate_limit(request)
    uid = await _user_id(request)
    await _require_conversation_ownership(req.conversation_id, uid)
    p = platform if platform._pool else platform.__class__(pool=_pool())
    resp = await p.complete(
        _to_gateway_request(req),
        user_id=uid,
        org_id=await _org_id(request),
        auto_tools=req.auto_execute_tools,
    )
    return {
        "id":              resp.id,
        "content":         resp.content,
        "tool_calls":      [tc.model_dump() for tc in resp.tool_calls],
        "finish_reason":   resp.finish_reason,
        "usage":           resp.usage.model_dump(),
        "conversation_id": resp.conversation_id,
        "cached":          resp.cached,
    }


@router.post("/stream")
async def stream(req: InferenceRequest, request: Request):
    """SSE streaming AI completion."""
    import json
    ai_rate_limit(request)
    # Resolved before the StreamingResponse starts, not inside event_stream()
    # — otherwise an unresolvable account surfaces as a buried SSE `error`
    # event under a 200 status instead of a clean 401.
    uid = await _user_id(request)
    # Resolved before the StreamingResponse starts, same reasoning as uid
    # above — a 404 here must be a clean HTTP 404, not a buried SSE `error`
    # event under a 200 status.
    await _require_conversation_ownership(req.conversation_id, uid)
    org_id = await _org_id(request)
    p = platform if platform._pool else platform.__class__(pool=_pool())

    async def event_stream():
        try:
            async for chunk in p.stream(
                _to_gateway_request(req),
                user_id=uid,
                org_id=org_id,
                auto_tools=req.auto_execute_tools,
            ):
                if isinstance(chunk, dict):
                    yield f"data: {json.dumps(chunk)}\n\n"
                else:
                    yield f"data: {chunk}\n\n"
        except Exception as exc:
            log.exception("Streaming error: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'error': 'An error occurred. Please try again.'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Conversations ─────────────────────────────────────────────────────────────

class ConvCreate(BaseModel):
    title:      str            = "New conversation"
    project_id: Optional[str] = None
    agent_id:   Optional[str] = None


@router.post("/conversations")
async def create_conversation(body: ConvCreate, request: Request):
    conv_svc = platform.conversations if platform._pool else \
               __import__("app.core.ai.services.conversation", fromlist=["ConversationService"]).ConversationService(_pool())
    cid = await conv_svc.create(
        user_id=await _user_id(request),
        title=body.title,
        project_id=body.project_id,
        agent_id=body.agent_id,
    )
    return {"id": cid, "title": body.title}


@router.get("/conversations")
async def list_conversations(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    from app.core.ai.services.conversation import ConversationService
    svc  = ConversationService(_pool())
    items = await svc.list(user_id=await _user_id(request), limit=limit, offset=offset)
    return [
        {
            "id":            c.id,
            "title":         c.title,
            "created_at":    c.created_at,
            "updated_at":    c.updated_at,
            "message_count": c.message_count,
        }
        for c in items
    ]


@router.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str, request: Request, page: int = 1, page_size: int = 50):
    from app.core.ai.services.conversation import ConversationService
    svc  = ConversationService(_pool())
    msgs = await svc.messages(conv_id, user_id=await _user_id(request), page=page, page_size=page_size)
    if msgs is None:
        raise HTTPException(404, "Conversation not found")
    return [
        {
            "id":           m.id,
            "role":         m.role,
            "content":      m.content,
            "tool_call_id": m.tool_call_id,
            "created_at":   m.created_at,
        }
        for m in msgs
    ]


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: str, request: Request):
    from app.core.ai.services.conversation import ConversationService
    deleted = await ConversationService(_pool()).delete(conv_id, user_id=await _user_id(request))
    if not deleted:
        raise HTTPException(404, "Conversation not found")


# ── Usage ─────────────────────────────────────────────────────────────────────

def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if not since:
        return None
    try:
        return datetime.fromisoformat(since)
    except ValueError:
        raise HTTPException(422, f"Invalid date format for 'since': {since!r}. Use ISO 8601.")


@router.get("/usage")
async def get_usage(request: Request, since: Optional[str] = None):
    from app.core.ai.telemetry.service import TelemetryService
    # Cheap, local validation before the DB-dependent identity resolution
    # below — since is now async (a real owner_user_id() DB call, not the
    # instant getattr() it used to be), so argument-evaluation order would
    # otherwise run it before this ever gets a chance to raise its 422.
    since_dt = _parse_since(since)
    uid = await _user_id(request)
    svc = TelemetryService(pool=_pool())
    return await svc.db_totals(user_id=uid, since=since_dt)


@router.get("/usage/providers")
async def get_usage_by_provider(request: Request, since: Optional[str] = None):
    from app.core.ai.telemetry.service import TelemetryService
    since_dt = _parse_since(since)
    uid = await _user_id(request)
    svc = TelemetryService(pool=_pool())
    return await svc.db_by_provider(user_id=uid, since=since_dt)


# ── Providers ─────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers():
    available = platform.registry.available()
    health    = platform.registry.health()
    return {
        "available": available,
        "default":   available[0] if available else None,
        "all":       [pid.value for pid in ProviderID],
        "health":    health,
    }


# ── Prompts ───────────────────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    name:          str
    slug:          str
    description:   str            = ""
    system:        Optional[str]  = None
    user_template: Optional[str]  = None
    variables:     Optional[list[str]] = None


class PromptVersionCreate(BaseModel):
    system:        Optional[str]  = None
    user_template: Optional[str]  = None
    variables:     Optional[list[str]] = None


class PromptPreviewRequest(BaseModel):
    variables: dict[str, str] = {}


@router.post("/prompts", status_code=201)
async def create_prompt(body: PromptCreate, request: Request):
    from app.core.ai.prompts.engine import PromptEngine
    engine = PromptEngine(_pool())
    pid = await engine.create(
        name=body.name, slug=body.slug, description=body.description,
        system=body.system, user_template=body.user_template,
        variables=body.variables, user_id=await _user_id(request),
    )
    return {"id": pid, "slug": body.slug}


@router.post("/prompts/{prompt_id}/versions", status_code=201)
async def publish_prompt_version(prompt_id: str, body: PromptVersionCreate, request: Request):
    from app.core.ai.prompts.engine import PromptEngine
    version = await PromptEngine(_pool()).publish_version(
        prompt_id, user_id=await _user_id(request), system=body.system,
        user_template=body.user_template, variables=body.variables,
    )
    if version is None:
        raise HTTPException(404, "Prompt not found")
    return {"prompt_id": prompt_id, "version": version}


@router.get("/prompts/{prompt_id}/versions")
async def list_prompt_versions(prompt_id: str, request: Request):
    from app.core.ai.prompts.engine import PromptEngine
    versions = await PromptEngine(_pool()).list_versions(prompt_id, user_id=await _user_id(request))
    return [v.model_dump() for v in versions]


@router.get("/prompts/{prompt_id}/active")
async def get_active_prompt_version(prompt_id: str, request: Request):
    from app.core.ai.prompts.engine import PromptEngine
    v = await PromptEngine(_pool()).get_active(prompt_id, user_id=await _user_id(request))
    if not v:
        raise HTTPException(404, "No active version found")
    return v.model_dump()


@router.post("/prompts/{prompt_id}/preview")
async def preview_prompt(prompt_id: str, body: PromptPreviewRequest, request: Request):
    from app.core.ai.prompts.engine import PromptEngine
    preview = await PromptEngine(_pool()).preview(
        prompt_id, variables=body.variables, user_id=await _user_id(request),
    )
    return {
        "system":        preview.system,
        "user_template": preview.user_template,
        "missing_vars":  preview.missing_vars,
        "extra_vars":    preview.extra_vars,
        "valid":         preview.valid,
    }


@router.post("/prompts/{prompt_id}/rollback/{version}")
async def rollback_prompt(prompt_id: str, version: int, request: Request):
    from app.core.ai.prompts.engine import PromptEngine
    new_version = await PromptEngine(_pool()).rollback(
        prompt_id, version, user_id=await _user_id(request),
    )
    if new_version is None:
        raise HTTPException(404, "Prompt or version not found")
    return {"prompt_id": prompt_id, "new_version": new_version}


# ── Memory ────────────────────────────────────────────────────────────────────

class MemoryCreate(BaseModel):
    content:         str
    importance:      float         = Field(1.0, ge=0.0, le=10.0)
    conversation_id: Optional[str] = None
    memory_type:     str           = "knowledge"


@router.post("/memory", status_code=201)
async def store_memory_item(body: MemoryCreate, request: Request):
    from app.core.ai.memory.manager import MemoryManager
    from app.core.ai.memory.types import MemoryType
    mid = await MemoryManager(_pool()).store(
        body.content,
        memory_type=MemoryType(body.memory_type),
        owner_id=await _user_id(request),
        conversation_id=body.conversation_id,
        importance=body.importance,
    )
    return {"id": mid}


@router.get("/memory")
async def recall_memory(request: Request, limit: int = 10):
    from app.core.ai.memory.manager import MemoryManager
    items = await MemoryManager(_pool()).recall(owner_id=await _user_id(request), limit=limit)
    return {"items": [{"id": i.id, "content": i.content, "importance": i.importance} for i in items]}


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_memory_item(memory_id: str, request: Request):
    from app.core.ai.memory.manager import MemoryManager
    deleted = await MemoryManager(_pool()).delete(memory_id, owner_id=await _user_id(request))
    if not deleted:
        raise HTTPException(404, "Memory item not found")


# ── Tools ─────────────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_tools():
    return [s.model_dump() for s in platform.tools.list_schemas()]


# ── Diagnostics ───────────────────────────────────────────────────────────────

@router.get("/diagnostics")
async def ai_diagnostics(include_db: bool = False):
    """Full AI platform observability report."""
    p = platform if platform._pool else platform.__class__(pool=_pool())
    return await p.diagnostics(include_db=include_db)


# ── Model catalog ─────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(provider: Optional[str] = None):
    """Return known models from the catalog."""
    from app.core.ai.models.catalog import catalog
    available = platform.registry.available()
    models = catalog.for_provider(provider) if provider else [
        m for m in catalog.all() if m.provider_id in available and not m.deprecated
    ]
    return [
        {
            "id":              m.id,
            "provider":        m.provider_id,
            "display_name":    m.display_name,
            "context_window":  m.context_window,
            "output_limit":    m.output_limit,
            "latency_tier":    m.latency_tier,
            "supports_tools":  m.supports_tools,
            "supports_vision": m.supports_vision,
            "reasoning":       m.reasoning,
            "input_cost_m":    m.input_cost_m,
            "output_cost_m":   m.output_cost_m,
        }
        for m in models
    ]
