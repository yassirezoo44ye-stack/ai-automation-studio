"""
Driver: Node.js projects.

All package manager logic has been extracted into app.execution.js_runtime.
This driver is a thin orchestrator that:
  1. Validates the workspace
  2. Installs dependencies if missing
  3. Delegates server start / build / script execution to RuntimeManager
  4. Emits structured SSE events understood by the frontend
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path
from typing import Optional

from app.execution import process_mgr
from app.execution.js_runtime import (
    JsRuntimeError,
    PackageManagerNotFound,
    ScriptNotFound,
    runtime_manager,
)
from app.runtime import registry
from app.runtime import process as rt_process

_SERVER_PROJECT_TYPES = {"express", "koa", "nestjs", "node"}
_BUILD_PROJECT_TYPES  = {"react", "vue", "svelte", "vite", "nextjs", "nuxt"}
_ALL_NODE_TYPES       = _SERVER_PROJECT_TYPES | _BUILD_PROJECT_TYPES | {"node_app"}


def can_handle(info) -> bool:
    if info.run_strategy not in ("node", "npm") and info.project_type not in _ALL_NODE_TYPES:
        return False
    return registry.has("node") or registry.has("npm")


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    # ── Step 1: Environment probe — stream direct evidence to the client ──────
    probe = runtime_manager.probe(ws)
    for line in probe.as_log_lines():
        yield _ev("log", stream="stdout", line=line, ts=round(time.time(), 3))

    # ── Step 2: External services check ───────────────────────────────────────
    report = runtime_manager.validate(ws)
    if report.diagnostics.get("external_services"):
        services = report.diagnostics["external_services"]
        yield _ev("unsupported",
                  project_type=info.project_type,
                  error=f"Requires external services not available in sandbox: {', '.join(services)}",
                  details=(
                      "Projects that depend on databases or message queues must be run locally.\n"
                      "Download the ZIP and run: docker compose up"
                  ),
                  local_run_hint="docker compose up",
                  fix=["Download the ZIP and run locally with Docker", "docker compose up"])
        return

    # ── Step 3: Install dependencies — stream every line, hard-stop on failure ─
    if (ws / "package.json").exists() and not (ws / "node_modules").exists():
        install_result = None

        async for stream_name, line, sentinel in runtime_manager.install(ws):
            if sentinel is not None:
                # Final sentinel — InstallResult object
                install_result = sentinel
                break
            # Emit EVERY line — no truncation, no filtering
            yield _ev("log", stream=stream_name, line=line, ts=round(time.time(), 3))

        # ── Step 4: STOP on failure — never continue to server start ──────────
        if install_result is None or not install_result.success:
            rc = install_result.exit_code if install_result else -1
            nm_exists = (ws / "node_modules").exists()

            if not nm_exists:
                # Complete failure — emit full stderr so the real error is visible
                failure_lines = install_result.failure_summary() if install_result else []
                details_lines = [
                    f"exit code  : {rc}",
                    f"pm         : {install_result.pm_name if install_result else 'unknown'}",
                    f"command    : {' '.join(install_result.pm_cmd) if install_result else 'unknown'}",
                    f"node       : {install_result.node_version if install_result else 'unknown'}",
                    f"HOME       : {install_result.home if install_result else 'unknown'}",
                    f"npm cache  : {install_result.npm_cache if install_result else 'unknown'}",
                    "",
                    "── Full npm error output ──",
                    *failure_lines,
                ]
                yield _ev("error",
                          category="dependency_installation",
                          error=f"Dependency installation failed (exit {rc})",
                          details="\n".join(details_lines),
                          fix=[
                              "Download the ZIP and install locally: npm install && npm run dev",
                              "Or use Docker: docker compose up",
                          ],
                          severity="high",
                          recoverable=False)
                return

            # node_modules present but non-zero exit — partial install, warn and continue
            yield _ev("status",
                      message=f"⚠ Install exited {rc} but node_modules exists — continuing with partial install")

    pt = info.project_type

    if pt in _BUILD_PROJECT_TYPES:
        async for chunk in _build_and_serve(project_id, ws, info):
            yield chunk
    elif _looks_like_server(ws) or pt in _SERVER_PROJECT_TYPES:
        async for chunk in _run_server(project_id, ws, info, command_override):
            yield chunk
    else:
        async for chunk in _run_script(ws, info, command_override):
            yield chunk


# ── Sub-strategies ────────────────────────────────────────────────────────────

async def _run_script(ws: Path, info, command_override):
    entry = _find_entry(ws) or "index.js"
    args = ["node", entry]

    yield _ev("status", message=f"▶ {' '.join(args)}", command=" ".join(args),
              project_type=info.project_type)
    start = time.time()

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async for line, code in rt_process.stream_process(args, cwd=ws, merge_stderr=False):
        if code is not None:
            rc = code
            break
        if line.startswith("[stderr] "):
            actual = line[len("[stderr] "):]
            stderr_lines.append(actual)
            yield _ev("log", stream="stderr", line=actual, ts=round(time.time(), 3))
        else:
            stdout_lines.append(line)
            yield _ev("log", stream="stdout", line=line, ts=round(time.time(), 3))
    else:
        rc = 0

    yield _ev("done", exit_code=rc, duration=round(time.time() - start, 2),
              stdout="\n".join(stdout_lines), stderr="\n".join(stderr_lines),
              project_type=info.project_type, command=" ".join(args), success=rc == 0)


async def _run_server(project_id: str, ws: Path, info, command_override):
    port = process_mgr.allocate_port()
    if port is None:
        yield _ev("error", error="No available ports. Stop other running projects.")
        return

    try:
        args = runtime_manager.server_argv(ws, port=port)
    except JsRuntimeError as exc:
        process_mgr._used_ports.discard(port)
        yield _ev("error",
                  category="runtime",
                  error=exc.message,
                  details="\n".join(exc.fix),
                  fix=exc.fix,
                  severity="high",
                  recoverable=False)
        return

    # Log which PM was chosen
    try:
        det = runtime_manager.detect(ws)
        pm_info = f"{det.adapter.name} via {det.method}"
    except JsRuntimeError:
        pm_info = "unknown"

    env = {**os.environ, "PORT": str(port), "NODE_ENV": "development"}
    yield _ev("status",
              message=f"▶ {' '.join(args)}  (port {port}, pm={pm_info})",
              command=" ".join(args), port=port)

    start = time.time()
    try:
        rp = await process_mgr.start_server(
            project_id=project_id, args=args, cwd=str(ws),
            env=env, port=port, project_type=info.project_type,
        )
    except Exception as exc:
        process_mgr._used_ports.discard(port)
        yield _ev("error", error=str(exc), project_type=info.project_type)
        return

    yield _ev("status", message=f"⏳ Waiting for server on :{port}…")

    log_lines: list[str] = []
    ready = False
    deadline = time.time() + 25.0

    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                ready = True
                break
        except OSError:
            pass
        if not rp.alive:
            break
        if rp.process.stdout:
            try:
                line = await asyncio.wait_for(rp.process.stdout.readline(), timeout=0.3)
                if line:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    log_lines.append(decoded)
                    yield _ev("log", stream="stdout", line=decoded, ts=round(time.time(), 3))
            except asyncio.TimeoutError:
                pass
        if rp.process.stderr:
            try:
                line = await asyncio.wait_for(rp.process.stderr.readline(), timeout=0.3)
                if line:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    log_lines.append(decoded)
                    yield _ev("log", stream="stderr", line=decoded, ts=round(time.time(), 3))
            except asyncio.TimeoutError:
                pass
        await asyncio.sleep(0.1)

    if not ready:
        try:
            rp.process.kill()
        except Exception:
            pass
        process_mgr._release(project_id)
        crash_log = "\n".join(log_lines[-20:]) if log_lines else "(no output captured)"
        yield _ev("error",
                  error="Node server failed to start",
                  details=(
                      f"The server did not respond on port {port} within 25 s.\n"
                      f"Last output:\n{crash_log}"
                  ),
                  stderr=crash_log,
                  project_type=info.project_type)
        return

    yield _ev("server_ready",
              preview_url=f"/api/projects/{project_id}/proxy/",
              port=port,
              project_type=info.project_type,
              message=f"✓ Node server ready in {round(time.time() - start, 2)}s — pm={pm_info}",
              command=" ".join(args))


async def _build_and_serve(project_id: str, ws: Path, info):
    for dist_dir in ("dist", "build", "out", ".next/static"):
        candidate = ws / dist_dir
        if candidate.exists():
            for html_name in ("index.html", "404.html"):
                html_path = candidate / html_name
                if html_path.exists():
                    content = html_path.read_text(encoding="utf-8")
                    rel = str(html_path.relative_to(ws)).replace("\\", "/")
                    yield _ev("html", html_content=content, entry_file=rel,
                              project_type=info.project_type,
                              message=f"Serving pre-built output from {dist_dir}/")
                    return

    build_script = runtime_manager.resolve_build_script(ws)
    if build_script:
        try:
            det = runtime_manager.detect(ws)
            yield _ev("status", message=f"🔨 Building with {det.adapter.name} run {build_script}…")
        except JsRuntimeError:
            yield _ev("status", message=f"🔨 Building ({build_script})…")

        try:
            rc, stdout, stderr = await runtime_manager.run_script(ws, build_script)
            log_lines = stdout + stderr
        except (ScriptNotFound, JsRuntimeError) as exc:
            yield _ev("error", error=str(exc), fix=getattr(exc, "fix", []))
            return

        for line in log_lines[-15:]:
            if line.strip():
                yield _ev("log", stream="stdout", line=line, ts=round(time.time(), 3))

        if rc == 0:
            for dist_dir in ("dist", "build", "out"):
                html_path = ws / dist_dir / "index.html"
                if html_path.exists():
                    content = html_path.read_text(encoding="utf-8")
                    yield _ev("html", html_content=content,
                              entry_file=f"{dist_dir}/index.html",
                              project_type=info.project_type,
                              message=f"Build complete — serving {dist_dir}/index.html")
                    return

    yield _ev("unsupported",
              project_type=info.project_type,
              error=f"{info.project_type} requires a build step not available in sandbox",
              details="The build completed but no index.html was found in dist/, build/, or out/.",
              local_run_hint="npm install && npm run dev")


# ── Helpers ───────────────────────────────────────────────────────────────────

_ENTRY_CANDIDATES = (
    "index.js", "server.js", "app.js", "main.js",
    "src/index.js", "src/server.js",
)


def _find_entry(ws: Path) -> Optional[str]:
    for name in _ENTRY_CANDIDATES:
        if (ws / name).exists():
            return name
    return None


def _looks_like_server(ws: Path) -> bool:
    for name in ("server.js", "app.js"):
        p = ws / name
        if p.exists():
            try:
                src = p.read_text(encoding="utf-8")
                return "listen(" in src or "express()" in src.lower()
            except Exception:
                pass
    return False


def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"
