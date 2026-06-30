import asyncio
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import USER_ID
from app.core.db import get_pool
from app.core.filesystem import workspace, safe_path
from app.core.helpers import get_ai_client, resolve_project_id, anthropic_error_message, strip_fences
from app.core.security import ai_rate_limit

router = APIRouter(tags=["build"])

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

BUILD_PLAN_SYSTEM = """You are a senior full-stack software architect.
Given a request, design the complete file/folder structure needed to deliver it as a genuinely runnable, production-quality result — including, when relevant: backend API, database schema/migrations, authentication, frontend, Docker support, .env.example, README.md, automated tests, and PWA assets (manifest/service worker) for web apps.
Respond with ONLY a valid JSON object, no markdown fences, no explanation:
{
  "description": "short description of what will be built",
  "run_command": "command to run the program",
  "language": "primary language",
  "files": [
    {"path": "relative/path/to/file.ext", "purpose": "one or two sentences describing exactly what this file must contain"}
  ]
}
Rules:
- Use relative paths only, never absolute.
- List every file needed for the result to actually work end-to-end — do not skip config, migrations, or env templates.
- Keep the file list focused: prefer 8-30 files; do not split a project into more files than it needs.
- Do NOT include file contents here — only path + purpose.
"""

BUILD_FILE_SYSTEM = """You are a senior full-stack software engineer.
You are given the overall plan for a project and asked to write the COMPLETE, production-quality content for exactly ONE file in that project.
Respond with ONLY the raw file content. No markdown code fences, no explanation, no JSON wrapper — just the file's exact contents.
Write clean, secure, working code: validate inputs, parameterize SQL, escape/encode output to prevent XSS, and never hardcode secrets (reference environment variables instead, and list them in .env.example when you are writing that file).
"""

BUILD_MAX_FILES = 30


class BuildRequest(BaseModel):
    project_id: str
    prompt: str = Field(..., min_length=1, max_length=10000)


class RunRequest2(BaseModel):
    command: Optional[str] = None


class FileWrite(BaseModel):
    path: str
    content: str


class FileSyncRequest(BaseModel):
    files: list[FileWrite]


@router.post("/api/build")
async def build_program(req: BuildRequest):
    ai = get_ai_client()
    try:
        msg = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            system=BUILD_SYSTEM,
            messages=[{"role": "user", "content": req.prompt}],
        )
    except anthropic.BadRequestError as e:
        raise HTTPException(402, anthropic_error_message(e))
    except Exception as e:
        raise HTTPException(502, str(e))

    raw = strip_fences(msg.content[0].text)
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

    async with get_pool().acquire() as conn:
        pid = resolve_project_id(req.project_id)
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


