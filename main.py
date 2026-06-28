from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncpg
import os
import json
import subprocess
import shutil
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import uuid
import anthropic

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ai_user:aiStudio2026!@127.0.0.1:5432/ai_studio")
WORKSPACES   = Path(os.getenv("WORKSPACES_DIR", "./workspaces"))

pool: asyncpg.Pool = None


# ── Models ────────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

class AgentRunCreate(BaseModel):
    project_id: str
    agent_type: str = Field(..., min_length=1, max_length=50)
    input_data: dict

class RunRequest(BaseModel):
    project_id: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None

class ConversationCreate(BaseModel):
    project_id: str
    title: Optional[str] = "New conversation"

class MessageCreate(BaseModel):
    conversation_id: str
    role: str
    content: str


# ── DB init ───────────────────────────────────────────────────────────────────

async def init_db(conn: asyncpg.Connection):
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            status VARCHAR(50) DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL DEFAULT 'New conversation',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS agent_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            agent_type VARCHAR(50) NOT NULL,
            input_data JSONB,
            output_data JSONB,
            status VARCHAR(50) DEFAULT 'pending',
            started_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            error_message TEXT
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS usage_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action VARCHAR(100) NOT NULL,
            details JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    # Seed test user
    test_uid = uuid.UUID("00000000-0000-0000-0000-000000000000")
    await conn.execute('''
        INSERT INTO users (id, email, name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING
    ''', test_uid, "test@example.com", "Test User")
    # Seed demo project
    demo_pid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    await conn.execute('''
        INSERT INTO projects (id, user_id, name, description) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING
    ''', demo_pid, test_uid, "Demo Project", "Default project for the chat UI")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        await init_db(conn)
    # Ensure agents table exists (merged here to avoid on_event race)
    await ensure_agents_table()
    yield
    await pool.close()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="AI Automation Studio", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


# ── Static Frontend ───────────────────────────────────────────────────────────

DIST = Path(__file__).parent / "dist"
if DIST.exists():
    # Mount /assets for JS/CSS chunks
    if (DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

@app.get("/", response_class=HTMLResponse)
async def root():
    index = DIST / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>◈ AI Automation Studio — Backend Running</h1><p><a href='/docs'>API Docs</a></p>")

@app.get("/manifest.json")
async def serve_manifest():
    f = DIST / "manifest.json"
    if not f.exists():
        f = Path(__file__).parent / "public" / "manifest.json"
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text(encoding="utf-8"), media_type="application/manifest+json")

@app.get("/sw.js")
async def serve_sw():
    f = DIST / "sw.js"
    if not f.exists():
        f = Path(__file__).parent / "public" / "sw.js"
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text(encoding="utf-8"), media_type="application/javascript")

@app.get("/icon-{size}.png")
async def serve_icon(size: str):
    if size not in ("192", "512"):
        raise HTTPException(404)
    f = DIST / f"icon-{size}.png"
    if not f.exists():
        f = Path(__file__).parent / "public" / f"icon-{size}.png"
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_bytes(), media_type="image/png")

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    async with pool.acquire() as conn:
        pg_version = await conn.fetchval("SELECT version()")
    return {"status": "healthy", "db": "postgresql", "pg_version": pg_version,
            "timestamp": datetime.utcnow().isoformat()}


# ── Streaming run ─────────────────────────────────────────────────────────────

