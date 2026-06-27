from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import os
import json
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import uuid
import anthropic

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ai_user:aiStudio2026!@127.0.0.1:5432/ai_studio")

pool: asyncpg.Pool = None


# ── Models ──────────────────────────────────────────────────────────────────

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

class UsageLogCreate(BaseModel):
    action: str = Field(..., min_length=1, max_length=100)
    details: Optional[dict] = None

class RunRequest(BaseModel):
    project_id: str
    prompt: str = Field(..., min_length=1, max_length=4000)


# ── DB init ──────────────────────────────────────────────────────────────────

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
        INSERT INTO users (id, email, name) VALUES ($1, $2, $3)
        ON CONFLICT (id) DO NOTHING
    ''', test_uid, "test@example.com", "Test User")
    # Seed demo project
    demo_pid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    await conn.execute('''
        INSERT INTO projects (id, user_id, name, description) VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO NOTHING
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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>AI Automation Studio</title></head>
<body style="font-family:sans-serif;padding:40px;background:#0d0f14;color:#e2e8f0">
<h1 style="color:#6c8ef7">◈ AI Automation Studio</h1>
<p>Backend running on PostgreSQL. <a href="/docs" style="color:#6c8ef7">API Docs →</a></p>
</body></html>"""


@app.get("/health")
async def health():
    async with pool.acquire() as conn:
        pg_version = await conn.fetchval("SELECT version()")
    return {"status": "healthy", "db": "postgresql", "pg_version": pg_version, "timestamp": datetime.utcnow().isoformat()}


@app.post("/run")
async def run_agent(req: RunRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set on the server.")
    try:
        ai = anthropic.Anthropic(api_key=api_key)
        message = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": req.prompt}],
        )
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid Anthropic API key. Update ANTHROPIC_API_KEY in .env.")
    except anthropic.PermissionDeniedError as e:
        raise HTTPException(status_code=402, detail=f"Anthropic account issue: {e.message}")
    except anthropic.BadRequestError as e:
        body = e.body if hasattr(e, 'body') and e.body else {}
        msg = body.get('error', {}).get('message', str(e)) if isinstance(body, dict) else str(e)
        raise HTTPException(status_code=402, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    summary = message.content[0].text

    pid = uuid.UUID("00000000-0000-0000-0000-000000000001") if req.project_id == "demo" else uuid.UUID(req.project_id)

    async with pool.acquire() as conn:
        run_id = await conn.fetchval('''
            INSERT INTO agent_runs (project_id, agent_type, input_data, output_data, status, completed_at)
            VALUES ($1, 'claude', $2, $3, 'completed', NOW()) RETURNING id
        ''', pid, json.dumps({"prompt": req.prompt}), json.dumps({"summary": summary}))

        await conn.execute('''
            INSERT INTO usage_logs (user_id, action, details)
            VALUES ($1, 'agent_run', $2)
        ''', USER_ID, json.dumps({"run_id": str(run_id), "prompt_preview": req.prompt[:80]}))

    return {"result": {"summary": summary}}


@app.get("/api/stats")
async def get_stats():
    async with pool.acquire() as conn:
        project_count  = await conn.fetchval("SELECT COUNT(*) FROM projects")
        run_count      = await conn.fetchval("SELECT COUNT(*) FROM agent_runs")
        completed      = await conn.fetchval("SELECT COUNT(*) FROM agent_runs WHERE status='completed'")
        logs           = await conn.fetch(
            "SELECT action, details, created_at FROM usage_logs ORDER BY created_at DESC LIMIT 10"
        )
    return {
        "projects":       int(project_count),
        "agent_runs":     int(run_count),
        "completed_runs": int(completed),
        "success_rate":   round(int(completed) / max(int(run_count), 1) * 100, 1),
        "recent_activity": [
            {"action": r["action"], "details": dict(r["details"]) if r["details"] else {}, "time": r["created_at"].isoformat()}
            for r in logs
        ],
    }


@app.post("/api/projects")
async def create_project(project: ProjectCreate):
    async with pool.acquire() as conn:
        pid = await conn.fetchval(
            "INSERT INTO projects (user_id, name, description) VALUES ($1, $2, $3) RETURNING id",
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
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": str(row["id"]), "name": row["name"], "description": row["description"],
            "status": row["status"], "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat()}


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, project: ProjectUpdate):
    async with pool.acquire() as conn:
        result = await conn.execute('''
            UPDATE projects SET
                name        = COALESCE($1, name),
                description = COALESCE($2, description),
                updated_at  = NOW()
            WHERE id = $3
        ''', project.name, project.description, uuid.UUID(project_id))
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Project not found")
    return {"message": "Updated"}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM projects WHERE id=$1", uuid.UUID(project_id))
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Project not found")
    return {"message": "Deleted"}


@app.post("/api/agent-runs")
async def create_agent_run(run: AgentRunCreate):
    async with pool.acquire() as conn:
        run_id = await conn.fetchval('''
            INSERT INTO agent_runs (project_id, agent_type, input_data, status)
            VALUES ($1, $2, $3, 'running') RETURNING id
        ''', uuid.UUID(run.project_id), run.agent_type, json.dumps(run.input_data))
    return {"id": str(run_id), "status": "running"}


@app.get("/api/agent-runs")
async def list_agent_runs(project_id: Optional[str] = None):
    async with pool.acquire() as conn:
        if project_id:
            rows = await conn.fetch(
                "SELECT id, project_id, agent_type, status, started_at, completed_at FROM agent_runs WHERE project_id=$1 ORDER BY started_at DESC",
                uuid.UUID(project_id),
            )
        else:
            rows = await conn.fetch(
                "SELECT id, project_id, agent_type, status, started_at, completed_at FROM agent_runs ORDER BY started_at DESC"
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


if __name__ == "__main__":
    import uvicorn
    # Load .env manually if python-dotenv not installed
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
