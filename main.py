from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import os
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import uuid

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_studio")

# Pydantic models
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

# Database pool
pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    await init_db()
    yield
    await pool.close()

app = FastAPI(title="AI Automation Studio", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def init_db():
    async with pool.acquire() as conn:
        # Users table
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        
        # Projects table with RLS
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                status VARCHAR(50) DEFAULT 'active',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        
        # Agent runs table with RLS
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                agent_type VARCHAR(50) NOT NULL,
                input_data JSONB,
                output_data JSONB,
                status VARCHAR(50) DEFAULT 'pending',
                started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                completed_at TIMESTAMP WITH TIME ZONE,
                error_message TEXT
            )
        ''')
        
        # Usage logs table with RLS
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS usage_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action VARCHAR(100) NOT NULL,
                details JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        
        # Enable RLS
        await conn.execute('ALTER TABLE IF EXISTS projects ENABLE ROW LEVEL SECURITY')
        await conn.execute('ALTER TABLE IF EXISTS agent_runs ENABLE ROW LEVEL SECURITY')
        await conn.execute('ALTER TABLE IF EXISTS usage_logs ENABLE ROW LEVEL SECURITY')
        
        # Create RLS policies
        await conn.execute('''
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = 'projects' AND policyname = 'projects_user_isolation'
                ) THEN
                    CREATE POLICY projects_user_isolation ON projects
                        USING (user_id = current_setting('app.current_user_id')::UUID);
                END IF;
            END
            $$;
        ''')
        
        await conn.execute('''
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = 'agent_runs' AND policyname = 'agent_runs_user_isolation'
                ) THEN
                    CREATE POLICY agent_runs_user_isolation ON agent_runs
                        USING (project_id IN (
                            SELECT id FROM projects WHERE user_id = current_setting('app.current_user_id')::UUID
                        ));
                END IF;
            END
            $$;
        ''')
        
        await conn.execute('''
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = 'usage_logs' AND policyname = 'usage_logs_user_isolation'
                ) THEN
                    CREATE POLICY usage_logs_user_isolation ON usage_logs
                        USING (user_id = current_setting('app.current_user_id')::UUID);
                END IF;
            END
            $$;
        ''')
        
        # Insert test user if not exists
        test_user_id = '00000000-0000-0000-0000-000000000000'
        await conn.execute('''
            INSERT INTO users (id, email, name)
            VALUES ($1, 'test@example.com', 'Test User')
            ON CONFLICT (id) DO NOTHING
        ''', uuid.UUID(test_user_id))

async def get_current_user_id():
    return "00000000-0000-0000-0000-000000000000"

async def set_user_context(conn, user_id):
    await conn.execute("SET LOCAL app.current_user_id = $1", user_id)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ø§Ø³ØªÙØ¯ÙÙ Ø§ÙØ£ØªÙØªØ© Ø§ÙØ°ÙÙØ©</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            text-align: center;
            padding: 40px 0;
            color: white;
        }
        header h1 {
            font-size: 3em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        header p {
            font-size: 1.2em;
            opacity: 0.9;
        }
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            transition: transform 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
        }
        .card h2 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.5em;
        }
        .card p {
            color: #666;
            line-height: 1.6;
        }
        .btn {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 12px 30px;
            border-radius: 25px;
            text-decoration: none;
            margin-top: 15px;
            transition: opacity 0.3s ease;
        }
        .btn:hover {
            opacity: 0.9;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 30px;
        }
        .stat {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            color: white;
        }
        .stat h3 {
            font-size: 2em;
            margin-bottom: 5px;
        }
        footer {
            text-align: center;
            padding: 40px 0;
            color: white;
            opacity: 0.8;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Ø§Ø³ØªÙØ¯ÙÙ Ø§ÙØ£ØªÙØªØ© Ø§ÙØ°ÙÙØ©</h1>
            <p>ÙÙØµØ© ÙØªÙØ§ÙÙØ© ÙØ¥Ø¯Ø§Ø±Ø© Ø§ÙÙØ´Ø§Ø±ÙØ¹ ÙØ§ÙÙÙÙØ§Ø¡ Ø§ÙØ°ÙÙÙÙ</p>
        </header>
        
        <div class="cards">
            <div class="card">
                <h2>ð Ø§ÙÙØ´Ø§Ø±ÙØ¹</h2>
                <p>Ø¥ÙØ´Ø§Ø¡ ÙØ¥Ø¯Ø§Ø±Ø© Ø§ÙÙØ´Ø§Ø±ÙØ¹ ÙØ¹ Ø¯Ø¹Ù ÙØ§ÙÙ ÙÙØªØ¹Ø§ÙÙ Ø§ÙÙØ±ÙÙÙ ÙÙØªØ§Ø¨Ø¹Ø© Ø§ÙØªÙØ¯Ù.</p>
                <a href="/docs" class="btn">Ø§Ø³ØªÙØ´Ù API</a>
            </div>
            <div class="card">
                <h2>ð¤ Ø§ÙÙÙÙØ§Ø¡ Ø§ÙØ°ÙÙÙÙ</h2>
                <p>ØªØ´ØºÙÙ ÙÙØ±Ø§ÙØ¨Ø© Ø§ÙÙÙÙØ§Ø¡ Ø§ÙØ°ÙÙÙÙ ÙØ¹ ØªØªØ¨Ø¹ Ø§ÙØ£Ø¯Ø§Ø¡ ÙØ§ÙÙØªØ§Ø¦Ø¬.</p>
                <a href="/docs" class="btn">Ø§Ø³ØªÙØ´Ù API</a>
            </div>
            <div class="card">
                <h2>ð Ø§ÙØªØ­ÙÙÙØ§Øª</h2>
                <p>ØªØªØ¨Ø¹ Ø§ÙØ§Ø³ØªØ®Ø¯Ø§Ù ÙØ§ÙØ£Ø¯Ø§Ø¡ ÙØ¹ ØªÙØ§Ø±ÙØ± ÙÙØµÙØ© ÙØ¥Ø­ØµØ§Ø¦ÙØ§Øª ÙÙ Ø§ÙÙÙØª Ø§ÙÙØ¹ÙÙ.</p>
                <a href="/docs" class="btn">Ø§Ø³ØªÙØ´Ù API</a>
            </div>
        </div>
        
        <div class="stats">
            <div class="stat">
                <h3>ð</h3>
                <p>FastAPI Backend</p>
            </div>
            <div class="stat">
                <h3>ð</h3>
                <p>PostgreSQL Database</p>
            </div>
            <div class="stat">
                <h3>ð</h3>
                <p>Row Level Security</p>
            </div>
        </div>
        
        <footer>
            <p>ØªÙ Ø§ÙØªØ·ÙÙØ± Ø¨Ø§Ø³ØªØ®Ø¯Ø§Ù FastAPI + PostgreSQL</p>
            <p>API Documentation: <a href="/docs" style="color: #fff;">/docs</a></p>
        </footer>
    </div>
</body>
</html>
'''

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML_TEMPLATE

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@app.post("/api/projects")
async def create_project(project: ProjectCreate, user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        project_id = await conn.fetchval('''
            INSERT INTO projects (user_id, name, description)
            VALUES ($1, $2, $3)
            RETURNING id
        ''', uuid.UUID(user_id), project.name, project.description)
        
        await conn.execute('''
            INSERT INTO usage_logs (user_id, action, details)
            VALUES ($1, $2, $3)
        ''', uuid.UUID(user_id), 'project_created', {'project_id': str(project_id)})
        
        return {"id": str(project_id), "message": "Project created successfully"}

@app.get("/api/projects")
async def list_projects(user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        rows = await conn.fetch('''
            SELECT id, name, description, status, created_at, updated_at
            FROM projects ORDER BY created_at DESC
        ''')
        return [{"id": str(r["id"]), "name": r["name"], "description": r["description"],
                 "status": r["status"], "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]

@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        row = await conn.fetchrow('''
            SELECT id, name, description, status, created_at, updated_at
            FROM projects WHERE id = $1
        ''', uuid.UUID(project_id))
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"id": str(row["id"]), "name": row["name"], "description": row["description"],
                "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, project: ProjectUpdate, user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        result = await conn.execute('''
            UPDATE projects SET name = COALESCE($1, name),
                               description = COALESCE($2, description),
                               updated_at = NOW()
            WHERE id = $3
        ''', project.name, project.description, uuid.UUID(project_id))
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Project not found")
        return {"message": "Project updated successfully"}

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        result = await conn.execute('DELETE FROM projects WHERE id = $1', uuid.UUID(project_id))
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Project not found")
        return {"message": "Project deleted successfully"}

@app.post("/api/agent-runs")
async def create_agent_run(run: AgentRunCreate, user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        run_id = await conn.fetchval('''
            INSERT INTO agent_runs (project_id, agent_type, input_data, status)
            VALUES ($1, $2, $3, 'running')
            RETURNING id
        ''', uuid.UUID(run.project_id), run.agent_type, run.input_data)
        
        await conn.execute('''
            INSERT INTO usage_logs (user_id, action, details)
            VALUES ($1, $2, $3)
        ''', uuid.UUID(user_id), 'agent_run_started', {'run_id': str(run_id), 'agent_type': run.agent_type})
        
        return {"id": str(run_id), "status": "running", "message": "Agent run started"}

@app.get("/api/agent-runs")
async def list_agent_runs(project_id: Optional[str] = None, user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        if project_id:
            rows = await conn.fetch('''
                SELECT * FROM agent_runs WHERE project_id = $1 ORDER BY started_at DESC
            ''', uuid.UUID(project_id))
        else:
            rows = await conn.fetch('SELECT * FROM agent_runs ORDER BY started_at DESC')
        return [{"id": str(r["id"]), "project_id": str(r["project_id"]), "agent_type": r["agent_type"],
                 "status": r["status"], "started_at": r["started_at"], "completed_at": r["completed_at"]} for r in rows]

@app.post("/api/usage-logs")
async def create_usage_log(log: UsageLogCreate, user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        log_id = await conn.fetchval('''
            INSERT INTO usage_logs (user_id, action, details)
            VALUES ($1, $2, $3)
            RETURNING id
        ''', uuid.UUID(user_id), log.action, log.details)
        return {"id": str(log_id), "message": "Usage logged successfully"}

@app.get("/api/usage-logs")
async def list_usage_logs(user_id: str = Depends(get_current_user_id)):
    async with pool.acquire() as conn:
        await set_user_context(conn, user_id)
        rows = await conn.fetch('''
            SELECT * FROM usage_logs ORDER BY created_at DESC LIMIT 100
        ''')
        return [{"id": str(r["id"]), "action": r["action"], "details": r["details"],
                 "created_at": r["created_at"]} for r in rows]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
