"""App Builder execution in Vercel microVMs; never fall back to host processes.

Only validated workspace files cross the boundary. Each VM has a hard lifetime,
a deny-by-default network policy and a dedicated preview capability. Handles
are deliberately ephemeral; a backend restart cannot extend a VM's lifetime.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
import json
import io
import logging
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.parse import urlsplit
from types import SimpleNamespace

from app.execution import detector
from app.core.config import WORKSPACES

log = logging.getLogger(__name__)
LIFETIME = 300
MAX_FILES = 1000
MAX_BYTES = 20 * 1024 * 1024
MAX_SESSIONS = 4
ROOT = "/vercel/sandbox/project"
SKIP = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
_sessions: dict[str, Session] = {}
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_capacity = asyncio.Semaphore(MAX_SESSIONS)


class PreviewError(ValueError):
    """An intentional, safe-to-display setup error."""


@dataclass
class Session:
    client: object
    sandbox: object
    preview_url: str | None
    project_type: str
    command: list[str]
    expires_at: float


def valid_preview_url(value: str) -> bool:
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and bool(u.hostname)
                and u.hostname.endswith(".vercel.run") and not u.username
                and not u.password and u.port in (None, 443))
    except ValueError:
        return False


def _trusted_workspace(requested: Path) -> Path:
    """Select a real directory from the configured root, never from request text.

    A caller's path is only a comparison key. Filesystem operations use an
    enumerated child of the trusted storage root. Reject root/child symlinks
    and nested paths, including paths outside that root.
    """
    root = WORKSPACES.resolve()
    requested = requested.absolute()
    for candidate in root.iterdir():
        if candidate.absolute() == requested:
            if candidate.is_symlink() or not candidate.is_dir():
                break
            return candidate
    raise PreviewError("Preview workspace must be an existing project under WORKSPACES_DIR")


def workspace_files(ws: Path) -> list[tuple[str, bytes]]:
    """Bound transfers and reject links; do not copy credentials or dependencies."""
    ws = _trusted_workspace(ws)
    files = []
    total = 0
    for path in sorted(ws.rglob("*")):
        rel = path.relative_to(ws)
        if any(part in SKIP for part in rel.parts):
            continue
        if any(part.startswith(".env") and part != ".env.example" for part in rel.parts):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(ws.resolve()):
            raise PreviewError("Workspace links are not allowed in isolated previews")
        if not path.is_file():
            continue
        size = path.stat().st_size
        if len(files) >= MAX_FILES or total + size > MAX_BYTES:
            raise PreviewError("Preview workspace exceeds the 1000-file / 20 MB limit")
        with path.open("rb") as source:
            data = source.read(MAX_BYTES - total + 1)
        total += len(data)
        if total > MAX_BYTES:
            raise PreviewError("Preview workspace exceeds the 20 MB limit")
        files.append((rel.as_posix(), data))
    return files


def _client():
    # Imported lazily: missing configuration never disables the rest of Flow.
    from vercel.sandbox import SandboxClient, SandboxCredentials, SandboxServiceOptions

    values = [os.getenv(k, "") for k in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID")]
    if not all(values):
        raise PreviewError("Isolated execution is not configured. Set VERCEL_TOKEN, "
                         "VERCEL_TEAM_ID and VERCEL_PROJECT_ID on the backend.")

    async def credentials():
        return SandboxCredentials(token=values[0], team_id=values[1], project_id=values[2])

    return SandboxClient.create(options=SandboxServiceOptions(
        credentials_factory=credentials, request_timeout=timedelta(seconds=20),
        file_transfer_timeout=timedelta(seconds=30),
    ))


def _event(kind: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': kind, **kwargs})}\n\n"


async def stop(project_id: str):
    async with _locks[project_id]:
        session = _sessions.get(project_id)
        if session:
            # Keep the handle if remote deletion fails, allowing a retry.
            await session.sandbox.destroy()
            _sessions.pop(project_id, None)
            try:
                await session.client.aclose()
            finally:
                _capacity.release()


async def status(project_id: str) -> dict:
    session = _sessions.get(project_id)
    if not session:
        return {"running": False}
    if time.monotonic() >= session.expires_at:
        await stop(project_id)
        return {"running": False}
    return {"running": bool(session.preview_url), "port": 3000,
            "project_type": session.project_type, "command": " ".join(session.command),
            "preview_url": session.preview_url, "idle_seconds": 0}


async def cleanup_expired():
    for project_id, session in list(_sessions.items()):
        if time.monotonic() >= session.expires_at:
            try:
                await stop(project_id)
            except Exception:
                log.warning("Could not clean up expired sandbox for %s", project_id)


async def stop_all():
    for project_id in list(_sessions):
        try:
            await stop(project_id)
        except Exception:
            log.warning("Sandbox shutdown cleanup failed; provider lifetime still applies")


class _Output(io.BytesIO):
    """Consume all remote output without allowing it to exhaust API memory."""
    def write(self, data):
        super().write(data[:max(0, 16000 - self.tell())])
        return len(data)


async def _checked(sandbox, command, args, **kwargs):
    stdout, stderr = _Output(), _Output()
    result = await sandbox.run_command(command, args, stdout=stdout, stderr=stderr,
                                       kill_after=90, **kwargs)
    if result.returncode:
        raise PreviewError(f"Preview command failed: {command} (exit {result.returncode})")
    return SimpleNamespace(returncode=result.returncode, stdout=stdout.getvalue(), stderr=stderr.getvalue())


async def stream(project_id: str, ws: Path, command_override: str | None = None):
    """Start one bounded isolated run; retain only successfully started previews."""
    async with _locks[project_id]:
        if project_id in _sessions:
            yield _event("error", category="execution", message="Stop the existing preview before starting again.",
                         fix=["Stop the preview, then retry"], severity="low", recoverable=True)
            return
        client = None
        session = None
        reserved = False
        retained = False
        try:
            if command_override:
                raise PreviewError("Custom commands are disabled for isolated previews")
            ws = _trusted_workspace(ws)
            files = workspace_files(ws)
            if not files:
                raise PreviewError("Workspace is empty — build the project first")
            info = detector.detect(ws)
            effective = info.effective_root or ws
            subdir = effective.relative_to(ws).as_posix()
            cwd = ROOT if subdir == "." else f"{ROOT}/{subdir}"
            client = _client()
            # No host process creation, even for HTML projects or failed setup.
            from vercel.sandbox import NetworkPolicy, SandboxResources

            await asyncio.wait_for(_capacity.acquire(), timeout=0.1)
            reserved = True
            yield _event("status", message="Creating isolated preview environment")
            async with asyncio.timeout(180):
                sandbox = await client.create_sandbox(
                    image="vercel/sandbox/universal", ports=[3000],
                    execution_time_limit=LIFETIME, persistent=False,
                    resources=SandboxResources(vcpus=1), network_policy=NetworkPolicy.deny_all(),
                    env={},
                )
                session = Session(client, sandbox, None, info.project_type, [], time.monotonic() + LIFETIME)
                await sandbox.fs.mkdir(ROOT)
                directories = {ROOT}
                for path, data in files:
                    parent = str(Path(f"{ROOT}/{path}").parent)
                    if parent not in directories:
                        await sandbox.fs.mkdir(parent)
                        directories.add(parent)
                    await sandbox.fs.write_bytes(f"{ROOT}/{path}", data)
                yield _event("status", message="Workspace copied; preparing preview")
                if info.run_strategy == "static" or info.project_type == "html":
                    args = ["python3", "-m", "http.server", "8080", "--bind", "127.0.0.1"]
                elif (effective / "package.json").is_file():
                    package = json.loads((effective / "package.json").read_text())
                    await sandbox.update_network_policy(NetworkPolicy.custom(allow={"registry.npmjs.org": ()}))
                    await _checked(sandbox, "npm", ["install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=cwd)
                    await sandbox.update_network_policy(NetworkPolicy.deny_all())
                    scripts = package.get("scripts", {})
                    if "dev" in scripts and info.project_type in {"react", "vue", "svelte", "vite"}:
                        args = ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "8080", "--strictPort"]
                    elif "start" in scripts:
                        args = ["npm", "start"]
                    else:
                        raise PreviewError("Node previews require a start script (PORT=8080), or a Vite dev script")
                elif info.run_strategy in {"script", "python_server"} or info.project_type in {"python", "fastapi", "flask"}:
                    if (effective / "requirements.txt").is_file():
                        await sandbox.update_network_policy(NetworkPolicy.custom(allow={"pypi.org": (), "files.pythonhosted.org": ()}))
                        await _checked(sandbox, "python3", ["-m", "pip", "install", "-r", "requirements.txt"], cwd=cwd)
                        await sandbox.update_network_policy(NetworkPolicy.deny_all())
                    entry = info.entry_point or "main.py"
                    if info.project_type == "fastapi":
                        module = entry.removesuffix(".py").replace("/", ".")
                        args = ["python3", "-m", "uvicorn", f"{module}:app", "--host", "127.0.0.1", "--port", "8080"]
                    elif info.project_type == "flask":
                        args = ["python3", "-m", "flask", "--app", entry.removesuffix(".py").replace("/", "."), "run", "--host", "127.0.0.1", "--port", "8080"]
                    else:
                        result = await _checked(sandbox, "python3", [entry], cwd=cwd)
                        yield _event("done", exit_code=0, duration=0,
                                     stdout=(result.stdout or b"").decode(errors="replace")[:16000],
                                     stderr=(result.stderr or b"").decode(errors="replace")[:16000],
                                     project_type=info.project_type, command=f"python3 {entry}", success=True)
                        return
                else:
                    raise PreviewError("This project type is not supported by isolated previews yet")
                session.command = args
                await sandbox.create_command(args[0], args[1:], cwd=cwd, env={"PORT": "8080", "HOST": "0.0.0.0"},
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # Test readiness inside the VM. Nothing connects to host loopback.
                await _checked(sandbox, "python3", ["-c", _READY], cwd=cwd)
                token = secrets.token_urlsafe(32)
                gateway = Path(__file__).with_name("preview_gateway.py").read_bytes()
                await sandbox.fs.write_bytes("/tmp/flow-preview-gateway.py", gateway)
                await sandbox.create_command("python3", ["/tmp/flow-preview-gateway.py"],
                                             env={"FLOW_PREVIEW_TOKEN": token},
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                await _checked(sandbox, "python3", ["-c", _READY.replace("8080", "3000")], cwd=cwd)
                route = next((r for r in sandbox.routes if r.port == 3000 and not r.system), None)
                if route is None or not valid_preview_url(route.url):
                    raise PreviewError("Sandbox did not return an approved HTTPS preview domain")
                session.preview_url = f"{route.url.rstrip('/')}/_flow_preview/{token}"
                _sessions[project_id] = session
                retained = True
                yield _event("server_ready", preview_url=session.preview_url, port=3000,
                             project_type=info.project_type, message="Isolated preview ready (expires in five minutes)",
                             command=" ".join(args), expires_in=max(0, int(session.expires_at - time.monotonic())))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Isolated preview setup failed for %s (%s)", project_id, type(exc).__name__)
            message = str(exc) if isinstance(exc, PreviewError) else "Unable to start isolated preview. Check sandbox configuration and retry."
            yield _event("error", category="isolation", message=message,
                         fix=["Configure the isolated runtime, then retry; host execution is disabled"],
                         severity="high", recoverable=True)
        finally:
            if not retained:
                if session:
                    try:
                        await session.sandbox.destroy()
                    except Exception:
                        # Keep the control handle and capacity reservation for retry.
                        _sessions[project_id] = session
                        log.warning("Sandbox cleanup failed; retry available until provider expiry")
                    else:
                        try:
                            await session.client.aclose()
                        finally:
                            _capacity.release()
                else:
                    try:
                        if client:
                            await client.aclose()
                    finally:
                        if reserved:
                            _capacity.release()


_READY = """import socket, time
for attempt in range(100):
    try:
        with socket.create_connection(('127.0.0.1', 8080), timeout=0.3): pass
        break
    except OSError: time.sleep(0.3)
else: raise SystemExit(1)
"""
