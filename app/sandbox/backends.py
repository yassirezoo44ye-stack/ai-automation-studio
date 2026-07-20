"""
Sandbox execution backends — DockerBackend (primary) and ProcessBackend
(fallback), mirroring the Event Bus phase's Redis-or-in-process fallback
precedent: get_sandbox_backend() probes Docker once and caches the result,
so the platform runs identically either way, just with a weaker isolation
guarantee when Docker isn't available.

Both backends produce the same Worker interface: an asyncio subprocess
(a local `docker run -i --rm ...` client process for Docker — the client
process's stdin/stdout ARE the attached container's stdin/stdout, so no
separate `docker attach` step is needed) whose stdin/stdout speak the
protocol in app/sandbox/protocol.py, driven by
app/sandbox/runner_entrypoint.py running inside it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import sys
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.sandbox.permissions import SandboxLimits

log = logging.getLogger(__name__)

ContextRpcHandler = Callable[[str, list, dict], Awaitable[Any]]

_RUNNER_SOURCE_PATH = Path(__file__).parent / "runner_entrypoint.py"


class WorkerCallError(Exception):
    """The worker reported a real error for one specific call — the
    worker process itself is still alive and can serve more requests."""


class WorkerCrashedError(Exception):
    """The worker process itself died (EOF / non-zero exit) — the caller
    must not send it any more requests."""


class Worker:
    """One live sandboxed process (or Docker container) running a single
    plugin's code for the plugin's whole enabled lifetime."""

    def __init__(
        self, process: asyncio.subprocess.Process, *,
        installation_id: str, backend: str, container_name: Optional[str] = None,
        context_rpc_handler: Optional[ContextRpcHandler] = None,
        default_timeout: float = 30.0,
    ) -> None:
        self._process = process
        self.installation_id = installation_id
        self.backend = backend
        self._container_name = container_name
        self._context_rpc_handler = context_rpc_handler
        self.default_timeout = default_timeout
        self._lock = asyncio.Lock()
        self._stopped = False

    @property
    def pid_or_container_id(self) -> str:
        return self._container_name or str(self._process.pid)

    @property
    def is_alive(self) -> bool:
        return self._process.returncode is None

    async def call(
        self, call: str, *, method: Optional[str] = None,
        args: Optional[list] = None, kwargs: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Send one request, service any context_rpc round-trips the
        worker sends back mid-call, and return the final result. `timeout`
        defaults to this worker's per-plugin-derived `default_timeout`
        (SandboxLimits.timeout_s) — pass it explicitly to override for one
        call, as app/plugins/loader.py's lifecycle hooks do."""
        if self._stopped or not self.is_alive:
            raise WorkerCrashedError(f"worker for installation {self.installation_id} is not running")
        if timeout is None:
            timeout = self.default_timeout
        async with self._lock:
            req_id = uuid.uuid4().hex
            await self._send({"id": req_id, "call": call, "method": method,
                               "args": args or [], "kwargs": kwargs or {}})
            return await self._pump_until(req_id, timeout)

    async def _send(self, payload: dict) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write((json.dumps(payload) + "\n").encode())
        await self._process.stdin.drain()

    async def _pump_until(self, req_id: str, timeout: float) -> Any:
        assert self._process.stdout is not None
        deadline_remaining = timeout
        while True:
            import time
            t0 = time.monotonic()
            try:
                line = await asyncio.wait_for(self._process.stdout.readline(), timeout=deadline_remaining)
            except asyncio.TimeoutError:
                raise WorkerCrashedError(f"worker for installation {self.installation_id} timed out after {timeout}s")
            deadline_remaining = max(0.001, deadline_remaining - (time.monotonic() - t0))
            if not line:
                raise WorkerCrashedError(f"worker for installation {self.installation_id} closed its output unexpectedly")
            try:
                data = json.loads(line.decode().strip() or "{}")
            except json.JSONDecodeError:
                log.warning("sandbox worker %s wrote non-JSON stdout line: %r", self.installation_id, line)
                continue

            if data.get("call") == "context_rpc":
                await self._service_context_rpc(data)
                continue

            if data.get("id") != req_id:
                continue  # stale line from a previous (timed-out) call — ignore
            if not data.get("ok"):
                raise WorkerCallError(data.get("error") or "sandbox worker call failed")
            return data.get("result")

    async def _service_context_rpc(self, request: dict) -> None:
        req_id = request.get("id")
        try:
            if self._context_rpc_handler is None:
                raise RuntimeError("no context_rpc handler configured for this worker")
            result = await self._context_rpc_handler(
                request.get("method"), request.get("args") or [], request.get("kwargs") or {},
            )
            await self._send({"id": req_id, "ok": True, "result": result, "error": None})
        except Exception as exc:  # noqa: BLE001 — must always answer the worker
            await self._send({"id": req_id, "ok": False, "result": None, "error": str(exc)})

    async def stop(self, *, timeout: float = 8.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
        except Exception:
            pass
        if self.backend == "docker" and self._container_name:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "stop", "-t", "5", self._container_name,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except Exception as exc:
                log.warning("docker stop failed for %s: %s", self._container_name, exc)
        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                self._process.kill()
            except Exception:
                pass
            await self._process.wait()


class SandboxBackend(ABC):
    @abstractmethod
    async def spawn(
        self, *, installation_id: str, workspace_dir: Path, entry_point: str,
        plugin_id: str, org_id: Optional[str], config: dict,
        limits: SandboxLimits, secret_env: dict[str, str],
        context_rpc_handler: ContextRpcHandler,
    ) -> Worker:
        ...


def _prepare_workspace_runner(workspace_dir: Path) -> None:
    """Copies runner_entrypoint.py's real source into the worker's
    isolated workspace as a standalone file (see that module's docstring)
    so it runs unmodified inside a bare container with no `app` package."""
    shutil.copy(_RUNNER_SOURCE_PATH, workspace_dir / "runner_entrypoint.py")


def _worker_env(
    *, installation_id: str, entry_point: str, plugin_id: str,
    org_id: Optional[str], config: dict, secret_env: dict[str, str],
) -> dict[str, str]:
    env = {
        "AXON_ENTRY_POINT": entry_point,
        "AXON_INSTALLATION_ID": installation_id,
        "AXON_PLUGIN_ID": plugin_id,
        "AXON_ORG_ID": org_id or "",
        "AXON_PLUGIN_CONFIG": json.dumps(config or {}),
        "PYTHONUNBUFFERED": "1",
    }
    env.update(secret_env)
    return env


class ProcessBackend(SandboxBackend):
    """Fallback backend — plain child process, not a container. Still
    gives real process isolation, an isolated workspace, and timeout
    enforcement; OS-level CPU/memory limits are Linux-only (RLIMIT),
    matching the honest limitation already documented by
    app/execution/platform/sandbox.py and app/runtime/process.py."""

    async def spawn(
        self, *, installation_id, workspace_dir, entry_point, plugin_id,
        org_id, config, limits, secret_env, context_rpc_handler,
    ) -> Worker:
        _prepare_workspace_runner(workspace_dir)
        env = {**os.environ, **_worker_env(
            installation_id=installation_id, entry_point=entry_point, plugin_id=plugin_id,
            org_id=org_id, config=config, secret_env=secret_env,
        )}

        kwargs: dict[str, Any] = {}
        if sys.platform == "linux":
            kwargs["preexec_fn"] = _make_rlimit_preexec(limits)

        process = await asyncio.create_subprocess_exec(
            sys.executable, "runner_entrypoint.py",
            cwd=str(workspace_dir), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )
        return Worker(process, installation_id=installation_id, backend="process",
                       context_rpc_handler=context_rpc_handler, default_timeout=limits.timeout_s)


def _make_rlimit_preexec(limits: SandboxLimits):
    def _apply():
        try:
            import resource
            mem_bytes = limits.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_NPROC, (limits.pids, limits.pids))
            resource.setrlimit(resource.RLIMIT_CPU, (int(limits.cpu_seconds), int(limits.cpu_seconds) + 1))
        except Exception:
            pass  # best-effort — never crash the child before it starts
    return _apply


