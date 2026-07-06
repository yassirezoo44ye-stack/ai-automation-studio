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

from app.execution import process_mgr
from app.runtime import registry
from app.runtime import process as rt_process

_SERVER_PROJECT_TYPES = {"express", "koa", "nestjs", "node"}
_BUILD_PROJECT_TYPES  = {"react", "vue", "svelte", "vite", "nextjs", "nuxt"}
_ALL_NODE_TYPES = _SERVER_PROJECT_TYPES | _BUILD_PROJECT_TYPES | {"node_app"}


def can_handle(info) -> bool:
    if info.run_strategy not in ("node", "npm") and info.project_type not in _ALL_NODE_TYPES:
        return False
    return registry.has("node") or registry.has("npm")


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    # Check for projects that need external services (DB, cache, etc.)
    missing = _check_external_services(ws)
    if missing:
        yield _ev("unsupported",
                  project_type=info.project_type,
                  error=f"This project requires external services not available in the sandbox: {', '.join(missing)}",
                  details=(
                      "Projects that depend on databases or message queues must be run locally.\n"
                      "Download the ZIP and run with: docker compose up"
                  ),
                  local_run_hint="docker compose up",
                  fix=["Download the ZIP and run locally with Docker", "docker compose up"])
        return

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

    # Stream server output while waiting — user sees exactly why it fails
    log_lines: list[str] = []
    ready = False
    deadline = time.time() + 25.0

    async def _read_pipe(pipe):
        if pipe is None:
            return
        try:
            while True:
                line = await asyncio.wait_for(pipe.readline(), timeout=1.0)
                if not line:
                    break
                log_lines.append(line.decode("utf-8", errors="replace").rstrip())
        except (asyncio.TimeoutError, Exception):
            pass

    while time.time() < deadline:
        # Check port
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                ready = True
                break
        except OSError:
            pass
        if not rp.alive:
            break
        # Drain any output
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

_EXTERNAL_SERVICE_DEPS: dict[str, str] = {
    "pg": "PostgreSQL", "pg-pool": "PostgreSQL", "mysql": "MySQL",
    "mysql2": "MySQL", "mongoose": "MongoDB", "mongodb": "MongoDB",
    "redis": "Redis", "ioredis": "Redis", "bullmq": "Redis/BullMQ",
    "bull": "Redis/Bull", "prisma": "Database (Prisma)",
    "@prisma/client": "Database (Prisma)", "typeorm": "Database (TypeORM)",
    "sequelize": "Database (Sequelize)", "knex": "Database (Knex)",
    "amqplib": "RabbitMQ", "kafkajs": "Kafka",
}


def _check_external_services(ws: Path) -> list[str]:
    """Return list of external services required by the project, or empty list if none."""
    pkg_json = ws / "package.json"
    if not pkg_json.exists():
        return []
    try:
        pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        found: dict[str, str] = {}
        for dep, service in _EXTERNAL_SERVICE_DEPS.items():
            if dep in all_deps:
                found[service] = service
        return list(found.values())
    except Exception:
        return []


# ── Package manager resolution (permanent fix for broken npm binaries) ────────
#
# On Render free-tier, /usr/local/bin/npm crashes immediately with
# MODULE_NOT_FOUND because /usr/local/lib/node_modules/npm/ is absent.
# Strategy (tried in order):
#   1. yarn   — often installed alongside Node.js via corepack
#   2. pnpm   — lightweight, sometimes available
#   3. node + npm-cli.js  — bypasses the broken shell wrapper
#   4. npm binary  — last resort
#
# For running scripts, we also parse package.json and execute the raw
# command directly via node_modules/.bin, completely bypassing any
# package manager for the run step.

import subprocess as _subprocess

def _find_package_manager() -> tuple[str, list[str]]:
    """Return (name, cmd_prefix) for the best available package manager."""
    import os as _os

    # yarn
    try:
        r = _subprocess.run(["yarn", "--version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return "yarn", ["yarn"]
    except Exception:
        pass

    # pnpm
    try:
        r = _subprocess.run(["pnpm", "--version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return "pnpm", ["pnpm"]
    except Exception:
        pass

    # node + npm-cli.js (bypasses broken /usr/local/bin/npm wrapper)
    for cli in (
        "/usr/local/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/share/npm/bin/npm-cli.js",
    ):
        if _os.path.exists(cli):
            return "npm-cli", ["node", cli]

    # npm binary — last resort
    return "npm", ["npm"]


def _extract_script_command(ws: Path, script_name: str, port: int) -> Optional[list[str]]:
    """Parse package.json and return the raw command for script_name.

    Tries to run it via node_modules/.bin directly, completely bypassing
    any package manager for the execution step.
    Returns None if the script cannot be resolved to a direct command.
    """
    import shlex as _shlex
    pkg_json = ws / "package.json"
    if not pkg_json.exists():
        return None
    try:
        pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        raw = pkg.get("scripts", {}).get(script_name)
        if not raw:
            return None

        # Substitute port placeholders
        raw = raw.replace("$PORT", str(port)).replace("${PORT}", str(port))

        parts = _shlex.split(raw)
        if not parts:
            return None

        executable = parts[0]

        # Resolve via node_modules/.bin first
        bin_path = ws / "node_modules" / ".bin" / executable
        if bin_path.exists():
            return [str(bin_path)] + parts[1:]

        # Known safe executables that can be called directly
        _SAFE = {"node", "nodemon", "ts-node", "tsx", "vite", "next", "nuxt",
                 "svelte-kit", "astro", "remix", "express", "fastify"}
        if executable in _SAFE:
            return parts

    except Exception:
        pass
    return None


async def _install_deps(ws: Path) -> tuple[bool, list[str]]:
    """Install node_modules using the best available package manager."""
    pm_name, pm_cmd = _find_package_manager()
    if pm_name == "yarn":
        args = [*pm_cmd, "install", "--non-interactive", "--ignore-scripts"]
    elif pm_name == "pnpm":
        args = [*pm_cmd, "install", "--ignore-scripts", "--prefer-offline"]
    else:
        args = [*pm_cmd, "install", "--ignore-scripts", "--prefer-offline"]

    rc, out, err = await rt_process.run_process(args, cwd=ws, timeout=120.0)
    return rc == 0, out + err


async def _npm_install(ws: Path) -> tuple[bool, list[str]]:
    return await _install_deps(ws)


async def _npm_run(ws: Path, script: str) -> tuple[bool, list[str]]:
    _, pm_cmd = _find_package_manager()
    if pm_cmd[0] == "yarn":
        args = [*pm_cmd, script]
    else:
        args = [*pm_cmd, "run", script]
    rc, out, err = await rt_process.run_process(args, cwd=ws, timeout=180.0)
    return rc == 0, [l for l in (out + err) if l.strip()]


def _server_command(ws: Path, port: int) -> list[str]:
    # 1. Try to resolve the raw script command (no package manager needed)
    for script_name in ("start", "dev"):
        direct = _extract_script_command(ws, script_name, port)
        if direct:
            return direct

    # 2. Fall back to package manager
    pkg_json = ws / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            _, pm_cmd = _find_package_manager()
            pm = pm_cmd[0]
            if "start" in scripts:
                return [*pm_cmd, "start"] if pm != "yarn" else [*pm_cmd, "start"]
            if "dev" in scripts:
                if pm == "yarn":
                    return [*pm_cmd, "dev"]
                return [*pm_cmd, "run", "dev", "--", "--host", "0.0.0.0", "--port", str(port)]
        except Exception:
            pass

    # 3. Last resort: run entry file directly
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
