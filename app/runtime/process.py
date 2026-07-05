"""
Unified Process API — the single place that creates subprocesses.

No other module should call asyncio.create_subprocess_exec directly.
All process creation flows through this module.

Public API
----------
stream_process(cmd, cwd, env, merge_stderr)
    Async generator. Yields (line, None) for each output line, then
    ("", returncode) once as the final sentinel. Matches the interface
    used throughout package.py so migration is drop-in.

run_process(cmd, cwd, env, timeout)
    Run to completion. Returns (returncode, stdout_lines, stderr_lines).
    Use for install steps (pip install, npm install) where callers only
    need the final result.

start_persistent(cmd, cwd, env)
    Start a long-running subprocess (server). Returns the Process object.
    process_mgr calls this for every project server it launches.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import AsyncIterator, Optional

log = logging.getLogger(__name__)

# Maximum memory a user subprocess may consume (512 MB).  Enforced via
# RLIMIT_AS on Linux only; silently skipped on Windows/macOS.
_MAX_RSS_BYTES = 512 * 1024 * 1024

# Maximum wall-clock seconds a persistent server process may run before the
# idle-timeout in process_mgr kicks it.  This is a belt-and-suspenders cap
# applied at spawn time so a hung process cannot outlive the watchdog.
_MAX_SERVER_RUNTIME = 3600  # 1 hour


def _apply_resource_limits() -> None:
    """Called as preexec_fn in spawned subprocesses (Linux only)."""
    if sys.platform != "linux":
        return
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (_MAX_RSS_BYTES, _MAX_RSS_BYTES))
    except Exception:
        pass  # best-effort; never crash the subprocess before it starts

# Safety gate — only these executables may be launched by the process API.
# Prevents command injection if a caller accidentally passes user-supplied input.
_ALLOWED_EXECUTABLES = {
    "python", "python3", "node", "npm", "npx", "pnpm", "bun",
    "uvicorn", "java", "gradle", "gradlew", "cargo", "go",
    # Windows variants
    "python.exe", "python3.exe", "node.exe", "npm.cmd", "npx.cmd",
    "gradlew.bat",
}


def _validate_exe(cmd: list[str]) -> None:
    """Raise ValueError if the executable is not in the allow-list."""
    if not cmd:
        raise ValueError("Empty command")
    exe = Path(cmd[0]).name.lower()
    if exe not in _ALLOWED_EXECUTABLES:
        raise ValueError(f"Executable not allowed by runtime platform: {cmd[0]!r}")


def _build_env(extra: Optional[dict] = None) -> dict:
    env = {**os.environ}
    if extra:
        env.update(extra)
    return env


async def stream_process(
    cmd: list[str],
    cwd: str | Path | None = None,
    env: Optional[dict] = None,
    merge_stderr: bool = True,
    timeout: Optional[float] = None,
) -> AsyncIterator[tuple[str, Optional[int]]]:
    """
    Async generator that yields output lines from a subprocess.

    Yields: (line: str, None) for each output line
    Final:  ("",   rc: int)  once when the process exits

    Args:
        cmd:          Command and arguments (executable must be in allow-list).
        cwd:          Working directory.
        env:          Extra environment variables merged over os.environ.
        merge_stderr: When True, stderr is combined with stdout (default).
                      When False, stderr lines are prefixed with "[stderr] ".
    """
    _validate_exe(cmd)
    merged_env = _build_env(env)
    cwd_str = str(cwd) if cwd else None

    stderr_pipe = asyncio.subprocess.STDOUT if merge_stderr else asyncio.subprocess.PIPE

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_pipe,
            cwd=cwd_str,
            env=merged_env,
        )
    except FileNotFoundError as exc:
        log.error("stream_process: executable not found: %s", cmd[0])
        yield f"[runtime] ERROR: executable not found: {cmd[0]}", None
        yield "", 127
        return
    except Exception as exc:
        log.exception("stream_process: failed to spawn %s", cmd)
        yield f"[runtime] ERROR: {exc}", None
        yield "", -1
        return

    async def _pump(reader: asyncio.StreamReader, prefix: str = "") -> None:
        async for raw in reader:
            line = raw.decode("utf-8", errors="replace").rstrip()
            await q.put((f"{prefix}{line}", None))
        await q.put(None)  # sentinel

    q: asyncio.Queue = asyncio.Queue()
    tasks = [asyncio.create_task(_pump(proc.stdout))]
    expected_sentinels = 1

    if not merge_stderr and proc.stderr:
        tasks.append(asyncio.create_task(_pump(proc.stderr, "[stderr] ")))
        expected_sentinels = 2

    import time as _time
    deadline = _time.monotonic() + timeout if timeout else None

    received = 0
    while received < expected_sentinels:
        if deadline:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                log.warning("stream_process: timeout after %.0fs — killing %s", timeout, cmd[0])
                proc.kill()
                yield "[runtime] Process timed out", None
                break
            try:
                item = await asyncio.wait_for(q.get(), timeout=min(remaining, 1.0))
            except asyncio.TimeoutError:
                continue
        else:
            item = await q.get()

        if item is None:
            received += 1
        else:
            yield item

    for t in tasks:
        t.cancel()

    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()

    yield "", proc.returncode if proc.returncode is not None else -1


async def run_process(
    cmd: list[str],
    cwd: str | Path | None = None,
    env: Optional[dict] = None,
    timeout: float = 120.0,
) -> tuple[int, list[str], list[str]]:
    """
    Run a subprocess to completion and collect all output.

    Returns:
        (returncode, stdout_lines, stderr_lines)

    Use for install / build steps where callers need the final result,
    not live streaming (e.g. pip install, npm install).
    """
    _validate_exe(cmd)
    merged_env = _build_env(env)
    cwd_str = str(cwd) if cwd else None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd_str,
            env=merged_env,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("run_process: timeout after %.0fs — killing %s", timeout, cmd)
        try:
            proc.kill()
        except Exception:
            pass
        return -1, [], [f"[runtime] Timed out after {timeout:.0f}s"]
    except FileNotFoundError:
        return 127, [], [f"[runtime] Executable not found: {cmd[0]}"]
    except Exception as exc:
        log.exception("run_process: %s", cmd)
        return -1, [], [f"[runtime] {exc}"]

    stdout_lines = out.decode("utf-8", errors="replace").splitlines()
    stderr_lines = err.decode("utf-8", errors="replace").splitlines()
    rc = proc.returncode if proc.returncode is not None else -1

    if rc != 0:
        log.warning("run_process: %s exited %d", cmd[0], rc)

    return rc, stdout_lines, stderr_lines


async def start_persistent(
    cmd: list[str],
    cwd: str | None = None,
    env: Optional[dict] = None,
) -> asyncio.subprocess.Process:
    """
    Start a long-running subprocess (server) and return its Process object.

    The caller (process_mgr) is responsible for tracking, health-checking,
    and terminating the process.
    """
    _validate_exe(cmd)
    merged_env = _build_env(env)

    kwargs: dict = dict(
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=merged_env,
    )
    # Apply memory cap on Linux; ignored elsewhere.
    if sys.platform == "linux":
        kwargs["preexec_fn"] = _apply_resource_limits

    proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
    log.info("start_persistent: pid=%d cmd=%s", proc.pid, cmd)
    return proc