_NETWORK_FLAG = {
    # "internal" and "allowlist" are resolved dynamically in
    # DockerBackend.spawn() (shared --internal network / --add-host DNS
    # allowlist respectively) — this dict only covers the two static cases.
    "none": "none",
    "full": "bridge",
}

_INTERNAL_NETWORK_NAME = "axon-sandbox-internal"
# Unreachable resolver inside the container: DNS queries for anything not
# seeded via --add-host get connection-refused instead of succeeding, so
# only the plugin's declared allowlisted domains resolve. This blocks
# *resolution* of non-allowed hostnames — it does not block a plugin from
# connecting directly to a raw IP address, which is a known, documented
# limitation of DNS-based allowlisting.
_BLACKHOLE_DNS = "127.0.0.1"


async def _ensure_internal_network() -> None:
    """Idempotently creates the shared Docker `--internal` bridge network
    (no route to the external world, containers on it can still reach each
    other) used by NetworkPolicy "internal". Real network isolation instead
    of the previous degrade-to-"none" placeholder."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "network", "create", "--internal", _INTERNAL_NETWORK_NAME,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 and b"already exists" not in stderr:
        log.warning("failed to create internal sandbox network: %s", stderr.decode(errors="replace"))


async def _resolve_allowed_domains(domains: list[str]) -> dict[str, str]:
    """Host-side DNS resolution for each manifest-declared domain, used to
    seed --add-host entries. Best-effort: a domain that fails to resolve is
    skipped (logged), not fatal to spawning the worker."""
    loop = asyncio.get_event_loop()
    resolved: dict[str, str] = {}
    for domain in domains:
        try:
            ip = await loop.run_in_executor(None, socket.gethostbyname, domain)
            resolved[domain] = ip
        except Exception as exc:
            log.warning("sandbox: could not resolve allowlisted domain %r: %s", domain, exc)
    return resolved


class DockerBackend(SandboxBackend):
    """Primary backend — one Docker container per plugin worker,
    `docker run -i --rm` in the foreground so the local client process's
    stdin/stdout ARE the container's attached stdin/stdout (no separate
    `docker attach` step). Resource limits are real container limits
    (--memory/--cpus/--pids-limit), enforced by the Docker daemon on any
    host OS Docker Desktop runs on, not just Linux."""

    IMAGE = "python:3.11-slim"

    async def spawn(
        self, *, installation_id, workspace_dir, entry_point, plugin_id,
        org_id, config, limits, secret_env, context_rpc_handler,
    ) -> Worker:
        _prepare_workspace_runner(workspace_dir)
        env = _worker_env(
            installation_id=installation_id, entry_point=entry_point, plugin_id=plugin_id,
            org_id=org_id, config=config, secret_env=secret_env,
        )
        container_name = f"axon-sandbox-{installation_id}"

        network_flag = _NETWORK_FLAG.get(limits.network_policy, "none")
        extra_network_flags: list[str] = []
        if limits.network_policy == "internal":
            await _ensure_internal_network()
            network_flag = _INTERNAL_NETWORK_NAME
        elif limits.network_policy == "allowlist":
            network_flag = "bridge"
            resolved = await _resolve_allowed_domains(limits.allowed_domains)
            for domain, ip in resolved.items():
                extra_network_flags += ["--add-host", f"{domain}:{ip}"]
            extra_network_flags += ["--dns", _BLACKHOLE_DNS]
            if not resolved:
                log.warning(
                    "sandbox worker for installation %s granted network_policy='allowlist' "
                    "but no declared domains resolved — effectively no reachable hosts",
                    installation_id,
                )
        # --cpus is a continuous rate cap (cores), a different concept from
        # cpu_seconds (a total CPU-time budget, enforced via RLIMIT_CPU on
        # the process backend and via the wall-clock timeout on Worker.call
        # here) — Docker has no direct "total CPU-seconds then kill"
        # primitive without external polling, so this is deliberately a
        # small fixed rate cap, not a unit conversion of cpu_seconds.
        cpus = "0.5" if limits.cpu_seconds <= 15 else "1.0"
        # /workspace holds the plugin's own source (read-only unless the
        # plugin was granted filesystem_write) — /tmp is always a writable
        # scratch space regardless of that grant, matching the platform's
        # unconditional "Writable Scratch Space" requirement (distinct
        # from "Filesystem Write" access to the plugin's own mounted code).
        workspace_mount = f"{workspace_dir}:/workspace" if limits.filesystem_write else f"{workspace_dir}:/workspace:ro"
        cmd = [
            "docker", "run", "-i", "--rm",
            "--name", container_name,
            "--network", network_flag,
            *extra_network_flags,
            "--memory", f"{limits.memory_mb}m",
            "--cpus", cpus,
            "--pids-limit", str(limits.pids),
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "-v", workspace_mount,
            "-w", "/workspace",
        ]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [self.IMAGE, "python", "runner_entrypoint.py"]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return Worker(process, installation_id=installation_id, backend="docker",
                       container_name=container_name, context_rpc_handler=context_rpc_handler,
                       default_timeout=limits.timeout_s)


async def _docker_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=5)
        return rc == 0
    except Exception:
        return False


_backend: Optional[SandboxBackend] = None
_backend_name: Optional[str] = None


async def get_sandbox_backend() -> SandboxBackend:
    """Probes Docker once and caches the result for the process lifetime —
    mirrors the Event Bus phase's Redis-or-in-process fallback precedent.
    Override via SANDBOX_BACKEND=process to force the fallback (e.g. CI
    environments without Docker)."""
    global _backend, _backend_name
    if _backend is not None:
        return _backend
    forced = os.getenv("SANDBOX_BACKEND", "").lower()
    if forced == "process":
        _backend, _backend_name = ProcessBackend(), "process"
    elif forced == "docker":
        _backend, _backend_name = DockerBackend(), "docker"
    elif await _docker_available():
        _backend, _backend_name = DockerBackend(), "docker"
    else:
        log.warning("sandbox: Docker unavailable — falling back to ProcessBackend (weaker isolation)")
        _backend, _backend_name = ProcessBackend(), "process"
    log.info("sandbox backend selected: %s", _backend_name)
    return _backend


def get_sandbox_backend_name() -> Optional[str]:
    return _backend_name
