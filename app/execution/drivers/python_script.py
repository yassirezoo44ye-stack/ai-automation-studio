"""Driver: Python script execution — streams stdout/stderr live."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from app.runtime import registry
from app.runtime import process as rt_process


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
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async for line, code in rt_process.stream_process(
        args,
        cwd=ws,
        merge_stderr=False,
        timeout=60,
    ):
        if code is not None:
            # Final sentinel — code is the exit code
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
