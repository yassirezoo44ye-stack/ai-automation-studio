import asyncio
import io
import json
import logging
import shutil
import time
import zipfile
from pathlib import Path
from typing import Optional

import anthropic
import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import USER_ID
from app.core.db import get_pool
from app.core.filesystem import workspace, safe_path
from app.core.helpers import (
    get_ai_client, get_async_ai_client,
    resolve_project_id, anthropic_error_message, strip_fences,
)
from app.core.security import ai_rate_limit
from app.execution import process_mgr
from app.execution.runner import run_stream, run_sync

log = logging.getLogger(__name__)

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

BUILD_UNIFIED_SYSTEM = """You are a senior full-stack software engineer.
Build a complete, production-quality, runnable project for the user's request.

Output EVERY file using EXACTLY this format — no deviations, no preamble:

<<<FILE: relative/path/to/file.ext>>>
[complete file content — no fences, no truncation, no placeholder comments]
<<<ENDFILE>>>

Rules:
- Start immediately with the first <<<FILE: ...>>> line — no introduction.
- Write EVERY file the project needs end-to-end (entry point, dependencies, README.md, .env.example if needed).
- Use relative paths only (e.g. src/main.py, not /app/src/main.py).
- Write COMPLETE file content — never use "..." or "# add more here".
- Write clean, secure code: validate inputs, parameterise SQL, escape output.
- For simple projects: one index.html with inline CSS/JS is fine.
- For Python: include requirements.txt when 3rd-party packages are needed.
- For Node: include package.json with all dependencies listed.

After ALL files, append metadata on its own line (no extra text):
<<<META>>>
{"description":"one line","run_command":"e.g. python main.py","language":"primary language"}
<<<ENDMETA>>>
"""

BUILD_MAX_FILES = 30


