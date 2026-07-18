import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import owner_user_id
from app.core.db import get_pool, ensure_agents_table
from app.core.helpers import get_ai_client, resolve_project_id
from app.core.org_quota import check_org_quota, record_org_tokens
from app.core.security import ai_rate_limit

router = APIRouter(tags=["agents"])


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    avatar: Optional[str] = "🤖"
    system_prompt: str = Field(..., min_length=1, max_length=8000)
    model: Optional[str] = "claude-sonnet-4-6"
    temperature: Optional[float] = 1.0
    description: Optional[str] = None
    project_id: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    description: Optional[str] = None


class AgentChatRequest(BaseModel):
    agent_id: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    project_id: Optional[str] = "demo"


@router.post("/api/agents")
async def create_agent(body: AgentCreate, request: Request):
    await ensure_agents_table()
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        pid = None
        if body.project_id and body.project_id != "demo":
            pid = await resolve_project_id(conn, body.project_id, uid)
        aid = await conn.fetchval(
            "INSERT INTO ai_agents (user_id,project_id,name,avatar,description,system_prompt,model,temperature) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id",
            uid, pid, body.name, body.avatar or "🤖",
            body.description, body.system_prompt, body.model or "claude-sonnet-4-6", body.temperature or 1.0,
        )
    return {"id": str(aid), "message": "Agent created"}


@router.get("/api/agents")
async def list_agents(request: Request):
    await ensure_agents_table()
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        rows = await conn.fetch(
            "SELECT id,name,avatar,description,system_prompt,model,temperature,message_count,created_at "
            "FROM ai_agents WHERE user_id=$1 ORDER BY created_at DESC",
            uid,
        )
    return [{"id": str(r["id"]), "name": r["name"], "avatar": r["avatar"],
             "description": r["description"], "system_prompt": r["system_prompt"],
             "model": r["model"], "temperature": r["temperature"],
             "message_count": r["message_count"],
             "created_at": r["created_at"].isoformat()} for r in rows]


@router.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str, request: Request):
    await ensure_agents_table()
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        r = await conn.fetchrow("SELECT * FROM ai_agents WHERE id=$1 AND user_id=$2", uuid.UUID(agent_id), uid)
    if not r:
        raise HTTPException(404, "Agent not found")
    return dict(r)


@router.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate, request: Request):
    await ensure_agents_table()
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        result = await conn.execute(
            "UPDATE ai_agents SET name=COALESCE($1,name), avatar=COALESCE($2,avatar), "
            "description=COALESCE($3,description), system_prompt=COALESCE($4,system_prompt), "
            "model=COALESCE($5,model), temperature=COALESCE($6,temperature), updated_at=NOW() "
            "WHERE id=$7 AND user_id=$8",
            body.name, body.avatar, body.description, body.system_prompt,
            body.model, body.temperature, uuid.UUID(agent_id), uid,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Agent not found")
    return {"message": "Updated"}


@router.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str, request: Request):
    await ensure_agents_table()
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        result = await conn.execute("DELETE FROM ai_agents WHERE id=$1 AND user_id=$2", uuid.UUID(agent_id), uid)
    if result == "DELETE 0":
        raise HTTPException(404, "Agent not found")
    return {"message": "Deleted"}


@router.post("/api/agents/{agent_id}/chat/stream")
async def agent_chat_stream(agent_id: str, req: AgentChatRequest, request: Request):
    ai_rate_limit(request)
    org_id = await check_org_quota(request)
    ai = get_ai_client()

    await ensure_agents_table()

    history: list[dict] = []
    conv_id: Optional[uuid.UUID] = None

    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        agent = await conn.fetchrow(
            "SELECT * FROM ai_agents WHERE id=$1 AND user_id=$2", uuid.UUID(agent_id), uid,
        )
        if not agent:
            raise HTTPException(404, "Agent not found")

        if req.conversation_id:
            try:
                conv_id = uuid.UUID(req.conversation_id)
            except ValueError:
                raise HTTPException(400, "Invalid conversation_id")
            owned = await conn.fetchval(
                "SELECT 1 FROM conversations c JOIN projects p ON c.project_id=p.id "
                "WHERE c.id=$1 AND p.user_id=$2",
                conv_id, uid,
            )
            if not owned:
                raise HTTPException(404, "Conversation not found")
            rows = await conn.fetch(
                "SELECT role, content FROM messages WHERE conversation_id=$1 ORDER BY created_at", conv_id)
            history = [{"role": r["role"], "content": r["content"]} for r in rows]
        else:
            pid = await resolve_project_id(conn, req.project_id, uid)
            conv_id = await conn.fetchval(
                "INSERT INTO conversations (project_id, title) VALUES ($1,$2) RETURNING id",
                pid, req.prompt[:60],
            )
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'user',$2)",
            conv_id, req.prompt,
        )
        await conn.execute("UPDATE conversations SET updated_at=NOW() WHERE id=$1", conv_id)

    history.append({"role": "user", "content": req.prompt})

    async def event_stream():
        full_text = ""
        try:
            with ai.messages.stream(
                model=agent["model"] or "claude-sonnet-4-6",
                max_tokens=2048,
                system=agent["system_prompt"],
                messages=history,
            ) as stream:
                yield f"data: {json.dumps({'type':'conv_id','conv_id':str(conv_id)})}\n\n"
                for text in stream.text_stream:
                    full_text += text
                    yield f"data: {json.dumps({'type':'delta','text':text})}\n\n"
                try:
                    final = stream.get_final_message()
                    total_tokens = final.usage.input_tokens + final.usage.output_tokens
                    await record_org_tokens(org_id, total_tokens, str(conv_id), ref_type="agents")
                except Exception:
                    pass  # metering must never turn a successful reply into an error

            yield f"data: {json.dumps({'type':'done'})}\n\n"

            try:
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'assistant',$2)",
                        conv_id, full_text,
                    )
                    await conn.execute("UPDATE conversations SET updated_at=NOW() WHERE id=$1", conv_id)
                    await conn.execute(
                        "UPDATE ai_agents SET message_count=message_count+1, updated_at=NOW() WHERE id=$1",
                        uuid.UUID(agent_id),
                    )
            except Exception:
                pass
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
