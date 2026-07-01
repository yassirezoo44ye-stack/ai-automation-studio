"""Driver: static HTML projects — reads the entry file and returns its content as an html event."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def can_handle(info) -> bool:
    return info.run_strategy == "static" or info.project_type == "html"


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    entry = info.entry_point
    if not entry:
        # Find first .html file
        html_files = sorted(p for p in ws.rglob("*.html") if p.is_file())
        if not html_files:
            yield _ev("error", error="No HTML file found.", project_type="html")
            return
        entry = str(html_files[0].relative_to(ws)).replace("\\", "/")

    try:
        content = (ws / entry).read_text(encoding="utf-8")
    except Exception as e:
        yield _ev("error", error=f"Cannot read {entry}: {e}", project_type="html")
        return

    yield _ev(
        "html",
        html_content=content,
        entry_file=entry,
        project_type="html",
        message=f"Opening {entry} in preview…",
    )


def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"
