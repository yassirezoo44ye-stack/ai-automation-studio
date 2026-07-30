"""
Deliverables registry — turns a file an agent produced during a run (e.g.
DeployAgent's zip archive) into something the frontend can actually
download, with the org-scoping a raw filesystem path doesn't carry on
its own (see app/routers/agent_os_api.py's deliverable download route).

In-process only, same tradeoff as app.agents.liveness's `_running` dict:
a deliverable entry is a link back to a file that's already durably on
disk under WORKSPACES. Losing the registry entry on a process restart
means the download link expires — it does not delete the artifact.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Optional, TypedDict

from app.core.config import WORKSPACES

log = logging.getLogger(__name__)


class Deliverable(TypedDict):
    path: str
    run_id: str
    agent: str
    label: str
    organization_id: Optional[str]
    # The verified caller identity that produced this deliverable (see
    # app.tenancy.context.optional_user_id) — None only when the run that
    # created it had no authenticated caller at all. This is the primary
    # ownership check at download time; organization_id is the fallback
    # for org-shared access. Never populate this from a client-supplied
    # value (e.g. a request-body field) — it must come from a verified
    # bearer token, or it isn't an authorization boundary at all.
    user_id: Optional[str]
    created_at: float


_deliverables: dict[str, Deliverable] = {}


def register(
    path: Path, *, run_id: str, agent: str, label: str,
    organization_id: Optional[str] = None, user_id: Optional[str] = None,
) -> Optional[str]:
    """
    Registers `path` for download and returns a deliverable_id, or None
    (logged, not raised) if the path isn't under WORKSPACES — an agent's
    own path construction is never trusted as an authorization boundary
    on its own, only paths inside the known artifact root are servable.
    """
    resolved = path.resolve()
    try:
        resolved.relative_to(WORKSPACES.resolve())
    except ValueError:
        log.warning("refused to register deliverable outside WORKSPACES: %s", resolved)
        return None

    deliverable_id = uuid.uuid4().hex
    _deliverables[deliverable_id] = {
        "path": str(resolved),
        "run_id": run_id,
        "agent": agent,
        "label": label,
        "organization_id": organization_id,
        "user_id": user_id,
        "created_at": time.time(),
    }
    return deliverable_id


def get(deliverable_id: str) -> Optional[Deliverable]:
    return _deliverables.get(deliverable_id)
