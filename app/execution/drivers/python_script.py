"""Driver: Python script execution — captures stdout/stderr with live streaming."""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from app.execution import registry


def can_handle(info) -> bool:
    return info.run_strategy == "script"


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    python = registry.best_python()

    if command_override:
        from app.execution.runner import _validate_command
        args = _validate_command(command_override) or [python, "-u", info.entry_point or "main.py"]
    else:
        args = [python, "-u", info.entry_point or "main.py"]

    yield _ev("status", message=f"▶ {' '.join(args)}", command=" ".join(args),
              project_type=info.project_type)

    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
            env={**os.environ},
        )
    except FileNotFoundError:
        yield _ev("error", error=f"Python not found: {args[0]}", project_type=info.project_type)
        return
    except Exception as e:
        yield _ev("error", error=str(e), project_type=info.project_type)
        return

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    q: asyncio.Queue = asyncio.Queue()

    async def pump(stream_r: asyncio.StreamReader, name: str) -> None:
        async for raw in stream_r:
            await q.put((name, raw.decode("utf-8", errors="replace").rstrip()))
        await q.put((name, None))

    t_out = asyncio.create_task(pump(proc.stdout, "stdout"))
    t_err = asyncio.create_task(pump(proc.stderr, "stderr"))

    timeout = 60
    deadline = time.time() + timeout
    done_count = 0

    while done_count < 2:
        remaining = deadline - time.time()
        if remaining <= 0:
            proc.terminate()
            yield _ev("warning", message=f"Script timed out after {timeout}s — terminated.",
                      project_type=info.project_type)
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

    t_out.cancel()
    t_err.cancel()

    rc = proc.returncode if proc.returncode is not None else -1
    elapsed = round(time.time() - start, 2)

    result: dict = {
        "exit_code": rc,
        "duration": elapsed,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "project_type": info.project_type,
        "command": " ".join(args),
        "success": rc == 0,
    }
    if not stdout_lines and not stderr_lines and rc == 0:
        result["warning"] = "Script exited with no output. Add print() calls to see results."

    yield _ev("done", **result)


def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"
