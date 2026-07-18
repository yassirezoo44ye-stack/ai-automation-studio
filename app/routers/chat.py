import json
import uuid
from datetime import datetime
from typing import Optional

import anthropic
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import owner_user_id
from app.core.db import get_pool
from app.core.helpers import get_ai_client, resolve_project_id, anthropic_error_message
from app.core.org_quota import check_org_quota, record_org_tokens
from app.core.security import ai_rate_limit

router = APIRouter(tags=["chat"])


class RunRequest(BaseModel):
    project_id: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None


class ConversationCreate(BaseModel):
    project_id: str
    title: Optional[str] = "New conversation"


@router.post("/run/stream")
async def run_stream(req: RunRequest, request: Request):
    from app.core.reliability import get_bulkhead
    bulkhead = get_bulkhead("ai", 32)
    ai_rate_limit(request)
    org_id = await check_org_quota(request)
    ai = get_ai_client()

    history: list[dict] = []
    conv_id: Optional[uuid.UUID] = None

    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
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
                "SELECT role, content FROM messages WHERE conversation_id=$1 ORDER BY created_at",
                conv_id,
            )
            history = [{"role": r["role"], "content": r["content"]} for r in rows]
        else:
            pid = await resolve_project_id(conn, req.project_id, uid)
            conv_id = await conn.fetchval(
                "INSERT INTO conversations (project_id, title) VALUES ($1, $2) RETURNING id",
                pid, req.prompt[:60] + ("…" if len(req.prompt) > 60 else ""),
            )

        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'user', $2)",
            conv_id, req.prompt,
        )
        await conn.execute("UPDATE conversations SET updated_at=NOW() WHERE id=$1", conv_id)

    history.append({"role": "user", "content": req.prompt})

    async def event_stream():
        # The bulkhead slot is held for the whole stream — a StreamingResponse
        # returns from the handler immediately, so guarding only the handler
        # body would release the slot before any tokens flow.
        try:
            bulkhead_cm = bulkhead.acquire()
            await bulkhead_cm.__aenter__()
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Server is at capacity — please retry shortly.'})}\n\n"
            return
        full_text = ""
        try:
            with ai.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=history,
            ) as stream:
                yield f"data: {json.dumps({'type': 'conv_id', 'conv_id': str(conv_id)})}\n\n"
                for text in stream.text_stream:
                    full_text += text
                    yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
                try:
                    final = stream.get_final_message()
                    total_tokens = final.usage.input_tokens + final.usage.output_tokens
                    await record_org_tokens(org_id, total_tokens, str(conv_id))
                except Exception:
                    pass  # metering must never turn a successful reply into an error

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            try:
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'assistant', $2)",
                        conv_id, full_text,
                    )
                    await conn.execute("UPDATE conversations SET updated_at=NOW() WHERE id=$1", conv_id)
                    pid2 = await resolve_project_id(conn, req.project_id, uid)
                    run_id = await conn.fetchval(
                        "INSERT INTO agent_runs (project_id, agent_type, input_data, output_data, status, completed_at) "
                        "VALUES ($1,'claude',$2,$3,'completed',NOW()) RETURNING id",
                        pid2, json.dumps({"prompt": req.prompt}), json.dumps({"summary": full_text}),
                    )
                    await conn.execute(
                        "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'agent_run',$2)",
                        uid, json.dumps({"run_id": str(run_id), "prompt_preview": req.prompt[:80]}),
                    )
            except Exception:
                pass

        except anthropic.BadRequestError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': anthropic_error_message(e)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            await bulkhead_cm.__aexit__(None, None, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/run")
async def run_agent(req: RunRequest, request: Request):
    from app.core.reliability import get_bulkhead
    org_id = await check_org_quota(request)
    ai = get_ai_client()
    async with get_bulkhead("ai", 32).acquire():
        try:
            message = ai.messages.create(
                model="claude-sonnet-4-6", max_tokens=1024,
                messages=[{"role": "user", "content": req.prompt}],
            )
        except anthropic.AuthenticationError:
            raise HTTPException(401, "Invalid Anthropic API key.")
        except anthropic.BadRequestError as e:
            raise HTTPException(402, anthropic_error_message(e))
        except Exception as e:
            raise HTTPException(502, str(e))

    await record_org_tokens(
        org_id, message.usage.input_tokens + message.usage.output_tokens, req.project_id,
    )
    summary = message.content[0].text
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        pid = await resolve_project_id(conn, req.project_id, uid)
        run_id = await conn.fetchval(
            "INSERT INTO agent_runs (project_id, agent_type, input_data, output_data, status, completed_at) "
            "VALUES ($1,'claude',$2,$3,'completed',NOW()) RETURNING id",
            pid, json.dumps({"prompt": req.prompt}), json.dumps({"summary": summary}),
        )
        await conn.execute(
            "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'agent_run',$2)",
            uid, json.dumps({"run_id": str(run_id), "prompt_preview": req.prompt[:80]}),
        )
    return {"result": {"summary": summary}}


