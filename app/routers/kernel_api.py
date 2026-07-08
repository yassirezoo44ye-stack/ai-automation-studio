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
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log    = logging.getLogger(__name__)
router = APIRouter(tags=["kernel"])


class KernelExecuteRequest(BaseModel):
    input  : str
    caller : str = "api"
    user_id: Optional[str] = None


@router.post("/api/kernel/execute")
async def kernel_execute(req: KernelExecuteRequest):
    from app.kernel import get_kernel
    kernel = get_kernel()
    result = await kernel.execute(req.input, caller=req.caller, user_id=req.user_id)
    return result.to_dict()


@router.get("/api/kernel/status")
async def kernel_status():
    from app.kernel import get_kernel
    return get_kernel().status()


@router.get("/api/kernel/state")
async def kernel_state():
    from app.kernel import get_kernel
    return get_kernel().state.to_dict()


@router.get("/api/kernel/modifications")
async def kernel_modifications():
    from app.kernel import get_kernel
    mods = get_kernel().state.modifications
    return {
        "count"        : len(mods),
        "modifications": [m.to_dict() for m in mods],
    }


@router.post("/api/kernel/rollback/{index}")
async def kernel_rollback(index: int):
    from app.kernel import get_kernel
    try:
        result = get_kernel().modifier.rollback(index)
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/kernel/agents")
async def kernel_agents():
    from app.kernel import get_kernel
    cmds = get_kernel().registry.all()
    return {
        "count" : len(cmds),
        "agents": [{"name": m.name, "description": m.description,
                    "group": m.group, "source": m.source}
                   for m in cmds],
    }
