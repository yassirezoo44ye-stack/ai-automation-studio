"""
Workspace path helpers shared between the Build and Package routers.
Both create or access project workspaces under WORKSPACES/ and must
guard against path-traversal attacks.
"""
import logging
import os
from pathlib import Path

from fastapi import HTTPException

from app.core.config import WORKSPACES, get_environment

log = logging.getLogger(__name__)


def workspaces_persistence_warning() -> str | None:
    """Warn when production keeps project files on the container's own disk.

    Project files (generated code, uploads, images, export packages) live
    under WORKSPACES. On Render the container disk is wiped on every deploy
    and restart, and it is not in any database backup, so production must
    point WORKSPACES_DIR at a persistent disk (render.yaml mounts one at
    /var/data). Returns the warning text, or None when nothing is wrong.
    """
    if get_environment() != "production" or os.getenv("WORKSPACES_DIR"):
        return None
    msg = (
        "WORKSPACES_DIR is not set: project files are stored at "
        f"{WORKSPACES} on the container's own disk and will be lost on the "
        "next deploy or restart. Attach a persistent disk and set "
        "WORKSPACES_DIR (see docs/BACKUP_RESTORE.md)."
    )
    log.warning(msg)
    return msg


def workspace(project_id: str) -> Path:
    """Return (and create if needed) the workspace directory for a project.

    Rejects project_id values that would escape the WORKSPACES root via
    path traversal (e.g. "../../etc").

    AUDIT FIX: previously compared with `str(ws).startswith(str(root))`,
    the classic gotcha where a sibling directory whose name happens to be a
    string-prefix of another (e.g. "/data/ws/abc-evil" vs "/data/ws/abc")
    passes the check even though it isn't actually inside it. Not known to
    be exploitable today (project_id/workspace names are UUIDs, not
    attacker-chosen text), but `is_relative_to()` closes the class of bug
    outright rather than relying on that being true forever.
    """
    ws = (WORKSPACES / project_id).resolve()
    if not ws.is_relative_to(WORKSPACES.resolve()):
        raise HTTPException(400, "Invalid project_id")
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def safe_path(ws: Path, rel: str) -> Path:
    """Resolve a relative path inside a workspace, rejecting any traversal.

    AUDIT FIX: same `is_relative_to()` hardening as workspace() above —
    see its comment for the exact gotcha this closes."""
    p = (ws / rel).resolve()
    if not p.is_relative_to(ws.resolve()):
        raise HTTPException(400, "Invalid path")
    return p