@app.post("/run/stream")
async def run_stream(req: RunRequest):
    """Stream Claude's response token by token using SSE."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")

    # Build message history if conversation_id provided
    history: list[dict] = []
    conv_id: Optional[uuid.UUID] = None

    async with pool.acquire() as conn:
        if req.conversation_id:
            try:
                conv_id = uuid.UUID(req.conversation_id)
                rows = await conn.fetch(
                    "SELECT role, content FROM messages WHERE conversation_id=$1 ORDER BY created_at",
                    conv_id,
                )
                history = [{"role": r["role"], "content": r["content"]} for r in rows]
            except Exception:
                pass
        else:
            # Create new conversation
            pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if req.project_id == "demo" else uuid.UUID(req.project_id)
            conv_id = await conn.fetchval(
                "INSERT INTO conversations (project_id, title) VALUES ($1, $2) RETURNING id",
                pid, req.prompt[:60] + ("…" if len(req.prompt) > 60 else ""),
            )

        # Save user message
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'user', $2)",
            conv_id, req.prompt,
        )
        await conn.execute(
            "UPDATE conversations SET updated_at=NOW() WHERE id=$1", conv_id,
        )

    history.append({"role": "user", "content": req.prompt})

    async def event_stream():
        ai = anthropic.Anthropic(api_key=api_key)
        full_text = ""
        try:
            with ai.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=history,
            ) as stream:
                # First send the conversation_id so the client can track it
                yield f"data: {json.dumps({'type': 'conv_id', 'conv_id': str(conv_id)})}\n\n"
                for text in stream.text_stream:
                    full_text += text
                    yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"

            # Save assistant message
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'assistant', $2)",
                    conv_id, full_text,
                )
                await conn.execute(
                    "UPDATE conversations SET updated_at=NOW() WHERE id=$1", conv_id,
                )
                pid2 = uuid.UUID("00000000-0000-0000-0000-000000000001") if req.project_id == "demo" else uuid.UUID(req.project_id)
                run_id = await conn.fetchval(
                    "INSERT INTO agent_runs (project_id, agent_type, input_data, output_data, status, completed_at) "
                    "VALUES ($1,'claude',$2,$3,'completed',NOW()) RETURNING id",
                    pid2, json.dumps({"prompt": req.prompt}), json.dumps({"summary": full_text}),
                )
                await conn.execute(
                    "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'agent_run',$2)",
                    USER_ID, json.dumps({"run_id": str(run_id), "prompt_preview": req.prompt[:80]}),
                )
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except anthropic.BadRequestError as e:
            body = e.body if hasattr(e, 'body') and e.body else {}
            msg = body.get('error', {}).get('message', str(e)) if isinstance(body, dict) else str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Non-streaming run (kept for compatibility) ────────────────────────────────

@app.post("/run")
async def run_agent(req: RunRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")
    try:
        ai = anthropic.Anthropic(api_key=api_key)
        message = ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024,
            messages=[{"role": "user", "content": req.prompt}],
        )
    except anthropic.AuthenticationError:
        raise HTTPException(401, "Invalid Anthropic API key.")
    except anthropic.BadRequestError as e:
        body = e.body if hasattr(e, 'body') and e.body else {}
        msg = body.get('error', {}).get('message', str(e)) if isinstance(body, dict) else str(e)
        raise HTTPException(402, msg)
    except Exception as e:
        raise HTTPException(502, str(e))

    summary = message.content[0].text
    pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if req.project_id == "demo" else uuid.UUID(req.project_id)
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            "INSERT INTO agent_runs (project_id, agent_type, input_data, output_data, status, completed_at) "
            "VALUES ($1,'claude',$2,$3,'completed',NOW()) RETURNING id",
            pid, json.dumps({"prompt": req.prompt}), json.dumps({"summary": summary}),
        )
        await conn.execute(
            "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'agent_run',$2)",
            USER_ID, json.dumps({"run_id": str(run_id), "prompt_preview": req.prompt[:80]}),
        )
    return {"result": {"summary": summary}}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    async with pool.acquire() as conn:
        project_count = await conn.fetchval("SELECT COUNT(*) FROM projects")
        run_count     = await conn.fetchval("SELECT COUNT(*) FROM agent_runs")
        completed     = await conn.fetchval("SELECT COUNT(*) FROM agent_runs WHERE status='completed'")
        conv_count    = await conn.fetchval("SELECT COUNT(*) FROM conversations")
        msg_count     = await conn.fetchval("SELECT COUNT(*) FROM messages")
        logs          = await conn.fetch(
            "SELECT action, details, created_at FROM usage_logs ORDER BY created_at DESC LIMIT 10"
        )
    return {
        "projects":       int(project_count),
        "agent_runs":     int(run_count),
        "completed_runs": int(completed),
        "conversations":  int(conv_count),
        "messages":       int(msg_count),
        "success_rate":   round(int(completed) / max(int(run_count), 1) * 100, 1),
        "recent_activity": [
            {
                "action": r["action"],
                "details": (json.loads(r["details"]) if isinstance(r["details"], str) else (dict(r["details"]) if r["details"] else {})),
                "time": r["created_at"].isoformat()
            }
            for r in logs
        ],
    }


# ── Conversations ─────────────────────────────────────────────────────────────

@app.post("/api/conversations")
async def create_conversation(body: ConversationCreate):
    pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if body.project_id == "demo" else uuid.UUID(body.project_id)
    async with pool.acquire() as conn:
        cid = await conn.fetchval(
            "INSERT INTO conversations (project_id, title) VALUES ($1,$2) RETURNING id",
            pid, body.title,
        )
    return {"id": str(cid), "title": body.title}

@app.get("/api/conversations")
async def list_conversations(project_id: Optional[str] = None):
    async with pool.acquire() as conn:
        if project_id:
            pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if project_id == "demo" else uuid.UUID(project_id)
            rows = await conn.fetch(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE project_id=$1 ORDER BY updated_at DESC",
                pid,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 50"
            )
    return [{"id": str(r["id"]), "title": r["title"],
             "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()} for r in rows]

@app.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: str):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id=$1 ORDER BY created_at",
            uuid.UUID(conv_id),
        )
    return [{"id": str(r["id"]), "role": r["role"], "content": r["content"],
             "created_at": r["created_at"].isoformat()} for r in rows]

@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM conversations WHERE id=$1", uuid.UUID(conv_id))
    return {"message": "Deleted"}


# ── Projects ──────────────────────────────────────────────────────────────────

@app.post("/api/projects")
async def create_project(project: ProjectCreate):
    async with pool.acquire() as conn:
        pid = await conn.fetchval(
            "INSERT INTO projects (user_id, name, description) VALUES ($1,$2,$3) RETURNING id",
            USER_ID, project.name, project.description,
        )
    return {"id": str(pid), "message": "Project created"}

@app.get("/api/projects")
async def list_projects():
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, description, status, created_at, updated_at FROM projects ORDER BY created_at DESC"
        )
    return [{"id": str(r["id"]), "name": r["name"], "description": r["description"],
             "status": r["status"], "created_at": r["created_at"].isoformat(),
             "updated_at": r["updated_at"].isoformat()} for r in rows]

@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, description, status, created_at, updated_at FROM projects WHERE id=$1",
            uuid.UUID(project_id),
        )
    if not row:
        raise HTTPException(404, "Project not found")
    return {"id": str(row["id"]), "name": row["name"], "description": row["description"],
            "status": row["status"], "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat()}

@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, project: ProjectUpdate):
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE projects SET name=COALESCE($1,name), description=COALESCE($2,description), updated_at=NOW() WHERE id=$3",
            project.name, project.description, uuid.UUID(project_id),
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Project not found")
    return {"message": "Updated"}

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM projects WHERE id=$1", uuid.UUID(project_id))
    return {"message": "Deleted"}


# ── Agent runs ────────────────────────────────────────────────────────────────

@app.get("/api/agent-runs")
async def list_agent_runs(project_id: Optional[str] = None):
    async with pool.acquire() as conn:
        if project_id:
            rows = await conn.fetch(
                "SELECT id,project_id,agent_type,status,started_at,completed_at FROM agent_runs WHERE project_id=$1 ORDER BY started_at DESC",
                uuid.UUID(project_id),
            )
        else:
            rows = await conn.fetch(
                "SELECT id,project_id,agent_type,status,started_at,completed_at FROM agent_runs ORDER BY started_at DESC"
            )
    return [{"id": str(r["id"]), "project_id": str(r["project_id"]), "agent_type": r["agent_type"],
             "status": r["status"], "started_at": r["started_at"].isoformat(),
             "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None} for r in rows]

@app.get("/api/usage-logs")
async def list_usage_logs():
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, action, details, created_at FROM usage_logs ORDER BY created_at DESC LIMIT 100"
        )
    return [{"id": str(r["id"]), "action": r["action"],
             "details": dict(r["details"]) if r["details"] else {},
             "created_at": r["created_at"].isoformat()} for r in rows]


# ── Builder ───────────────────────────────────────────────────────────────────

WORKSPACES.mkdir(exist_ok=True)

BUILD_SYSTEM = """You are an expert software engineer and code generator.
When the user asks you to build something, respond ONLY with a valid JSON object (no markdown, no explanation outside the JSON).

JSON schema:
{
  "description": "Short description of what was built",
  "files": [
    {"path": "relative/path/to/file.ext", "content": "full file content as string"}
  ],
  "run_command": "command to run the program (e.g. python main.py)",
  "language": "primary language (python, javascript, html, etc.)"
}