@router.post("/api/conversations")
async def create_conversation(body: ConversationCreate, request: Request):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        pid = await resolve_project_id(conn, body.project_id, uid)
        cid = await conn.fetchval(
            "INSERT INTO conversations (project_id, title) VALUES ($1,$2) RETURNING id",
            pid, body.title,
        )
    return {"id": str(cid), "title": body.title}


@router.get("/api/conversations")
async def list_conversations(request: Request, project_id: Optional[str] = None):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        if project_id:
            pid = await resolve_project_id(conn, project_id, uid)
            rows = await conn.fetch(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE project_id=$1 ORDER BY updated_at DESC",
                pid,
            )
        else:
            rows = await conn.fetch(
                "SELECT c.id, c.title, c.created_at, c.updated_at FROM conversations c "
                "JOIN projects p ON c.project_id=p.id WHERE p.user_id=$1 "
                "ORDER BY c.updated_at DESC LIMIT 50",
                uid,
            )
    return [{"id": str(r["id"]), "title": r["title"],
             "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()}
            for r in rows]


@router.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: str, request: Request):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        owned = await conn.fetchval(
            "SELECT 1 FROM conversations c JOIN projects p ON c.project_id=p.id "
            "WHERE c.id=$1 AND p.user_id=$2",
            uuid.UUID(conv_id), uid,
        )
        if not owned:
            raise HTTPException(404, "Conversation not found")
        rows = await conn.fetch(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id=$1 ORDER BY created_at",
            uuid.UUID(conv_id),
        )
    return [{"id": str(r["id"]), "role": r["role"], "content": r["content"],
             "created_at": r["created_at"].isoformat()} for r in rows]


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str, request: Request):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        result = await conn.execute(
            "DELETE FROM conversations c USING projects p "
            "WHERE c.project_id=p.id AND c.id=$1 AND p.user_id=$2",
            uuid.UUID(conv_id), uid,
        )
    if result == "DELETE 0":
        raise HTTPException(404, "Conversation not found")
    return {"message": "Deleted"}


@router.get("/api/search")
async def search(q: str, request: Request, project_id: Optional[str] = None):
    if not q or len(q) < 2:
        return {"conversations": [], "messages": []}
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        conv_rows = await conn.fetch(
            "SELECT c.id, c.title, c.updated_at FROM conversations c "
            "JOIN projects p ON c.project_id=p.id "
            "WHERE p.user_id=$1 AND c.title ILIKE $2 ORDER BY c.updated_at DESC LIMIT 10",
            uid, f"%{q}%",
        )
        msg_rows = await conn.fetch(
            "SELECT m.id, m.content, m.role, m.conversation_id, c.title "
            "FROM messages m JOIN conversations c ON m.conversation_id=c.id "
            "JOIN projects p ON c.project_id=p.id "
            "WHERE p.user_id=$1 AND m.content ILIKE $2 ORDER BY m.created_at DESC LIMIT 20",
            uid, f"%{q}%",
        )
    return {
        "conversations": [{"id": str(r["id"]), "title": r["title"],
                           "updated_at": r["updated_at"].isoformat()} for r in conv_rows],
        "messages": [{"id": str(r["id"]), "content": r["content"][:200], "role": r["role"],
                      "conversation_id": str(r["conversation_id"]), "conv_title": r["title"]}
                     for r in msg_rows],
    }


@router.get("/api/export/conversations/{conv_id}")
async def export_conversation(conv_id: str, request: Request):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        conv = await conn.fetchrow(
            "SELECT c.title, c.created_at FROM conversations c "
            "JOIN projects p ON c.project_id=p.id WHERE c.id=$1 AND p.user_id=$2",
            uuid.UUID(conv_id), uid,
        )
        if not conv:
            raise HTTPException(404, "Not found")
        msgs = await conn.fetch(
            "SELECT role, content, created_at FROM messages WHERE conversation_id=$1 ORDER BY created_at",
            uuid.UUID(conv_id),
        )
    lines = [f"# {conv['title']}", f"*Exported {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC*", ""]
    for m in msgs:
        lines.append(f"**{m['role'].upper()}**")
        lines.append(m["content"])
        lines.append("")
    md = "\n".join(lines)
    return Response(content=md, media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="conversation.md"'})
