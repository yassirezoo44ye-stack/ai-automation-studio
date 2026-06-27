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