@router.post("/api/build/stream")
async def build_stream(req: BuildRequest, request: Request):
    ai_rate_limit(request, max_calls=10, window=60)
    ai = get_ai_client()

    async def event_stream():
        try:
            yield f"data: {json.dumps({'type':'status','message':'🤖 يخطط للمشروع…'})}\n\n"

            plan_chunks: list[str] = []
            with ai.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=BUILD_PLAN_SYSTEM,
                messages=[{"role": "user", "content": req.prompt}],
            ) as stream:
                for text in stream.text_stream:
                    plan_chunks.append(text)

            try:
                plan = json.loads(strip_fences("".join(plan_chunks)))
            except json.JSONDecodeError:
                yield f"data: {json.dumps({'type':'error','message':'تعذّر فهم خطة المشروع — حاول صياغة الطلب بشكل أوضح'})}\n\n"
                return

            files_meta = [f for f in plan.get("files", []) if f.get("path")][:BUILD_MAX_FILES]
            if not files_meta:
                yield f"data: {json.dumps({'type':'error','message':'لم يتمكن النظام من تحديد أي ملفات لهذا الطلب'})}\n\n"
                return

            all_paths = ", ".join(f["path"] for f in files_meta)
            yield f"data: {json.dumps({'type':'status','message':f'📋 الخطة جاهزة — {len(files_meta)} ملف…'})}\n\n"

            ws = workspace(req.project_id)
            written = []
            for i, fmeta in enumerate(files_meta, 1):
                path = fmeta["path"]
                purpose = fmeta.get("purpose", "")
                yield f"data: {json.dumps({'type':'status','message':f'✍️ ({i}/{len(files_meta)}) {path}…'})}\n\n"

                file_prompt = (
                    f"Project request: {req.prompt}\n\n"
                    f"Overall plan: {plan.get('description', '')}\n"
                    f"All files in this project: {all_paths}\n\n"
                    f"Write the complete content for this one file:\n"
                    f"Path: {path}\nPurpose: {purpose}"
                )
                content_chunks: list[str] = []
                with ai.messages.stream(
                    model="claude-sonnet-4-6",
                    max_tokens=8000,
                    system=BUILD_FILE_SYSTEM,
                    messages=[{"role": "user", "content": file_prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        content_chunks.append(text)

                content = strip_fences("".join(content_chunks))
                dest = safe_path(ws, path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                written.append(path)
                yield f"data: {json.dumps({'type':'file','path':path,'content':content})}\n\n"

            yield f"data: {json.dumps({'type':'done','description':plan.get('description',''),'files':written,'run_command':plan.get('run_command',''),'language':plan.get('language','')})}\n\n"

            try:
                async with get_pool().acquire() as conn:
                    pid = resolve_project_id(req.project_id)
                    await conn.execute(
                        "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'build',$2)",
                        USER_ID, json.dumps({"prompt": req.prompt[:80], "files": written}),
                    )
            except Exception:
                pass

        except anthropic.BadRequestError as e:
            yield f"data: {json.dumps({'type':'error','message':anthropic_error_message(e)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/projects/{project_id}/files")
async def list_files(project_id: str):
    ws = workspace(project_id)
    files = []
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(ws)).replace("\\", "/")
            files.append({"path": rel, "size": p.stat().st_size})
    return {"files": files, "workspace": str(ws)}


@router.get("/api/projects/{project_id}/files/{file_path:path}")
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


@router.post("/api/projects/{project_id}/sync")
async def sync_files(project_id: str, body: FileSyncRequest):
    ws = workspace(project_id)
    written = []
    for f in body.files:
        dest = safe_path(ws, f.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.content, encoding="utf-8")
        written.append(f.path)
    return {"synced": written}


@router.post("/api/projects/{project_id}/upload")
async def upload_files(project_id: str, files: list[UploadFile]):
    ws = workspace(project_id)
    saved = []
    for uf in files:
        safe_name = Path(uf.filename).name
        dest = safe_path(ws, safe_name)
        content = await uf.read()
        dest.write_bytes(content)
        saved.append({"path": safe_name, "size": len(content)})
    return {"saved": saved, "count": len(saved)}


@router.delete("/api/projects/{project_id}/files")
async def clear_workspace(project_id: str):
    ws = workspace(project_id)
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)
    return {"message": "Workspace cleared"}


@router.get("/api/projects/{project_id}/download")
async def download_workspace(project_id: str):
    ws = workspace(project_id)
    if not ws.exists() or not any(ws.rglob("*")):
        raise HTTPException(404, "No files to download")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(ws.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(ws))
    buf.seek(0)

    name = f"project-{project_id[:8]}.zip"
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/api/projects/{project_id}/run")
async def run_project(project_id: str, body: RunRequest2):
    import shlex
    ws = workspace(project_id)
    raw_command = (body.command or "python main.py").strip()

    SHELL_CHARS = (";", "&", "|", ">", "<", "`", "$", "(", ")", "{", "}")
    if any(c in raw_command for c in SHELL_CHARS):
        raise HTTPException(400, "Shell metacharacters are not allowed.")

    _args_check = shlex.split(raw_command)
    ALLOWED_EXECUTABLES = {"python", "python3", "node", "npm"}
    if not _args_check or _args_check[0] not in ALLOWED_EXECUTABLES:
        raise HTTPException(400, "Only python/node commands are allowed.")

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
