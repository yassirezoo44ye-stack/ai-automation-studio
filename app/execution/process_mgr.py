"""
ProcessManager — tracks and controls long-running project server processes.

Responsibilities:
- Allocate unique ports from a pool (8100–8199)
- Start server subprocesses via runtime.process.start_persistent()
- Track running processes per project_id
- Health-poll a port until the server is ready
- Kill processes on demand or after idle timeout
- Cleanup zombie processes

All subprocess creation is delegated to app.runtime.process.start_persistent()
— this module owns lifecycle management, not process spawning.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Optional

from app.runtime import process as rt_process

log = logging.getLogger(__name__)

_PORT_MIN      = 8100
_PORT_MAX      = 8200
_IDLE_TIMEOUT  = 300.0    # seconds before an idle server is killed
_MAX_RUNTIME   = 3600.0   # hard cap — kill any server older than 1 hour
_READY_POLL    = 0.25     # seconds between port-readiness checks


@dataclass
class RunningProcess:
    project_id: str
    process: asyncio.subprocess.Process
    port: int
    project_type: str
    command: list[str]
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity


# Module-level state
_processes: dict[str, RunningProcess] = {}
_used_ports: set[int] = set()


# ── Public API ────────────────────────────────────────────────────────────────

def get_running(project_id: str) -> Optional[RunningProcess]:
    rp = _processes.get(project_id)
    if rp is None:
        return None
    if not rp.alive:
        _release(project_id)
        return None
    rp.last_activity = time.time()
    return rp


def allocate_port() -> Optional[int]:
    """Reserve a port from the pool. Returns None if pool exhausted."""
    for p in range(_PORT_MIN, _PORT_MAX):
        if p not in _used_ports:
            _used_ports.add(p)
            return p
    return None


async def start_server(
    project_id: str,
    args: list[str],
    cwd: str,
    env: dict,
    port: int,
    project_type: str,
) -> RunningProcess:
    """Kill any existing process for this project, then start a new one."""
    await kill(project_id)
    if port not in _used_ports:
        _used_ports.add(port)

    proc = await rt_process.start_persistent(args, cwd=cwd, env=env)

    rp = RunningProcess(
        project_id=project_id,
        process=proc,
        port=port,
        project_type=project_type,
        command=args,
    )
    _processes[project_id] = rp
    log.info("started %s pid=%d port=%d", project_id, proc.pid, port)
    return rp


async def kill(project_id: str) -> None:
    rp = _processes.get(project_id)
    if rp is None:
        return
    try:
        if rp.alive:
            rp.process.terminate()
            await asyncio.sleep(0.4)
        if rp.alive:
            rp.process.kill()
    except Exception as e:
        log.warning("kill %s: %s", project_id, e)
    _release(project_id)
    log.info("killed %s", project_id)


async def wait_ready(port: int, timeout: float = 15.0) -> bool:
    """Return True when localhost:port accepts a TCP connection."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        await asyncio.sleep(_READY_POLL)
    return False


async def cleanup_idle() -> None:
    """Called periodically from maintenance loop to reap idle/dead/over-limit processes."""
    now = time.time()
    dead = [
        pid for pid, rp in list(_processes.items())
        if (
            not rp.alive
            or rp.idle_seconds > _IDLE_TIMEOUT
            or (now - rp.started_at) > _MAX_RUNTIME
        )
    ]
    for pid in dead:
        log.info("cleanup idle/expired: %s", pid)
        await kill(pid)


def status_all() -> list[dict]:
    return [
        {
            "project_id": rp.project_id,
            "port": rp.port,
            "project_type": rp.project_type,
            "command": " ".join(rp.command),
            "alive": rp.alive,
            "idle_seconds": round(rp.idle_seconds),
            "started_at": rp.started_at,
        }
        for rp in _processes.values()
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _release(project_id: str) -> None:
    rp = _processes.pop(project_id, None)
    if rp:
        _used_ports.discard(rp.port)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False
