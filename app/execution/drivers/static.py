"""Driver: static HTML projects — reads the entry file and returns its content as an html event."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


def can_handle(info) -> bool:
    return info.run_strategy == "static" or info.project_type == "html"


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    entry = info.entry_point
    if not entry:
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

    content = _inline_assets(content, ws, entry)

    yield _ev(
        "html",
        html_content=content,
        entry_file=entry,
        project_type="html",
        message=f"Opening {entry} in preview…",
    )


def _inline_assets(html: str, ws: Path, entry: str) -> str:
    """Inline relative JS/CSS so the blob URL preview works without a real server.

    Relative <script src> and <link rel=stylesheet href> references are replaced
    with inline <script> and <style> blocks.  Absolute URLs, data: URIs, and any
    path that would escape the workspace are left untouched.
    """
    base_dir = (ws / entry).parent.resolve()
    ws_resolved = ws.resolve()

    def _safe_read(src: str) -> Optional[str]:
        if not src or src.startswith(("http://", "https://", "//", "data:", "#", "javascript:")):
            return None
        try:
            target = (base_dir / src).resolve()
        except Exception:
            return None
        if not target.is_relative_to(ws_resolved):
            return None  # path-traversal guard
        try:
            return target.read_text(encoding="utf-8")
        except Exception:
            return None

    def _sub_script(m: re.Match) -> str:
        src = m.group(1)
        body = _safe_read(src)
        return f"<script>{body}</script>" if body is not None else m.group(0)

    def _sub_link(m: re.Match) -> str:
        full_tag = m.group(0)
        if "stylesheet" not in full_tag.lower():
            return full_tag
        href_m = re.search(r'href=["\']([^"\']+)["\']', full_tag, re.IGNORECASE)
        if not href_m:
            return full_tag
        body = _safe_read(href_m.group(1))
        return f"<style>{body}</style>" if body is not None else full_tag

    # <script src="path/to/file.js"></script>
    html = re.sub(
        r'<script\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>\s*</script>',
        _sub_script, html, flags=re.IGNORECASE | re.DOTALL,
    )
    # <link ...> (targets rel=stylesheet)
    html = re.sub(
        r'<link\b[^>]*/?>',
        _sub_link, html, flags=re.IGNORECASE,
    )
    return html


def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"
