"""
Driver: Node.js projects — requires node/npm in the runtime registry.

Handles:
  - Express/Koa/NestJS/generic server apps → starts server, proxy via process_mgr
  - React/Vue/Vite/Next.js → npm run build → serve dist/index.html as static HTML
  - Plain node scripts → streams stdout/stderr
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path
from typing import Optional

from app.execution import process_mgr, registry

_SERVER_PROJECT_TYPES = {"express", "koa", "nestjs", "node"}
_BUILD_PROJECT_TYPES  = {"react", "vue", "svelte", "vite", "nextjs", "nuxt"}
_ALL_NODE_TYPES = _SERVER_PROJECT_TYPES | _BUILD_PROJECT_TYPES | {"node_app"}


def can_handle(info) -> bool:
    if info.run_strategy not in ("node", "npm") and info.project_type not in _ALL_NODE_TYPES:
        return False
    return registry.has("node") or registry.has("npm")


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    # Install node_modules if package.json present and node_modules absent
    if (ws / "package.json").exists() and not (ws / "node_modules").exists():
        if registry.has("npm"):
            yield _ev("status", message="📦 npm install --ignore-scripts…")
            ok, install_log = await _npm_install(ws)
            if not ok:
                for line in install_log[-5:]:
                    if line.strip():
                        yield _ev("log", stream="stderr", line=line, ts=round(time.time(), 3))
                yield _ev("status", message="⚠ npm install had errors — continuing…")

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
    entry = _find_node_entry(ws) or "index.js"
    args = ["node", entry]

    yield _ev("status", message=f"▶ {' '.join(args)}", command=" ".join(args),
              project_type=info.project_type)
    start = time.time()

    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(ws),
            env={**os.environ},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        yield _ev("error", error=str(e), project_type=info.project_type)
        return

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    q: asyncio.Queue = asyncio.Queue()

    async def pump(sr: asyncio.StreamReader, name: str) -> None:
        async for raw in sr:
            await q.put((name, raw.decode("utf-8", errors="replace").rstrip()))
        await q.put((name, None))

    t1 = asyncio.create_task(pump(proc.stdout, "stdout"))
    t2 = asyncio.create_task(pump(proc.stderr, "stderr"))
    deadline = time.time() + 60
    done_count = 0

    while done_count < 2:
        remaining = deadline - time.time()
        if remaining <= 0:
            proc.terminate()
            break
        try:
            name, line = await asyncio.wait_for(q.get(), timeout=min(0.5, remaining))
        except asyncio.TimeoutError:
            if proc.returncode is not None:
                break
            continue
        if line is None:
            done_count += 1
        else:
            (stdout_lines if name == "stdout" else stderr_lines).append(line)
            yield _ev("log", stream=name, line=line, ts=round(time.time(), 3))

    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        proc.kill()
    t1.cancel()
    t2.cancel()

    rc = proc.returncode if proc.returncode is not None else -1
    yield _ev("done", exit_code=rc, duration=round(time.time() - start, 2),
              stdout="\n".join(stdout_lines), stderr="\n".join(stderr_lines),
              project_type=info.project_type, command=" ".join(args), success=rc == 0)


async def _run_server(project_id: str, ws: Path, info, command_override):
    port = process_mgr.allocate_port()
    if port is None:
        yield _ev("error", error="No available ports. Stop other running projects.")
        return

    args = _server_command(ws, port)
    env = {**os.environ, "PORT": str(port), "NODE_ENV": "development"}
    yield _ev("status", message=f"▶ {' '.join(args)}  (port {port})",
              command=" ".join(args), port=port)

    start = time.time()
    try:
        rp = await process_mgr.start_server(
            project_id=project_id, args=args, cwd=str(ws),
            env=env, port=port, project_type=info.project_type,
        )
    except Exception as e:
        process_mgr._used_ports.discard(port)
        yield _ev("error", error=str(e), project_type=info.project_type)
        return

    yield _ev("status", message=f"⏳ Waiting for server on :{port}…")
    ready = await _wait_ready(rp, port, timeout=20.0)

    if not ready:
        stderr_text = ""
        try:
            out, err = await asyncio.wait_for(rp.process.communicate(), timeout=2.0)
            stderr_text = (err or b"").decode("utf-8", errors="replace")
        except Exception:
            try:
                rp.process.kill()
            except Exception:
                pass
        process_mgr._release(project_id)
        yield _ev("error",
                  error="Node server failed to start",
                  details=f"Port {port} did not respond within 20 s. Check that the app listens on process.env.PORT.",
                  stderr=stderr_text,
                  project_type=info.project_type)
        return

    yield _ev("server_ready",
              preview_url=f"/api/projects/{project_id}/proxy/",
              port=port,
              project_type=info.project_type,
              message=f"✓ Node server ready in {round(time.time() - start, 2)}s",
              command=" ".join(args))


async def _build_and_serve(project_id: str, ws: Path, info):
    """Try to serve a pre-built dist/, or npm run build first."""
    # Look for pre-built output
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

    # Attempt npm run build
    if registry.has("npm"):
        yield _ev("status", message="🔨 Building with npm run build…")
        ok, log_lines = await _npm_run(ws, "build")
        for line in log_lines[-15:]:
            if line.strip():
                yield _ev("log", stream="stdout", line=line, ts=round(time.time(), 3))

        if ok:
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
              error=f"{info.project_type} requires a build step not yet available",
              details="The project built but no index.html was found in dist/, build/, or out/.",
              local_run_hint="npm install && npm run dev")


# ── Utilities ─────────────────────────────────────────────────────────────────

async def _npm_install(ws: Path) -> tuple[bool, list[str]]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", "--ignore-scripts",
            cwd=str(ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        lines = (out + err).decode("utf-8", errors="replace").splitlines()
        return proc.returncode == 0, lines
    except Exception as e:
        return False, [str(e)]


async def _npm_run(ws: Path, script: str) -> tuple[bool, list[str]]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "run", script,
            cwd=str(ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180.0)
        lines = (out + err).decode("utf-8", errors="replace").splitlines()
        return proc.returncode == 0, [l for l in lines if l.strip()]
    except Exception as e:
        return False, [str(e)]


def _server_command(ws: Path, port: int) -> list[str]:
    pkg_json = ws / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            if "start" in scripts:
                return ["npm", "start"]
            if "dev" in scripts:
                return ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", str(port)]
        except Exception:
            pass
    entry = _find_node_entry(ws)
    return ["node", entry or "index.js"]


def _find_node_entry(ws: Path) -> Optional[str]:
    for name in ("index.js", "server.js", "app.js", "main.js",
                 "src/index.js", "src/server.js"):
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


async def _wait_ready(rp, port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            pass
        if not rp.alive:
            return False
        await asyncio.sleep(0.25)
    return False


def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"