Rules:
- Always include a README.md explaining how to use the program
- Use relative paths only, never absolute
- Make programs self-contained and runnable
- For Python: include a requirements.txt if needed
- For web apps: use a single index.html with embedded CSS/JS
- Write clean, working, production-quality code
"""

class BuildRequest(BaseModel):
    project_id: str
    prompt: str = Field(..., min_length=1, max_length=2000)

class RunRequest2(BaseModel):
    project_id: str
    command: Optional[str] = None

class FileWrite(BaseModel):
    path: str
    content: str

def workspace(project_id: str) -> Path:
    # Guard against path traversal (e.g. project_id = "../../etc")
    ws = (WORKSPACES / project_id).resolve()
    if not str(ws).startswith(str(WORKSPACES.resolve())):
        raise HTTPException(400, "Invalid project_id")
    ws.mkdir(parents=True, exist_ok=True)
    return ws

def safe_path(ws: Path, rel: str) -> Path:
    """Ensure path stays inside workspace."""
    p = (ws / rel).resolve()
    if not str(p).startswith(str(ws.resolve())):
        raise HTTPException(400, "Invalid path")
    return p


@app.post("/api/build")
async def build_program(req: BuildRequest):
    """Ask Claude to build a program, write all files, return the result."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")

    try:
        ai = anthropic.Anthropic(api_key=api_key)
        msg = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            system=BUILD_SYSTEM,
            messages=[{"role": "user", "content": req.prompt}],
        )
    except anthropic.BadRequestError as e:
        body = e.body if hasattr(e, "body") and e.body else {}
        detail = body.get("error", {}).get("message", str(e)) if isinstance(body, dict) else str(e)
        raise HTTPException(402, detail)
    except Exception as e:
        raise HTTPException(502, str(e))

    raw = msg.content[0].text.strip()
    # Strip markdown fences if Claude added them
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(502, f"Claude returned non-JSON: {raw[:200]}")

    ws = workspace(req.project_id)
    written = []
    for f in result.get("files", []):
        dest = safe_path(ws, f["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f["content"], encoding="utf-8")
        written.append(f["path"])

    # Log to DB
    async with pool.acquire() as conn:
        pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if req.project_id == "demo" else uuid.UUID(req.project_id)
        await conn.execute(
            "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'build',$2)",
            USER_ID, json.dumps({"prompt": req.prompt[:80], "files": written, "project_id": req.project_id}),
        )

    return {
        "description": result.get("description", ""),
        "files": written,
        "run_command": result.get("run_command", ""),
        "language": result.get("language", ""),
        "workspace": str(ws),
    }


@app.post("/api/build/stream")
async def build_stream(req: BuildRequest):
    """Stream the build progress via SSE."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")

    async def event_stream():
        try:
            ai = anthropic.Anthropic(api_key=api_key)
            yield f"data: {json.dumps({'type':'status','message':'🤖 Thinking…'})}\n\n"

            # Collect full response (build needs complete JSON)
            msg = ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8096,
                system=BUILD_SYSTEM,
                messages=[{"role": "user", "content": req.prompt}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:])
                if raw.endswith("```"):
                    raw = raw[:-3].strip()

            result = json.loads(raw)
            n = len(result.get("files", []))
            yield f"data: {json.dumps({'type':'status','message':f'Writing {n} files…'})}\n\n"

            ws = workspace(req.project_id)
            written = []
            for f in result.get("files", []):
                dest = safe_path(ws, f["path"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(f["content"], encoding="utf-8")
                written.append(f["path"])
                yield f"data: {json.dumps({'type':'file','path':f['path'],'content':f['content']})}\n\n"
                await asyncio.sleep(0.05)

            async with pool.acquire() as conn:
                pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if req.project_id == "demo" else uuid.UUID(req.project_id)
                await conn.execute(
                    "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'build',$2)",
                    USER_ID, json.dumps({"prompt": req.prompt[:80], "files": written}),
                )

            yield f"data: {json.dumps({'type':'done','description':result.get('description',''),'files':written,'run_command':result.get('run_command',''),'language':result.get('language','')})}\n\n"

        except anthropic.BadRequestError as e:
            body = e.body if hasattr(e, "body") and e.body else {}
            msg2 = body.get("error", {}).get("message", str(e)) if isinstance(body, dict) else str(e)
            yield f"data: {json.dumps({'type':'error','message':msg2})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/projects/{project_id}/files")
async def list_files(project_id: str):
    ws = workspace(project_id)
    files = []
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(ws)).replace("\\", "/")
            files.append({"path": rel, "size": p.stat().st_size})
    return {"files": files, "workspace": str(ws)}


@app.get("/api/projects/{project_id}/files/{file_path:path}")
async def read_file(project_id: str, file_path: str):
    ws = workspace(project_id)
    dest = safe_path(ws, file_path)
    if not dest.exists():
        raise HTTPException(404, "File not found")
    try:
        content = dest.read_text(encoding="utf-8")
    except Exception:
        content = "<binary file>"
    return {"path": file_path, "content": content}


@app.post("/api/projects/{project_id}/upload")
async def upload_files(project_id: str, files: list[UploadFile]):
    """Upload one or more files into a project workspace."""
    ws = workspace(project_id)
    saved = []
    for uf in files:
        safe_name = Path(uf.filename).name  # strip any directory component
        dest = safe_path(ws, safe_name)
        content = await uf.read()
        dest.write_bytes(content)
        saved.append({"path": safe_name, "size": len(content)})
    return {"saved": saved, "count": len(saved)}


@app.delete("/api/projects/{project_id}/files")
async def clear_workspace(project_id: str):
    ws = workspace(project_id)
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)
    return {"message": "Workspace cleared"}


@app.post("/api/projects/{project_id}/run")
async def run_project(project_id: str, body: RunRequest2):
    ws = workspace(project_id)
    raw_command = (body.command or "python main.py").strip()

    # Allowlist: only permit safe interpreter invocations
    # Format: "python <script.py> [args]" or "node <script.js> [args]"
    ALLOWED_INTERPRETERS = ("python", "python3", "node", "npm run")
    if not any(raw_command.startswith(p) for p in ALLOWED_INTERPRETERS):
        raise HTTPException(400, "Only python/node commands are allowed.")

    # Reject shell metacharacters (prevent injection even without shell=True)
    SHELL_CHARS = (";", "&", "|", ">", "<", "`", "$", "(", ")", "{", "}")
    if any(c in raw_command for c in SHELL_CHARS):
        raise HTTPException(400, "Shell metacharacters are not allowed.")

    import shlex
    args = shlex.split(raw_command)

    try:
        proc = subprocess.run(
            args, shell=False, cwd=str(ws),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "command": raw_command,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "Execution timed out after 30 seconds.")
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Custom Agents ─────────────────────────────────────────────────────────────

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


async def ensure_agents_table():
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_agents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
                name VARCHAR(100) NOT NULL,
                avatar VARCHAR(10) DEFAULT '🤖',
                description TEXT,
                system_prompt TEXT NOT NULL,
                model VARCHAR(80) DEFAULT 'claude-sonnet-4-6',
                temperature FLOAT DEFAULT 1.0,
                message_count INT DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        ''')


# NOTE: ensure_agents_table() is now called inside lifespan (above)
# Keeping this stub to avoid breaking any imports, but it's a no-op.
async def _on_startup_stub():
    pass


@app.post("/api/agents")
async def create_agent(body: AgentCreate):
    await ensure_agents_table()
    pid = None
    if body.project_id and body.project_id != "demo":
        try: pid = uuid.UUID(body.project_id)
        except: pass
    async with pool.acquire() as conn:
        aid = await conn.fetchval(
            "INSERT INTO ai_agents (user_id,project_id,name,avatar,description,system_prompt,model,temperature) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id",
            USER_ID, pid, body.name, body.avatar or "🤖",
            body.description, body.system_prompt, body.model or "claude-sonnet-4-6", body.temperature or 1.0,
        )
    return {"id": str(aid), "message": "Agent created"}


@app.get("/api/agents")
async def list_agents():
    await ensure_agents_table()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id,name,avatar,description,system_prompt,model,temperature,message_count,created_at "
            "FROM ai_agents WHERE user_id=$1 ORDER BY created_at DESC",
            USER_ID,
        )
    return [{"id": str(r["id"]), "name": r["name"], "avatar": r["avatar"],
             "description": r["description"], "system_prompt": r["system_prompt"],
             "model": r["model"], "temperature": r["temperature"],
             "message_count": r["message_count"],
             "created_at": r["created_at"].isoformat()} for r in rows]


@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str):
    await ensure_agents_table()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_agents WHERE id=$1", uuid.UUID(agent_id))
    if not r:
        raise HTTPException(404, "Agent not found")
    return dict(r)


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate):
    await ensure_agents_table()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ai_agents SET name=COALESCE($1,name), avatar=COALESCE($2,avatar), "
            "description=COALESCE($3,description), system_prompt=COALESCE($4,system_prompt), "
            "model=COALESCE($5,model), temperature=COALESCE($6,temperature), updated_at=NOW() WHERE id=$7",
            body.name, body.avatar, body.description, body.system_prompt,
            body.model, body.temperature, uuid.UUID(agent_id),
        )
    return {"message": "Updated"}


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    await ensure_agents_table()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ai_agents WHERE id=$1", uuid.UUID(agent_id))
    return {"message": "Deleted"}


# ── Chat with custom agent ─────────────────────────────────────────────────────

class AgentChatRequest(BaseModel):
    agent_id: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    project_id: Optional[str] = "demo"


@app.post("/api/agents/{agent_id}/chat/stream")
async def agent_chat_stream(agent_id: str, req: AgentChatRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")

    await ensure_agents_table()
    async with pool.acquire() as conn:
        agent = await conn.fetchrow("SELECT * FROM ai_agents WHERE id=$1", uuid.UUID(agent_id))
    if not agent:
        raise HTTPException(404, "Agent not found")

    history: list[dict] = []
    conv_id: Optional[uuid.UUID] = None

    async with pool.acquire() as conn:
        if req.conversation_id:
            try:
                conv_id = uuid.UUID(req.conversation_id)
                rows = await conn.fetch(
                    "SELECT role, content FROM messages WHERE conversation_id=$1 ORDER BY created_at", conv_id)
                history = [{"role": r["role"], "content": r["content"]} for r in rows]
            except Exception:
                pass
        else:
            pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if req.project_id == "demo" else uuid.UUID(req.project_id or "00000000-0000-0000-0000-000000000001")
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
        ai_client = anthropic.Anthropic(api_key=api_key)
        full_text = ""
        try:
            with ai_client.messages.stream(
                model=agent["model"] or "claude-sonnet-4-6",
                max_tokens=2048,
                system=agent["system_prompt"],
                messages=history,
            ) as stream:
                yield f"data: {json.dumps({'type':'conv_id','conv_id':str(conv_id)})}\n\n"
                for text in stream.text_stream:
                    full_text += text
                    yield f"data: {json.dumps({'type':'delta','text':text})}\n\n"

            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'assistant',$2)",
                    conv_id, full_text,
                )
                await conn.execute("UPDATE conversations SET updated_at=NOW() WHERE id=$1", conv_id)
                await conn.execute(
                    "UPDATE ai_agents SET message_count=message_count+1, updated_at=NOW() WHERE id=$1",
                    uuid.UUID(agent_id),
                )
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
async def search(q: str, project_id: Optional[str] = None):
    if not q or len(q) < 2:
        return {"conversations": [], "messages": []}
    async with pool.acquire() as conn:
        conv_rows = await conn.fetch(
            "SELECT id, title, updated_at FROM conversations WHERE title ILIKE $1 ORDER BY updated_at DESC LIMIT 10",
            f"%{q}%",
        )
        msg_rows = await conn.fetch(
            "SELECT m.id, m.content, m.role, m.conversation_id, c.title "
            "FROM messages m JOIN conversations c ON m.conversation_id=c.id "
            "WHERE m.content ILIKE $1 ORDER BY m.created_at DESC LIMIT 20",
            f"%{q}%",
        )
    return {
        "conversations": [{"id": str(r["id"]), "title": r["title"], "updated_at": r["updated_at"].isoformat()} for r in conv_rows],
        "messages": [{"id": str(r["id"]), "content": r["content"][:200], "role": r["role"],
                      "conversation_id": str(r["conversation_id"]), "conv_title": r["title"]} for r in msg_rows],
    }


# ── Export ────────────────────────────────────────────────────────────────────

@app.get("/api/export/conversations/{conv_id}")
async def export_conversation(conv_id: str):
    async with pool.acquire() as conn:
        conv = await conn.fetchrow("SELECT title, created_at FROM conversations WHERE id=$1", uuid.UUID(conv_id))
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
    from fastapi.responses import Response
    return Response(content=md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="conversation.md"'})


# ── Stats with timeseries ─────────────────────────────────────────────────────

@app.get("/api/stats/timeseries")
async def stats_timeseries(days: int = 14):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DATE(created_at) as day, COUNT(*) as count "
            "FROM messages WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL "
            "GROUP BY day ORDER BY day",
            str(days),
        )
        build_rows = await conn.fetch(
            "SELECT DATE(created_at) as day, COUNT(*) as count "
            "FROM usage_logs WHERE action='build' AND created_at >= NOW() - ($1 || ' days')::INTERVAL "
            "GROUP BY day ORDER BY day",
            str(days),
        )
    msg_map   = {str(r["day"]): int(r["count"]) for r in rows}
    build_map = {str(r["day"]): int(r["count"]) for r in build_rows}

    from datetime import timedelta, date
    labels, msgs, builds = [], [], []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        labels.append(d[5:])  # MM-DD
        msgs.append(msg_map.get(d, 0))
        builds.append(build_map.get(d, 0))
    return {"labels": labels, "messages": msgs, "builds": builds}


# ── YouTube ───────────────────────────────────────────────────────────────────

class YoutubeRequest(BaseModel):
    url: str

class YoutubeAskRequest(BaseModel):
    url: str
    question: str
    transcript: Optional[str] = None

def extract_video_id(url: str) -> Optional[str]:
    import re
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

@app.post("/api/youtube/info")
async def youtube_info(req: YoutubeRequest):
    vid = extract_video_id(req.url)
    if not vid:
        raise HTTPException(400, "Invalid YouTube URL")
    try:
        import yt_dlp
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        return {
            "video_id": vid,
            "title":       info.get("title", ""),
            "channel":     info.get("uploader", ""),
            "duration":    info.get("duration", 0),
            "view_count":  info.get("view_count", 0),
            "like_count":  info.get("like_count", 0),
            "description": (info.get("description") or "")[:800],
            "thumbnail":   info.get("thumbnail", ""),
            "upload_date": info.get("upload_date", ""),
            "tags":        (info.get("tags") or [])[:10],
        }
    except Exception as e:
        raise HTTPException(502, f"Could not fetch video info: {e}")


@app.post("/api/youtube/transcript")
async def youtube_transcript(req: YoutubeRequest):
    vid = extract_video_id(req.url)
    if not vid:
        raise HTTPException(400, "Invalid YouTube URL")
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(vid)
            # prefer manual, fallback to auto, then any
            try:
                t = transcript_list.find_manually_created_transcript(["ar", "en"])
            except Exception:
                try:
                    t = transcript_list.find_generated_transcript(["ar", "en"])
                except Exception:
                    t = next(iter(transcript_list))
            entries = t.fetch()
            text = " ".join(e.text for e in entries)
            return {"video_id": vid, "language": t.language_code, "transcript": text, "length": len(text)}
        except (NoTranscriptFound, TranscriptsDisabled):
            raise HTTPException(404, "No transcript available for this video.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


@app.post("/api/youtube/analyze/stream")
async def youtube_analyze_stream(req: YoutubeAskRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")

    transcript = req.transcript or ""
    system = (
        "You are a YouTube video analyst. You are given the transcript of a video and a user question. "
        "Answer thoughtfully using the transcript content. If summarizing, include key points with bullet points. "
        "If the transcript is empty, say so and answer from general knowledge."
    )
    user_msg = f"VIDEO TRANSCRIPT:\n{transcript[:6000]}\n\n---\nQUESTION: {req.question}"

    async def event_stream():
        ai_client = anthropic.Anthropic(api_key=api_key)
        try:
            with ai_client.messages.stream(
                model="claude-sonnet-4-6", max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Social Media (Facebook / Instagram / Twitter) ─────────────────────────────

class SocialRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    platform: str = "facebook"          # facebook | instagram | twitter | linkedin
    content_type: str = "post"          # post | ad | story | reel_caption | thread
    tone: str = "engaging"              # engaging | professional | funny | inspirational | urgent
    language: str = "arabic"            # arabic | english | both
    include_hashtags: bool = True
    include_emoji: bool = True
    variations: int = 3


SOCIAL_SYSTEM = """You are an expert social media content creator specializing in Arabic and English content.
Create highly engaging, platform-optimized content. Follow these rules:
- Match the tone perfectly
- Use platform best practices (Facebook: longer narrative; Instagram: visual-focused; Twitter: punchy)
- Arabic content should feel natural, not translated
- Return ONLY a JSON array of variation objects: [{"text": "...", "hashtags": [...], "tip": "..."}]
- No markdown fences, just raw JSON array
"""

@app.post("/api/social/generate/stream")
async def social_generate_stream(req: SocialRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")

    lang_instruction = {
        "arabic": "Write ONLY in Arabic (العربية).",
        "english": "Write ONLY in English.",
        "both": "Write a bilingual version: Arabic first, then English translation.",
    }.get(req.language, "Write in Arabic.")

    platform_tips = {
        "facebook": "Facebook posts: 150-300 words, storytelling format, call to action at end",
        "instagram": "Instagram: 3-5 punchy lines + strong call to action, visual description hint",
        "twitter": "Twitter/X: under 280 chars each, punchy and direct",
        "linkedin": "LinkedIn: professional, value-driven, thought leadership style",
    }.get(req.platform, "")

    user_msg = (
        f"Platform: {req.platform.upper()}\n"
        f"Content type: {req.content_type}\n"
        f"Tone: {req.tone}\n"
        f"Language: {lang_instruction}\n"
        f"Include hashtags: {req.include_hashtags}\n"
        f"Include emojis: {req.include_emoji}\n"
        f"Tip: {platform_tips}\n\n"
        f"Topic/Product/Brief:\n{req.topic}\n\n"
        f"Generate {req.variations} unique variations."
    )

    async def event_stream():
        ai_client = anthropic.Anthropic(api_key=api_key)
        full = ""
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Generating content…'})}\n\n"
            msg = ai_client.messages.create(
                model="claude-sonnet-4-6", max_tokens=3000,
                system=SOCIAL_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
            variations = json.loads(raw)
            for i, v in enumerate(variations):
                yield f"data: {json.dumps({'type': 'variation', 'index': i, 'data': v})}\n\n"
                await asyncio.sleep(0.05)
            yield f"data: {json.dumps({'type': 'done', 'count': len(variations)})}\n\n"
        except json.JSONDecodeError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Could not parse response. Try again.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── App Packager (direct binaries — no ZIP) ───────────────────────────────────

DIST_DIR = Path(__file__).parent / "dist_packages"
DIST_DIR.mkdir(exist_ok=True)
(DIST_DIR / "zips").mkdir(exist_ok=True)

import re as _re
def _sanitize(name: str) -> str:
    return _re.sub(r"[^A-Za-z0-9_\-]", "_", name) or "App"

class PackageRequest(BaseModel):
    project_id: str
    target:      str  = "exe"
    lang:        str  = "python"
    app_name:    str  = "MyApp"
    app_version: str  = "1.0.0"
    one_file:    bool = True
    console:     bool = False   # --console/--windowed for PyInstaller


async def _run_stream(cmd: list, cwd: str):
    """Yield (line, returncode) pairs from a subprocess."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for raw in proc.stdout:
        yield raw.decode("utf-8", errors="replace").rstrip(), None
        await asyncio.sleep(0)
    await proc.wait()
    yield "", proc.returncode


@app.post("/api/package/stream")
async def package_stream(req: PackageRequest):
    ws        = workspace(req.project_id)
    safe_name = _sanitize(req.app_name)

    async def event_stream():
        def log(text: str, level: str = "info"):
            return f"data: {json.dumps({'type':'log','text':text,'level':level})}\n\n"
        def done(file: str, url: str, size_mb: float = 0, extra_files: list = None):
            return f"data: {json.dumps({'type':'done','output_file':file,'download_url':url,'size_mb':size_mb,'extra_files': extra_files or []})}\n\n"
        def err(msg: str):
            return f"data: {json.dumps({'type':'error','message':msg})}\n\n"

        try:
            # ── 1. Python → .EXE (PyInstaller — runs directly, no ZIP) ───────
            if req.lang == "python" and req.target == "exe":
                # find entry point
                main_py = ws / "main.py"
                if not main_py.exists():
                    candidates = sorted(ws.glob("*.py"))
                    if not candidates:
                        # create a simple demo app so the user can test the pipeline
                        yield log("⚠️ لا يوجد ملف Python — إنشاء تطبيق تجريبي تلقائياً…", "info")
                        main_py.write_text(
                            f'# {req.app_name} — generated by AI Automation Studio\n'
                            f'import tkinter as tk\n'
                            f'root = tk.Tk()\n'
                            f'root.title("{req.app_name}")\n'
                            f'root.geometry("480x300")\n'
                            f'tk.Label(root, text="🚀 {req.app_name}", font=("Arial", 24, "bold")).pack(expand=True)\n'
                            f'tk.Label(root, text="Built with AI Automation Studio", font=("Arial", 11)).pack()\n'
                            f'root.mainloop()\n'
                        )
                        yield log(f"✅ تم إنشاء main.py تجريبي (tkinter)", "ok")
                    else:
                        main_py = candidates[0]
                yield log(f"✅ ملف الإدخال: {main_py.name}", "ok")

                # Auto-detect GUI vs CLI: use --windowed only for GUI toolkits
                GUI_IMPORTS = ("tkinter", "PyQt", "PySide", "wx", "kivy", "toga", "pyglet", "pygame")
                src_text = main_py.read_text(encoding="utf-8", errors="replace")
                is_gui = any(lib in src_text for lib in GUI_IMPORTS)
                windowed_flag = "--windowed" if (is_gui or not req.console) and is_gui else "--console"
                yield log(f"{'🖼 GUI detected → --windowed' if is_gui else '⌨️ CLI detected → --console'}", "info")

                # install requirements if any
                req_txt = ws / "requirements.txt"
                if req_txt.exists():
                    yield log("📦 تثبيت المتطلبات…", "cmd")
                    async for line, code in _run_stream(
                        ["python", "-m", "pip", "install", "-r", str(req_txt), "--quiet"], str(ws)
                    ):
                        if line.strip():
                            yield log(line, "info")
                        if code is not None and code != 0:
                            yield log(f"تحذير: فشل تثبيت بعض المتطلبات (exit {code})", "info")

                dist_out  = DIST_DIR / safe_name
                dist_out.mkdir(exist_ok=True)
                build_tmp = dist_out / "_build"
                spec_dir  = dist_out / "_spec"

                # use absolute paths so PyInstaller works from any cwd
                cmd = [
                    "python", "-m", "PyInstaller",
                    "--onefile" if req.one_file else "--onedir",
                    "--noconfirm", "--clean",
                    windowed_flag,
                    "--name", safe_name,
                    "--distpath", str(dist_out.resolve()),
                    "--workpath",  str(build_tmp.resolve()),
                    "--specpath",  str(spec_dir.resolve()),
                    str(main_py.resolve()),
                ]
                yield log("$ " + " ".join(cmd[2:]), "cmd")
                yield log("⏳ جاري التجميع — قد يستغرق 1-3 دقائق…", "info")

                # run from project root, not workspace
                rc = None
                project_root = str(Path(__file__).parent)
                async for line, code in _run_stream(cmd, project_root):
                    if code is not None:
                        rc = code
                        break
                    if line.strip():
                        lvl = ("err" if "ERROR" in line.upper()
                               else "ok" if any(w in line.lower() for w in ("completed", "success", "building exe"))
                               else "info")
                        yield log(line, lvl)

                if rc != 0:
                    yield log(f"❌ PyInstaller فشل (exit {rc})", "err")
                    yield err(f"Build failed (exit {rc})")
                    return

                # locate .exe
                exe = next(
                    (p for ext in (f"{safe_name}.exe", safe_name) for p in [dist_out / ext] if p.exists()),
                    None,
                )
                if not exe:
                    exe = next(iter(dist_out.glob("*.exe")), None)
                if not exe:
                    yield log("❌ لم يُعثر على الملف الناتج", "err")
                    yield err("Output file not found after build.")
                    return

                size_mb = round(exe.stat().st_size / 1024 / 1024, 1)
                yield log(f"✅ تم البناء: {exe.name} ({size_mb} MB)", "ok")

                # ── Create PowerShell installer (.bat) ──────────────────────
                yield log("📦 إنشاء مُثبِّت Windows مع اختصارات…", "info")
                installer_name = f"Install_{safe_name}.bat"
                installer_path = dist_out / installer_name

                ps_script = f"""@echo off
chcp 65001 >nul
echo.
echo  ================================
echo   تثبيت {req.app_name}
echo  ================================
echo.

set "INSTALL_DIR=%LOCALAPPDATA%\\{safe_name}"
set "EXE_NAME={exe.name}"
set "APP_NAME={req.app_name}"

echo [1/4] إنشاء مجلد التثبيت...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo [2/4] نسخ الملفات...
copy /Y "%~dp0%EXE_NAME%" "%INSTALL_DIR%\\%EXE_NAME%" >nul
if errorlevel 1 ( echo خطأ في النسخ! & pause & exit /b 1 )

echo [3/4] إنشاء اختصار سطح المكتب...
powershell -NoProfile -Command "$ws=New-Object -COM WScript.Shell; $s=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\\\\{req.app_name}.lnk'); $s.TargetPath='%INSTALL_DIR%\\\\%EXE_NAME%'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.Description='{req.app_name}'; $s.Save()"

echo [4/4] إنشاء اختصار قائمة ابدأ...
set "START_DIR=%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{safe_name}"
if not exist "%START_DIR%" mkdir "%START_DIR%"
powershell -NoProfile -Command "$ws=New-Object -COM WScript.Shell; $s=$ws.CreateShortcut('%START_DIR%\\\\{req.app_name}.lnk'); $s.TargetPath='%INSTALL_DIR%\\\\%EXE_NAME%'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.Description='{req.app_name}'; $s.Save()"

echo.
echo  ================================
echo   تم التثبيت بنجاح!
echo   - اختصار سطح المكتب: {req.app_name}
echo   - قائمة ابدأ: {req.app_name}
echo   - مجلد التثبيت: %INSTALL_DIR%
echo  ================================
echo.
pause
"""
                installer_path.write_text(ps_script, encoding="utf-8")
                yield log(f"✅ مُثبِّت جاهز: {installer_name}", "ok")
                yield log(f"📋 حمِّل الملفين وضعهما في نفس المجلد ثم شغِّل المُثبِّت", "ok")
                yield done(
                    installer_name,
                    f"/api/package/download/{safe_name}/{installer_name}",
                    size_mb,
                    extra_files=[{"name": exe.name, "url": f"/api/package/download/{safe_name}/{exe.name}"}]
                )

            # ── 2. Python → .APK (Briefcase — builds real APK) ───────────────
            elif req.lang == "python" and req.target == "apk":
                yield log("📱 بناء APK حقيقي باستخدام BeeWare Briefcase…", "cmd")

                # prepare briefcase project dir
                bf_dir = DIST_DIR / f"{safe_name}_briefcase"
                bf_dir.mkdir(exist_ok=True)

                # copy workspace source into src/safe_name/
                src_pkg = bf_dir / "src" / safe_name.lower()
                src_pkg.mkdir(parents=True, exist_ok=True)
                for f in ws.glob("*.py"):
                    import shutil
                    dest = src_pkg / f.name
                    shutil.copy2(f, dest)
                # rename main.py → __main__.py
                mp = src_pkg / "main.py"
                if mp.exists():
                    mp.rename(src_pkg / "__main__.py")
                (src_pkg / "__init__.py").touch()

                # pyproject.toml
                pyproject = f"""[tool.briefcase]
project_name = "{req.app_name}"
bundle = "com.example"
version = "{req.app_version}"
url = "https://example.com"
license.file = "LICENSE"
author = "AI Studio"
author_email = "ai@studio.com"

[tool.briefcase.app.{safe_name.lower()}]
formal_name = "{req.app_name}"
description = "Built with AI Automation Studio"
icon = "icon"
sources = ["src/{safe_name.lower()}"]
requires = ["toga"]

[tool.briefcase.app.{safe_name.lower()}.android]
requires = ["toga-android"]
base_theme = "@style/Theme.AppCompat.Light.DarkActionBar"
"""
                (bf_dir / "pyproject.toml").write_text(pyproject)
                (bf_dir / "LICENSE").write_text("MIT License")

                yield log("✅ هيكل مشروع Briefcase جاهز", "ok")
                yield log("⬇️ تحقق من Briefcase + Android SDK…", "info")

                # check briefcase
                check = await asyncio.create_subprocess_exec(
                    "python", "-m", "briefcase", "--version",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await check.wait()
                if check.returncode != 0:
                    yield log("📦 تثبيت Briefcase…", "cmd")
                    async for line, code in _run_stream(
                        ["python", "-m", "pip", "install", "briefcase", "--quiet"], str(bf_dir)
                    ):
                        if line.strip(): yield log(line, "info")

                # briefcase create android
                yield log("$ briefcase create android", "cmd")
                yield log("⏳ إعداد مشروع Android (قد يُحمِّل Android SDK في المرة الأولى ~5 دقائق)…", "info")
                async for line, code in _run_stream(
                    ["python", "-m", "briefcase", "create", "android", "--no-input"], str(bf_dir)
                ):
                    if code is not None:
                        if code != 0:
                            yield log(f"❌ briefcase create فشل (exit {code})", "err")
                            yield err(f"briefcase create failed (exit {code})")
                            return
                        break
                    if line.strip():
                        lvl = "err" if "error" in line.lower() else "ok" if "success" in line.lower() else "info"
                        yield log(line, lvl)

                # briefcase build android
                yield log("$ briefcase build android", "cmd")
                yield log("⏳ جاري تجميع APK…", "info")
                async for line, code in _run_stream(
                    ["python", "-m", "briefcase", "build", "android", "--no-input"], str(bf_dir)
                ):
                    if code is not None:
                        if code != 0:
                            yield log(f"❌ briefcase build فشل (exit {code})", "err")
                            yield err(f"briefcase build failed (exit {code})")
                            return
                        break
                    if line.strip():
                        lvl = "err" if "error" in line.lower() else "ok" if "apk" in line.lower() or "success" in line.lower() else "info"
                        yield log(line, lvl)

                # find APK
                apk_files = list(bf_dir.rglob("*.apk"))
                if not apk_files:
                    yield log("❌ لم يُعثر على APK بعد البناء", "err")
                    yield err("APK not found after build.")
                    return

                apk       = apk_files[0]
                # copy to dist for serving
                out_apk   = DIST_DIR / safe_name / apk.name
                (DIST_DIR / safe_name).mkdir(exist_ok=True)
                import shutil
                shutil.copy2(apk, out_apk)
                size_mb   = round(out_apk.stat().st_size / 1024 / 1024, 1)
                yield log(f"✅ APK جاهز: {out_apk.name} ({size_mb} MB)", "ok")
                yield log("📲 حمِّل الملف وثبِّته مباشرة على جهاز Android", "ok")
                yield done(out_apk.name, f"/api/package/download/{safe_name}/{out_apk.name}", size_mb)

            # ── 3. Web → .APK (Capacitor + Gradle — builds real APK) ─────────
            elif req.lang == "web" and req.target == "apk":
                yield log("🌐 بناء APK من تطبيق ويب باستخدام Capacitor + Gradle…", "cmd")

                # verify node/npm available
                npm_check = await asyncio.create_subprocess_exec(
                    "npm", "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await npm_check.wait()
                if npm_check.returncode != 0:
                    yield log("❌ Node.js غير مثبّت. يُرجى تثبيت Node.js من nodejs.org أولاً.", "err")
                    yield err("Node.js not installed.")
                    return

                # verify Android SDK / gradlew
                cap_dir = DIST_DIR / f"{safe_name}_capacitor"
                cap_dir.mkdir(exist_ok=True)

                html_files = list(ws.glob("*.html"))
                entry = html_files[0].name if html_files else "index.html"
                if not (ws / entry).exists():
                    (ws / entry).write_text(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{req.app_name}</title></head><body><h1>{req.app_name}</h1></body></html>")

                # copy web files to cap_dir/dist
                dist_web = cap_dir / "dist"
                dist_web.mkdir(exist_ok=True)
                import shutil
                for f in ws.iterdir():
                    if f.is_file() and f.suffix in (".html", ".css", ".js", ".png", ".jpg", ".svg", ".ico"):
                        shutil.copy2(f, dist_web / f.name)

                # write package.json + capacitor config
                (cap_dir / "package.json").write_text(json.dumps({
                    "name": safe_name.lower(), "version": req.app_version,
                    "scripts": {"build": "echo done"},
                    "dependencies": {"@capacitor/core": "6.x", "@capacitor/android": "6.x", "@capacitor/cli": "6.x"},
                }, indent=2))
                (cap_dir / "capacitor.config.json").write_text(json.dumps({
                    "appId": f"com.aistudio.{safe_name.lower()}",
                    "appName": req.app_name,
                    "webDir": "dist",
                }, indent=2))

                yield log("📦 npm install…", "cmd")
                async for line, code in _run_stream(["npm", "install", "--silent"], str(cap_dir)):
                    if code is not None:
                        if code != 0:
                            yield log(f"npm install فشل (exit {code})", "err")
                            yield err(f"npm install failed"); return
                        break
                    if line.strip(): yield log(line, "info")

                yield log("$ npx cap add android", "cmd")
                async for line, code in _run_stream(["npx", "cap", "add", "android"], str(cap_dir)):
                    if code is not None:
                        if code != 0:
                            yield log(f"cap add android فشل (exit {code})", "err")
                            yield err(f"cap add android failed"); return
                        break
                    if line.strip(): yield log(line, "info")

                yield log("$ npx cap sync", "cmd")
                async for line, code in _run_stream(["npx", "cap", "sync", "android"], str(cap_dir)):
                    if code is not None: break
                    if line.strip(): yield log(line, "info")

                # Build with Gradle
                gradlew = cap_dir / "android" / "gradlew.bat"
                yield log("$ gradlew assembleDebug", "cmd")
                yield log("⏳ جاري Gradle build (قد يستغرق 3-8 دقائق في المرة الأولى)…", "info")
                async for line, code in _run_stream([str(gradlew), "assembleDebug"], str(cap_dir / "android")):
                    if code is not None:
                        if code != 0:
                            yield log(f"Gradle فشل (exit {code})", "err")
                            yield err(f"Gradle build failed (exit {code})"); return
                        break
                    if line.strip():
                        lvl = "err" if "error" in line.lower() else "ok" if "build successful" in line.lower() else "info"
                        yield log(line, lvl)

                apk_files = list((cap_dir / "android").rglob("*debug*.apk"))
                if not apk_files:
                    yield log("❌ لم يُعثر على APK", "err")
                    yield err("APK not found after Gradle build."); return

                apk     = apk_files[0]
                out_apk = DIST_DIR / safe_name / apk.name
                (DIST_DIR / safe_name).mkdir(exist_ok=True)
                shutil.copy2(apk, out_apk)
                size_mb = round(out_apk.stat().st_size / 1024 / 1024, 1)
                yield log(f"✅ APK جاهز: {out_apk.name} ({size_mb} MB)", "ok")
                yield log("📲 حمِّل الملف وثبِّته مباشرة على Android", "ok")
                yield done(out_apk.name, f"/api/package/download/{safe_name}/{out_apk.name}", size_mb)

            # ── 4. Web → .EXE (Electron Builder — installs + builds real NSIS)
            elif req.lang == "electron" and req.target == "exe":
                yield log("⚡ بناء .EXE باستخدام Electron Builder…", "cmd")

                npm_check = await asyncio.create_subprocess_exec(
                    "npm", "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await npm_check.wait()
                if npm_check.returncode != 0:
                    yield log("❌ Node.js غير مثبّت. يُرجى تثبيت Node.js من nodejs.org.", "err")
                    yield err("Node.js not installed."); return

                el_dir = DIST_DIR / f"{safe_name}_electron"
                el_dir.mkdir(exist_ok=True)
                import shutil
                for f in ws.iterdir():
                    if f.is_file():
                        shutil.copy2(f, el_dir / f.name)

                html_files = list(el_dir.glob("*.html"))
                entry = html_files[0].name if html_files else "index.html"
                if not (el_dir / entry).exists():
                    (el_dir / entry).write_text(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{req.app_name}</title></head><body style='font-family:sans-serif;padding:40px;background:#1a1a2e;color:#fff'><h1>{req.app_name}</h1><p>Powered by AI Automation Studio</p></body></html>")

                (el_dir / "main.js").write_text(f"""const {{app, BrowserWindow}} = require('electron')
function createWindow() {{
  const win = new BrowserWindow({{
    width: 1200, height: 800,
    icon: 'icon.png',
    webPreferences: {{nodeIntegration: false, contextIsolation: true}}
  }})
  win.loadFile('{entry}')
  win.setTitle('{req.app_name}')
}}
app.whenReady().then(createWindow)
app.on('window-all-closed', () => {{ if (process.platform !== 'darwin') app.quit() }})
""")
                (el_dir / "package.json").write_text(json.dumps({
                    "name": safe_name.lower(), "version": req.app_version,
                    "description": req.app_name, "main": "main.js",
                    "scripts": {"start": "electron .", "dist": "electron-builder --win --x64"},
                    "build": {
                        "appId": f"com.aistudio.{safe_name.lower()}",
                        "productName": req.app_name,
                        "win": {"target": [{"target": "nsis", "arch": ["x64"]}], "icon": None},
                        "nsis": {"oneClick": True, "perMachine": False},
                        "files": ["**/*", "!node_modules/**"],
                    },
                    "devDependencies": {"electron": "^32.0.0", "electron-builder": "^25.0.0"},
                }, indent=2))

                yield log("📦 npm install…", "cmd")
                async for line, code in _run_stream(["npm", "install", "--silent"], str(el_dir)):
                    if code is not None:
                        if code != 0:
                            yield log(f"npm install فشل (exit {code})", "err")
                            yield err("npm install failed"); return
                        break
                    if line.strip(): yield log(line, "info")

                yield log("$ npm run dist  (Electron Builder NSIS)", "cmd")
                yield log("⏳ جاري البناء — قد يستغرق 3-10 دقائق…", "info")
                async for line, code in _run_stream(["npm", "run", "dist"], str(el_dir)):
                    if code is not None:
                        if code != 0:
                            yield log(f"❌ electron-builder فشل (exit {code})", "err")
                            yield err(f"electron-builder failed (exit {code})"); return
                        break
                    if line.strip():
                        lvl = "err" if "error" in line.lower() else "ok" if "target=" in line.lower() or "packag" in line.lower() else "info"
                        yield log(line, lvl)

                # find installer
                dist_el = el_dir / "dist"
                exe_files = list(dist_el.glob("**/*.exe")) if dist_el.exists() else []
                if not exe_files:
                    yield log("❌ لم يُعثر على .exe", "err")
                    yield err("EXE not found after build."); return

                exe = exe_files[0]
                out_exe = DIST_DIR / safe_name / exe.name
                (DIST_DIR / safe_name).mkdir(exist_ok=True)
                shutil.copy2(exe, out_exe)
                size_mb = round(out_exe.stat().st_size / 1024 / 1024, 1)
                yield log(f"✅ مُثبِّت Windows جاهز: {out_exe.name} ({size_mb} MB)", "ok")
                yield log("💻 شغِّل الملف لتثبيت التطبيق مباشرة على Windows", "ok")
                yield done(out_exe.name, f"/api/package/download/{safe_name}/{out_exe.name}", size_mb)

            else:
                yield log(f"التركيبة {req.lang}→{req.target} غير مدعومة حالياً.", "err")
                yield err("Unsupported combination.")

        except Exception as e:
            import traceback
            yield log(f"خطأ: {e}", "err")
            yield log(traceback.format_exc(), "err")
            yield err(str(e))

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/package/download/{folder}/{filename}")
async def download_package(folder: str, filename: str):
    from fastapi.responses import FileResponse
    safe_f = _sanitize(folder)
    # Strip any path separators or traversal sequences from filename
    safe_n = _sanitize(filename.rsplit(".", 1)[0]) + ("." + filename.rsplit(".", 1)[1] if "." in filename else "")
    safe_n = safe_n.replace("..", "")
    path = (DIST_DIR / safe_f / safe_n).resolve()
    # Hard guard: must stay inside DIST_DIR
    if not str(path).startswith(str(DIST_DIR.resolve())):
        raise HTTPException(400, "Invalid path")
    if not path.exists():
        raise HTTPException(404, "File not found")
    ext = path.suffix.lower()
    media = ("application/vnd.android.package-archive" if ext == ".apk"
             else "application/zip" if ext == ".zip"
             else "application/octet-stream")
    return FileResponse(str(path), media_type=media, filename=path.name,
                        headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


# ── AI Design ─────────────────────────────────────────────────────────────────

class DesignAIRequest(BaseModel):
    prompt: str
    template: Optional[str] = "Instagram Post"

@app.post("/api/design/ai-generate")
async def design_ai_generate(req: DesignAIRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set.")

    SIZES = {"Instagram Post": (1080,1080), "Instagram Story": (1080,1920), "Facebook Cover": (820,312),
             "Facebook Post": (1200,630), "YouTube Thumb": (1280,720), "A4 Portrait": (794,1123), "Presentation": (1920,1080)}
    w, h = SIZES.get(req.template or "", (1080,1080))

    system = f"""You are a graphic design AI. Given a design brief, output ONLY a valid JSON object representing a Fabric.js canvas.

Canvas size: {w}x{h}

JSON format:
{{
  "version": "6.0.0",
  "objects": [
    {{
      "type": "Rect", "left": 0, "top": 0, "width": {w}, "height": {h},
      "fill": "gradient_or_hex", "selectable": false
    }},
    {{
      "type": "IText", "text": "MAIN TITLE", "left": {w//2}, "top": {h//3},
      "fontSize": 80, "fontFamily": "Cairo", "fill": "#ffffff",
      "fontWeight": "bold", "textAlign": "center", "originX": "center", "originY": "center"
    }}
  ],
  "background": "#hex_or_gradient_string"
}}

Rules:
- Use Arabic-friendly fonts (Cairo, Tajawal, Almarai) for Arabic text
- Choose beautiful, trendy color combinations
- Include 2-5 text elements and 2-4 decorative shapes
- Make it visually striking and professional
- Return ONLY the JSON, no explanation
"""

    try:
        ai = anthropic.Anthropic(api_key=api_key)
        msg = ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=3000,
            system=system,
            messages=[{"role": "user", "content": f"Design brief: {req.prompt}\nTemplate: {req.template}"}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
        canvas_json = json.loads(raw)
        return {"canvas_json": canvas_json}
    except json.JSONDecodeError:
        raise HTTPException(502, "Claude returned invalid JSON for the design.")
    except Exception as e:
        raise HTTPException(502, str(e))


if __name__ == "__main__":
    import uvicorn
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
