"""
Kernel REST API — exposes the AI Kernel over HTTP.

POST /api/kernel/execute
    Execute any kernel command.
    Body: {"input": "patch --file=app/x.py --find=old --replace=new"}

GET  /api/kernel/status
    Kernel status: uptime, command count, modifications, hot reloads.

GET  /api/kernel/state
    Full kernel state including modification audit log.

GET  /api/kernel/modifications
    List all recorded self-modifications.

POST /api/kernel/rollback/{index}
    Roll back modification at index.

GET  /api/kernel/agents
    List all registered command agents.

POST /api/kernel/middleware
    Add a named middleware to the pipeline (from registered set).

Authorization (P0.5 security fix, see docs/security-tenant-boundary-audit.md):
the kernel is a single process-wide singleton, not org-scoped data — there
is no OrgContext to check it against. Every route below requires the same
cross-org admin API-key mechanism already used for other non-org-scoped,
system-level actions (app/routers/usage_api.py's /api/admin/plans/{id},
app/routers/marketplace.py's /api/admin/... routes), not org_context.
Previously any authenticated user of any org could call POST
/api/kernel/execute, including "modify patch ..." commands that rewrite
the running application's own source files (app/kernel/self_modify.py).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.api_keys import ApiKeyRecord, require_api_key

log    = logging.getLogger(__name__)
router = APIRouter(tags=["kernel"])


class KernelExecuteRequest(BaseModel):
    input  : str
    caller : str = "api"
    user_id: Optional[str] = None


@router.post("/api/kernel/execute")
async def kernel_execute(
    req: KernelExecuteRequest,
    key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"])),
):
    from app.kernel import get_kernel
    kernel = get_kernel()
    result = await kernel.execute(req.input, caller=req.caller, user_id=req.user_id)
    return result.to_dict()


@router.get("/api/kernel/status")
async def kernel_status(key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"]))):
    from app.kernel import get_kernel
    return get_kernel().status()


@router.get("/api/kernel/state")
async def kernel_state(key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"]))):
    from app.kernel import get_kernel
    return get_kernel().state.to_dict()


@router.get("/api/kernel/modifications")
async def kernel_modifications(key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"]))):
    from app.kernel import get_kernel
    mods = get_kernel().state.modifications
    return {
        "count"        : len(mods),
        "modifications": [m.to_dict() for m in mods],
    }


@router.post("/api/kernel/rollback/{index}")
async def kernel_rollback(index: int, key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"]))):
    from app.kernel import get_kernel
    try:
        result = get_kernel().modifier.rollback(index)
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/kernel/agents")
async def kernel_agents(key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"]))):
    from app.kernel import get_kernel
    cmds = get_kernel().registry.all()
    return {
        "count" : len(cmds),
        "agents": [{"name": m.name, "description": m.description,
                    "group": m.group, "source": m.source}
                   for m in cmds],
    }
