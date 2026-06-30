"""
Workspace path helpers shared between the Build and Package routers.
Both create or access project workspaces under WORKSPACES/ and must
guard against path-traversal attacks.
"""
from pathlib import Path

from fastapi import HTTPException

from app.core.config import WORKSPACES


def workspace(project_id: str) -> Path:
    """Return (and create if needed) the workspace directory for a project.

    Rejects project_id values that would escape the WORKSPACES root via
    path traversal (e.g. "../../etc").
    """
    ws = (WORKSPACES / project_id).resolve()
    if not str(ws).startswith(str(WORKSPACES.resolve())):
        raise HTTPException(400, "Invalid project_id")
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def safe_path(ws: Path, rel: str) -> Path:
    """Resolve a relative path inside a workspace, rejecting any traversal."""
    p = (ws / rel).resolve()
    if not str(p).startswith(str(ws.resolve())):
        raise HTTPException(400, "Invalid path")
    return p
