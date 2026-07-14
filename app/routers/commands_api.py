"""
Commands REST API.

POST /api/commands/execute
    Execute any command by name or raw string.
    Body: {"input": "run ./my-project --port=3000"}
      or: {"command": "run", "args": ["./my-project"], "flags": {"port": "3000"}}

GET  /api/commands
    List all registered commands.

GET  /api/commands/{name}
    Describe one command.

POST /api/commands/register
    Register a new command from a plugin file at runtime.
    Body: {"plugin_path": "/abs/path/to/plugin.py"}
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.commands import get_registry, get_runner

log    = logging.getLogger(__name__)
router = APIRouter(tags=["commands"])


# ── Request models ────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    # raw string OR structured
    input  : Optional[str] = None
    command: Optional[str] = None
    args   : list[str]     = []
    flags  : dict[str, str]= {}
    caller : str           = "api"
    user_id: Optional[str] = None


class RegisterPluginRequest(BaseModel):
    plugin_path: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/commands/execute")
async def execute_command(req: ExecuteRequest):
    """
    Execute a command.  Returns CommandResult as JSON.
    Never raises 5xx — errors are captured in the result.
    """
    runner = get_runner()

    if req.input:
        result = await runner.execute(req.input, caller=req.caller, user_id=req.user_id)
    elif req.command:
        result = await runner.execute_parsed(
            req.command, req.args, req.flags,
            caller=req.caller, user_id=req.user_id,
        )
    else:
        raise HTTPException(status_code=400,
                            detail="Provide either 'input' (raw string) or 'command'.")

    return result.to_dict()


@router.get("/api/commands")
async def list_commands():
    """List all registered commands, grouped."""
    registry = get_registry()
    groups   = registry.by_group()
    return {
        "total": len(registry.names()),
        "groups": {
            group: [
                {
                    "name"       : m.name,
                    "description": m.description,
                    "usage"      : m.usage,
                    "aliases"    : m.aliases,
                    "source"     : m.source,
                }
                for m in commands
            ]
            for group, commands in groups.items()
        },
    }


@router.get("/api/commands/{name}")
async def describe_command(name: str):
    """Describe a single command."""
    registry = get_registry()
    meta     = registry.lookup(name)
    if meta is None:
        from app.commands.result import _closest
        close = _closest(name, registry.names())
        raise HTTPException(
            status_code=404,
            detail={
                "error"      : f"Command '{name}' not found.",
                "suggestions": [f"Did you mean: {c}?" for c in close[:3]],
                "all_commands": registry.names(),
            },
        )
    return {
        "name"       : meta.name,
        "description": meta.description,
        "usage"      : meta.usage,
        "aliases"    : meta.aliases,
        "group"      : meta.group,
        "source"     : meta.source,
    }


@router.post("/api/commands/register")
async def register_plugin(req: RegisterPluginRequest):
    """Load a plugin file and register its commands at runtime."""
    from pathlib import Path
    from app.commands.loader import _load_file

    path = Path(req.plugin_path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    registry = get_registry()
    before   = set(registry.names())
    ok       = _load_file(registry, path)
    if not ok:
        raise HTTPException(status_code=422,
                            detail=f"{path.name} has no register() function.")

    added = list(set(registry.names()) - before)
    return {"loaded": str(path), "new_commands": added}
