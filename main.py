from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
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


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>AI Automation Studio</title></head>
<body style="font-family:sans-serif;padding:40px;background:#0d0f14;color:#e2e8f0">
<h1 style="color:#6c8ef7">◈ AI Automation Studio</h1>
<p>Backend running. <a href="/docs" style="color:#6c8ef7">API Docs →</a></p>
</body></html>"""

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
            {"action": r["action"], "details": dict(r["details"]) if r["details"] else {}, "time": r["created_at"].isoformat()}
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
    ws = WORKSPACES / project_id
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
    command = body.command or "python main.py"

    # Safety: block dangerous commands
    blocked = ["rm ", "del ", "format ", "shutdown", "reboot", ":(){", "dd if"]
    if any(b in command.lower() for b in blocked):
        raise HTTPException(400, "Command not allowed.")

    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(ws),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "command": command,
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


@app.on_event("startup")
async def on_startup():
    await ensure_agents_table()


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
