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

Authorization (P0.5 security sweep, see docs/security-tenant-boundary-sweep.md):
execute_command() dispatches into a process-wide command registry that
includes app/commands/builtin/modify_cmd.py — "modify file" writes to any
filesystem path the process can reach with NO PolicyEngine-style path
restriction (unlike app/kernel/self_modify.py's SelfModifyingEngine, which
this registry is a separate, independently-registered instance of).
Previously reachable by any authenticated user of any org with only "some
valid session" required. Now requires the same cross-org admin API-key
mechanism as app/routers/kernel_api.py, which gates the equivalent
capability on the AIKernel side. list_commands/describe_command are
unchanged — read-only command metadata, no tenant data, no execution.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.commands import get_registry, get_runner
from app.core.api_keys import ApiKeyRecord, require_api_key

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
async def execute_command(
    req: ExecuteRequest, key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"])),
):
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
    """DISABLED — arbitrary code execution.

    This endpoint took a client-supplied `plugin_path`, resolved it with no
    restriction to any directory, and passed it to
    app.commands.loader._load_file(), which calls
    importlib.util.spec_from_file_location(...).exec_module(module) —
    executing that file's entire module-level code unconditionally, before
    even checking for a register() function. api_auth_middleware
    (app/factory.py) only requires a valid subscription/JWT — no role
    check — so any authenticated user, regardless of privilege, could
    execute arbitrary Python on the server just by naming a path it can
    read.

    Confirmed zero legitimate consumers (no frontend, test, doc, or script
    references this route or `plugin_path` anywhere in the repo), and this
    codebase has no platform-level admin/staff concept to gate it with —
    only per-organization membership roles (app/routers/organizations.py),
    which are scoped to that org's own resources and would be the wrong
    trust boundary for a process-wide code-execution capability regardless.
    Disabled rather than access-gated until a real security model for
    runtime plugin loading is designed — see
    docs/AI_ENTRY_POINT_UNIFICATION_AUDIT.md-adjacent security audit,
    2026-08-03. Startup-time plugin loading (app.commands.loader.
    load_plugins(), which only scans fixed, non-client-controlled
    directories) is unaffected and still runs normally.
    """
    raise HTTPException(
        status_code=403,
        detail=(
            "Runtime plugin registration is disabled pending a security "
            "review — it previously allowed arbitrary code execution via "
            "a client-supplied file path."
        ),
    )
