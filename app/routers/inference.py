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

from app.ai.models import (
    CompletionRequest, Message, ProviderID, ToolSchema,
)
from app.core.ai.platform import platform
from app.core.db import get_pool
from app.core.rate_limit import ai_rate_limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_id(request: Request) -> Optional[str]:
    return getattr(request.state, "user_id", None)


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

@router.post("/complete")
async def complete(req: InferenceRequest, request: Request):
    """Non-streaming AI completion. Delegates entirely to InferenceEngine."""
    ai_rate_limit(request)
    p = platform if platform._pool else platform.__class__(pool=_pool())
    resp = await p.complete(
        _to_gateway_request(req),
        user_id=_user_id(request),
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
    p = platform if platform._pool else platform.__class__(pool=_pool())

    async def event_stream():
        try:
            async for chunk in p.stream(
                _to_gateway_request(req),
                user_id=_user_id(request),
                org_id=await _org_id(request),
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
        user_id=_user_id(request),
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
    items = await svc.list(user_id=_user_id(request), limit=limit, offset=offset)
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
async def get_messages(conv_id: str, page: int = 1, page_size: int = 50):
    from app.core.ai.services.conversation import ConversationService
    svc  = ConversationService(_pool())
    msgs = await svc.messages(conv_id, page=page, page_size=page_size)
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
async def delete_conversation(conv_id: str):
    from app.core.ai.services.conversation import ConversationService
    await ConversationService(_pool()).delete(conv_id)


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
    svc = TelemetryService(pool=_pool())
    return await svc.db_totals(user_id=_user_id(request), since=_parse_since(since))


@router.get("/usage/providers")
async def get_usage_by_provider(request: Request, since: Optional[str] = None):
    from app.core.ai.telemetry.service import TelemetryService
    svc = TelemetryService(pool=_pool())
    return await svc.db_by_provider(user_id=_user_id(request), since=_parse_since(since))


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
        variables=body.variables, user_id=_user_id(request),
    )
    return {"id": pid, "slug": body.slug}


@router.post("/prompts/{prompt_id}/versions", status_code=201)
async def publish_prompt_version(prompt_id: str, body: PromptVersionCreate):
    from app.core.ai.prompts.engine import PromptEngine
    version = await PromptEngine(_pool()).publish_version(
        prompt_id, system=body.system,
        user_template=body.user_template, variables=body.variables,
    )
    return {"prompt_id": prompt_id, "version": version}


@router.get("/prompts/{prompt_id}/versions")
async def list_prompt_versions(prompt_id: str):
    from app.core.ai.prompts.engine import PromptEngine
    versions = await PromptEngine(_pool()).list_versions(prompt_id)
    return [v.model_dump() for v in versions]


@router.get("/prompts/{prompt_id}/active")
async def get_active_prompt_version(prompt_id: str):
    from app.core.ai.prompts.engine import PromptEngine
    v = await PromptEngine(_pool()).get_active(prompt_id)
    if not v:
        raise HTTPException(404, "No active version found")
    return v.model_dump()


@router.post("/prompts/{prompt_id}/preview")
async def preview_prompt(prompt_id: str, body: PromptPreviewRequest):
    from app.core.ai.prompts.engine import PromptEngine
    preview = await PromptEngine(_pool()).preview(prompt_id, variables=body.variables)
    return {
        "system":        preview.system,
        "user_template": preview.user_template,
        "missing_vars":  preview.missing_vars,
        "extra_vars":    preview.extra_vars,
        "valid":         preview.valid,
    }


@router.post("/prompts/{prompt_id}/rollback/{version}")
async def rollback_prompt(prompt_id: str, version: int):
    from app.core.ai.prompts.engine import PromptEngine
    new_version = await PromptEngine(_pool()).rollback(prompt_id, version)
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
        owner_id=_user_id(request),
        conversation_id=body.conversation_id,
        importance=body.importance,
    )
    return {"id": mid}


@router.get("/memory")
async def recall_memory(request: Request, limit: int = 10):
    from app.core.ai.memory.manager import MemoryManager
    items = await MemoryManager(_pool()).recall(owner_id=_user_id(request), limit=limit)
    return {"items": [{"id": i.id, "content": i.content, "importance": i.importance} for i in items]}


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_memory_item(memory_id: str):
    from app.core.ai.memory.manager import MemoryManager
    await MemoryManager(_pool()).delete(memory_id)


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
