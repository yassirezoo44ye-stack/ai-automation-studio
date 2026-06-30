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
    """
    Smart project runner. Auto-detects project type and chooses the right
    execution strategy. Always returns structured JSON — never a bare HTTP 4xx
    without an explanation.
    """
    import logging
    import shlex

    log = logging.getLogger(__name__)
    ws = workspace(project_id)

    if not ws.exists():
        return _run_error(
            "Workspace not found",
            f"No workspace directory exists for project '{project_id}'. "
            "Try rebuilding the project.",
            project_type="unknown",
            workspace=str(ws),
        )

    workspace_files: list[str] = sorted(
        str(p.relative_to(ws)).replace("\\", "/")
        for p in ws.rglob("*") if p.is_file()
    )

    if not workspace_files:
        return _run_error(
            "Empty workspace",
            "No files found in the project workspace. Build the project first.",
            project_type="unknown",
            workspace=str(ws),
            checked_files=[],
        )

    # ── Validate user-supplied command ────────────────────────────────────────
    _SHELL_CHARS = frozenset(";& |><`$(){}\\")
    _ALLOWED_EXE = {"python", "python3"}  # only Python guaranteed in production image

    raw_command = (body.command or "").strip()
    if raw_command:
        bad = [c for c in raw_command if c in _SHELL_CHARS]
        if bad:
            return _run_error(
                "Shell metacharacters are not allowed",
                f"Command contains forbidden characters: {bad}",
                project_type="unknown",
                workspace=str(ws),
                checked_files=workspace_files,
            )
        args = shlex.split(raw_command)
        if args and args[0] not in _ALLOWED_EXE:
            # Fall through to auto-detection; ignore non-Python command
            log.warning("run_project: ignoring unsupported command %r, auto-detecting", raw_command)
            raw_command = ""

    # ── Auto-detect project type ───────────────────────────────────────────────
    fset = set(workspace_files)
    detected_type, detected_cmd = _detect_project(ws, fset)

    if not raw_command:
        raw_command = detected_cmd or ""

    log.info("run_project: project=%s type=%s files=%d cmd=%r",
             project_id, detected_type, len(workspace_files), raw_command)

    # ── HTML project → return content for browser preview ─────────────────────
    if detected_type == "html" and not raw_command:
        return _serve_html(ws, fset, workspace_files, project_id)

    # ── Server framework → cannot run inside sandbox ───────────────────────────
    if detected_type in ("flask", "fastapi", "django", "express", "vite") and not raw_command:
        return {
            "success": False,
            "type": "server_app",
            "project_type": detected_type,
            "error": "Server application detected",
            "details": (
                f"This is a {detected_type.title()} server app. "
                "Long-running servers cannot be started inside this sandbox. "
                "Download the ZIP and run it locally with: "
                + (_server_run_hint(detected_type, fset))
            ),
            "stdout": "", "stderr": "", "returncode": -1,
            "command": "",
            "workspace": str(ws),
            "checked_files": workspace_files,
        }

    # ── Nothing runnable found ─────────────────────────────────────────────────
    if not raw_command:
        return _run_error(
            "No runnable entry point found",
            "Could not determine how to run this project. "
            "Add a main.py, app.py, or index.html file, "
            "or type a command manually (e.g. python main.py).",
            project_type=detected_type,
            workspace=str(ws),
            checked_files=workspace_files,
        )

    # ── Execute ────────────────────────────────────────────────────────────────
    args = shlex.split(raw_command)
    try:
        proc = subprocess.run(
            args, shell=False, cwd=str(ws),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        result: dict = {
            "success": True,
            "type": "terminal",
            "project_type": detected_type,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "command": raw_command,
        }
        # Surface a helpful warning if the script has no output at all
        if not proc.stdout.strip() and not proc.stderr.strip() and proc.returncode == 0:
            result["warning"] = (
                "Program exited successfully with no output. "
                "If you expected output, check that your script calls print()."
            )
        return result
    except subprocess.TimeoutExpired:
        return _run_error(
            "Execution timed out (30 s)",
            "The script ran for 30 seconds without finishing. "
            "This usually means it started a server (which cannot be served here) "
            "or entered an infinite loop. Download and run it locally.",
            project_type=detected_type,
            workspace=str(ws),
            checked_files=workspace_files,
            status=408,
        )
    except FileNotFoundError:
        return _run_error(
            f"Executable not found: {args[0]}",
            f"'{args[0]}' is not installed in this environment. "
            "Only Python is available. Download and run Node/npm projects locally.",
            project_type=detected_type,
            workspace=str(ws),
            checked_files=workspace_files,
        )
    except Exception as exc:
        log.exception("run_project unexpected error: %s", exc)
        return _run_error(
            "Unexpected execution error",
            str(exc),
            project_type=detected_type,
            workspace=str(ws),
            checked_files=workspace_files,
            status=500,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _detect_project(ws: Path, fset: set[str]) -> tuple[str, str]:
    """
    Returns (project_type, run_command).
    run_command="" means the caller must handle it (e.g. html preview).
    """
    has_py   = any(f.endswith(".py")   for f in fset)
    has_html = any(f.endswith(".html") for f in fset)
    has_pkg  = "package.json" in fset

    # ── Server framework detection ─────────────────────────────────────────
    if "requirements.txt" in fset:
        reqs = (ws / "requirements.txt").read_text(encoding="utf-8").lower()
        if "fastapi" in reqs or "uvicorn" in reqs:
            return "fastapi", ""
        if "flask" in reqs:
            return "flask", ""
        if "django" in reqs:
            return "django", ""

    if has_pkg:
        try:
            import json as _j
            pkg = _j.loads((ws / "package.json").read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "vite" in deps or "react" in deps or "vue" in deps:
                return "vite", ""
            if "express" in deps or "koa" in deps:
                return "express", ""
        except Exception:
            pass

    # ── Runnable Python scripts ────────────────────────────────────────────
    for fname in ("main.py", "app.py", "server.py", "run.py", "cli.py", "solution.py", "index.py"):
        if fname in fset:
            return "python", f"python {fname}"

    # Any .py file (pick the non-test, non-setup one)
    py_files = [
        f for f in sorted(fset)
        if f.endswith(".py") and not any(x in f for x in ("test", "setup", "conf", "__"))
    ]
    if py_files:
        return "python", f"python {py_files[0]}"

    # ── HTML-only project ──────────────────────────────────────────────────
    if has_html and not has_py and not has_pkg:
        return "html", ""

    # ── Node bare scripts ──────────────────────────────────────────────────
    if has_pkg:
        for fname in ("index.js", "main.js", "server.js", "app.js"):
            if fname in fset:
                return "node", f"node {fname}"
        return "node", ""

    # ── HTML with other assets ─────────────────────────────────────────────
    if has_html:
        return "html", ""

    return "unknown", ""


def _serve_html(ws: Path, fset: set[str], workspace_files: list[str], project_id: str) -> dict:
    """Return HTML content so the frontend can render it in an iframe."""
    entry = next(
        (f for f in ("index.html",) if f in fset),
        next((f for f in workspace_files if f.endswith(".html")), None),
    )
    if not entry:
        return _run_error(
            "No HTML file found",
            "Project was detected as HTML but no .html file exists in the workspace.",
            project_type="html",
            workspace=str(ws),
            checked_files=workspace_files,
        )
    content = (ws / entry).read_text(encoding="utf-8")
    return {
        "success": True,
        "type": "html",
        "project_type": "html",
        "html_content": content,
        "entry_file": entry,
        "command": f"preview {entry}",
        "stdout": f"Opening {entry} in browser preview…",
        "stderr": "",
        "returncode": 0,
    }


def _server_run_hint(project_type: str, fset: set[str]) -> str:
    hints = {
        "fastapi": "uvicorn main:app --reload",
        "flask":   "python app.py",
        "django":  "python manage.py runserver",
        "express": "npm start",
        "vite":    "npm run dev",
    }
    return hints.get(project_type, "see README.md for instructions")


def _run_error(error: str, details: str, *, project_type: str,
               workspace: str = "", checked_files: list | None = None,
               status: int = 400) -> dict:
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content={
        "success": False,
        "type": "error",
        "error": error,
        "details": details,
        "project_type": project_type,
        "workspace": workspace,
        "checked_files": checked_files or [],
        "stdout": "", "stderr": "", "returncode": -1,
        "command": "",
    })