class _BuildParser:
    """
    Line-by-line state machine that parses the Claude stream.

    Transitions:
      preamble  →  in_file  (on <<<FILE: path>>>)
      in_file   →  preamble (on <<<ENDFILE>>>, emits file_done)
      preamble  →  in_meta  (on <<<META>>>)
      in_meta   →  done     (on <<<ENDMETA>>>, emits meta_done)
    """

    def __init__(self):
        self.state = "preamble"
        self.current_path = ""
        self.content_lines: list[str] = []
        self.meta_lines: list[str] = []
        self.completed_files: list[str] = []

    def feed(self, line: str):
        """Return (event_type, data) or None."""
        if self.state == "preamble":
            if line.startswith("<<<FILE: ") and line.endswith(">>>"):
                self.current_path = line[9:-3].strip()
                self.content_lines = []
                self.state = "in_file"
                return ("file_start", self.current_path)
            if line.strip() == "<<<META>>>":
                self.meta_lines = []
                self.state = "in_meta"
        elif self.state == "in_file":
            if line.strip() == "<<<ENDFILE>>>":
                content = "\n".join(self.content_lines)
                path = self.current_path
                self.completed_files.append(path)
                self.state = "preamble"
                return ("file_done", (path, content))
            self.content_lines.append(line)
        elif self.state == "in_meta":
            if line.strip() == "<<<ENDMETA>>>":
                self.state = "done"
                return ("meta_done", "\n".join(self.meta_lines))
            self.meta_lines.append(line)
        return None


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
    """
    Single-call async streaming build.

    Root-cause fix for "No files yet":
      - AsyncAnthropic: async for text in stream.text_stream yields control to
        the event loop between tokens — event loop NEVER blocks.
      - Single LLM call: no N+1 round-trips that allow the proxy to time out.
      - Parses <<<FILE: path>>> / <<<ENDFILE>>> delimiters in real-time.
      - Writes each file and emits its SSE event the moment <<<ENDFILE>>> arrives.
      - Heartbeat every 15 s keeps the Render proxy alive.
    """
    ai_rate_limit(request, max_calls=10, window=60)

    async def event_stream():
        try:
            yield _sse("status", message="🤖 Connecting to Claude…")

            ai = get_async_ai_client()
            parser = _BuildParser()
            ws = workspace(req.project_id)
            buf = ""
            last_heartbeat = time.time()

            async with ai.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system=BUILD_UNIFIED_SYSTEM,
                messages=[{"role": "user", "content": req.prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    buf += text

                    # Heartbeat — prevents Render/nginx idle-timeout on long builds
                    now = time.time()
                    if now - last_heartbeat > 15:
                        yield _sse("heartbeat", ts=round(now, 1))
                        last_heartbeat = now

                    # Process complete lines from buffer
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        event = parser.feed(line)
                        if event is None:
                            continue
                        etype, data = event
                        if etype == "file_start":
                            yield _sse("status", message=f"✍️ Writing {data}…")
                        elif etype == "file_done":
                            path, content = data
                            dest = safe_path(ws, path)
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            await asyncio.to_thread(dest.write_text, content, "utf-8")
                            yield _sse("file", path=path, content=content)

            # Flush remaining buffer (last line without trailing newline)
            if buf.strip():
                event = parser.feed(buf)
                if event and event[0] == "file_done":
                    path, content = event[1]
                    dest = safe_path(ws, path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(dest.write_text, content, "utf-8")
                    yield _sse("file", path=path, content=content)

            if not parser.completed_files:
                yield _sse("error",
                           message="Claude did not produce any files. Try rephrasing your request.")
                return

            meta: dict = {}
            if parser.meta_lines:
                try:
                    meta = json.loads("\n".join(parser.meta_lines))
                except Exception:
                    pass

            yield _sse("done",
                       description=meta.get("description", ""),
                       files=parser.completed_files,
                       run_command=meta.get("run_command", ""),
                       language=meta.get("language", ""))

            try:
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        "INSERT INTO usage_logs (user_id, action, details) VALUES ($1,'build',$2)",
                        USER_ID,
                        json.dumps({"prompt": req.prompt[:80], "files": parser.completed_files}),
                    )
            except Exception:
                pass

        except anthropic.BadRequestError as e:
            yield _sse("error", message=anthropic_error_message(e))
        except Exception as e:
            log.exception("build_stream error")
            yield _sse("error", message=str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"


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


@router.post("/api/projects/{project_id}/run/stream")
async def run_project_stream(project_id: str, body: RunRequest2, request: Request):
    """
    Primary Run endpoint — streams SSE events in real time.

    Event types:
      status        — progress update
      log           — one line of stdout/stderr
      html          — static HTML (frontend renders blob URL)
      server_ready  — server started; preview_url = /api/projects/{id}/proxy/
      unsupported   — project not runnable here, shows local hint
      done          — script finished  {exit_code, duration, stdout, stderr}
      error         — fatal error
    """
    ws = workspace(project_id)

    # Sync any in-memory files that arrived via the request body
    # (body.files is optional — client may have synced already)
    async def event_gen():
        async for chunk in run_stream(project_id, ws, body.command or None):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/projects/{project_id}/run")
async def run_project(project_id: str, body: RunRequest2):
    """
    Sync fallback — collects the stream and returns a single JSON response.
    Used by older clients or if SSE is unavailable.
    """
    ws = workspace(project_id)
    result = await run_sync(project_id, ws, body.command or None)
    # Map SSE event to HTTP status
    if result.get("type") == "error":
        return Response(
            content=json.dumps(result),
            status_code=400,
            media_type="application/json",
        )
    return result


@router.delete("/api/projects/{project_id}/process")
async def stop_project(project_id: str):
    """Kill any running server process for this project."""
    await process_mgr.kill(project_id)
    return {"stopped": project_id}


@router.get("/api/projects/{project_id}/process")
async def project_process_status(project_id: str):
    """Check whether a server process is currently running for this project."""
    rp = process_mgr.get_running(project_id)
    if rp:
        return {
            "running": True,
            "port": rp.port,
            "project_type": rp.project_type,
            "command": " ".join(rp.command),
            "preview_url": f"/api/projects/{project_id}/proxy/",
            "idle_seconds": round(rp.idle_seconds),
        }
    return {"running": False}


@router.api_route(
    "/api/projects/{project_id}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_to_project(project_id: str, path: str, request: Request):
    """
    Reverse proxy: forwards every request to the running server for this project.
    The server listens on an internal port; this route exposes it to the browser.
    """
    rp = process_mgr.get_running(project_id)
    if rp is None:
        raise HTTPException(503, detail={
            "error": "No running server",
            "details": (
                f"No server is running for project '{project_id}'. "
                "Click Run to start it."
            ),
        })

    target = f"http://127.0.0.1:{rp.port}/{path}"
    if request.url.query:
        target += f"?{request.url.query}"

    # Forward headers except hop-by-hop
    _HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate",
                   "proxy-authorization", "te", "trailer", "transfer-encoding",
                   "upgrade", "host"}
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    body_bytes = await request.body()

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.request(
                method=request.method,
                url=target,
                headers=fwd_headers,
                content=body_bytes,
            )
        # Strip hop-by-hop from response headers
        resp_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in _HOP_BY_HOP
        }
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=resp_headers,
        )
    except httpx.ConnectError:
        rp_check = process_mgr.get_running(project_id)
        if rp_check is None:
            raise HTTPException(503, detail={"error": "Server has exited"})
        raise HTTPException(502, detail={"error": "Could not connect to server"})
    except httpx.TimeoutException:
        raise HTTPException(504, detail={"error": "Server request timed out"})
