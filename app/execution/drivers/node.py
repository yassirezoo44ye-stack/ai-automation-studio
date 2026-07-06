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
        try:
            pm = _resolve_package_manager(ws)
            yield _ev("status", message=f"📦 Installing dependencies with {pm.name}…")
            ok, install_log = await _npm_install(ws)
            if not ok:
                for line in install_log[-5:]:
                    if line.strip():
                        yield _ev("log", stream="stderr", line=line, ts=round(time.time(), 3))
                yield _ev("status", message=f"⚠ {pm.name} install had errors — continuing…")
        except RuntimeExecutorError as e:
            yield _ev("error",
                      category="runtime",
                      error="No package manager available",
                      details="\n".join(e.last_output),
                      fix=["Download the ZIP and run locally: npm install && npm run dev"],
                      severity="high",
                      recoverable=False)
            return

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


# ── Runtime Executor — Package Manager Resolution ─────────────────────────────
#
# Step 1: Detect package manager from lockfile
#   pnpm-lock.yaml    → pnpm
#   yarn.lock         → yarn
#   package-lock.json → npm
#
# Step 2: Verify the detected executable exists
#
# Step 3: Execute  pnpm run <script> | yarn <script> | npm run <script>
#
# Step 4: If npm executable is broken → node <npm-cli.js> run <script>
#
# Step 5: All managers fail → structured RuntimeError

import subprocess as _subprocess
import os as _os
from dataclasses import dataclass


@dataclass
class _PM:
    name: str
    cmd: list[str]

    def install_args(self) -> list[str]:
        if self.name == "yarn":
            return [*self.cmd, "install", "--non-interactive", "--ignore-scripts"]
        return [*self.cmd, "install", "--ignore-scripts", "--prefer-offline"]

    def run_args(self, script: str) -> list[str]:
        if self.name == "yarn":
            return [*self.cmd, script]
        return [*self.cmd, "run", script]


class RuntimeExecutorError(Exception):
    """Raised when no package manager can execute the requested script."""
    def __init__(self, tried: list[str], last_output: list[str]):
        self.tried = tried
        self.last_output = last_output
        super().__init__(f"All package managers failed: {tried}")


def _detect_pm_from_lockfile(ws: Path) -> Optional[str]:
    """Step 1: detect PM name from lockfile presence."""
    if (ws / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (ws / "yarn.lock").exists():
        return "yarn"
    if (ws / "package-lock.json").exists():
        return "npm"
    return None


def _verify_executable(name: str) -> bool:
    """Step 2: verify the executable is present and functional."""
    try:
        r = _subprocess.run([name, "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _npm_cli_fallback() -> Optional[list[str]]:
    """Step 4: find npm-cli.js for when the npm binary is broken."""
    for cli in (
        "/usr/local/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/share/npm/bin/npm-cli.js",
        "/opt/homebrew/lib/node_modules/npm/bin/npm-cli.js",
    ):
        if _os.path.exists(cli):
            return ["node", cli]
    return None


def _resolve_package_manager(ws: Path) -> _PM:
    """Steps 1–4: detect, verify, and fall back to get a working PM."""
    # Step 1: lockfile detection → preferred order
    preferred = _detect_pm_from_lockfile(ws)

    candidates = []
    if preferred:
        candidates.append(preferred)
    # Always append the others as fallbacks
    for name in ("pnpm", "yarn", "npm"):
        if name not in candidates:
            candidates.append(name)

    # Steps 2–3: try each candidate
    for name in candidates:
        if _verify_executable(name):
            return _PM(name=name, cmd=[name])

    # Step 4: npm binary broken → node + npm-cli.js
    cli = _npm_cli_fallback()
    if cli:
        return _PM(name="npm-cli", cmd=cli)

    # Step 5 will be triggered by the caller when this raises
    raise RuntimeExecutorError(
        tried=candidates,
        last_output=["No package manager found: tried pnpm, yarn, npm, npm-cli.js"],
    )


async def _npm_install(ws: Path) -> tuple[bool, list[str]]:
    """Install dependencies using the resolved package manager."""
    try:
        pm = _resolve_package_manager(ws)
    except RuntimeExecutorError as e:
        return False, e.last_output

    rc, out, err = await rt_process.run_process(
        pm.install_args(), cwd=ws, timeout=120.0,
    )
    return rc == 0, out + err


async def _npm_run(ws: Path, script: str) -> tuple[bool, list[str]]:
    """Run a package.json script using the resolved package manager."""
    try:
        pm = _resolve_package_manager(ws)
    except RuntimeExecutorError as e:
        return False, e.last_output

    rc, out, err = await rt_process.run_process(
        pm.run_args(script), cwd=ws, timeout=180.0,
    )
    return rc == 0, [l for l in (out + err) if l.strip()]


def _server_command(ws: Path, port: int) -> list[str]:
    """Return the command to start the dev/production server."""
    pkg_json = ws / "package.json"
    if not pkg_json.exists():
        entry = _find_node_entry(ws)
        return ["node", entry or "index.js"]

    try:
        pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {})

        pm = _resolve_package_manager(ws)

        if "start" in scripts:
            return pm.run_args("start")
        if "dev" in scripts:
            args = pm.run_args("dev")
            # Inject host/port flags for Vite-based projects
            if pm.name in ("npm", "npm-cli"):
                args += ["--", "--host", "0.0.0.0", "--port", str(port)]
            return args
    except RuntimeExecutorError:
        pass
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
