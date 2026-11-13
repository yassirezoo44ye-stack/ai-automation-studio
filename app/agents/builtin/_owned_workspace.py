"""Resolve an agent's workspace from a project the caller owns.

Agents reached through /api/agentos/* used to take their workspace from
ctx.args / ctx.workspace — a raw, client-controlled filesystem path. Deploy
then zipped any server directory into a downloadable deliverable, and build
ran npm/make/python with cwd at any path. RunAgent already re-derives the
workspace from a verified project id; this shares that rule with the others.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.agents.base import AgentContext, AgentResult


async def owned_workspace(ctx: AgentContext, agent_name: str) -> Path | AgentResult:
    """Return the caller's own project workspace, or a failed AgentResult."""
    if not ctx.user_id:
        return AgentResult.fail(agent_name, "Authentication required.")
    if not ctx.project_id:
        return AgentResult.fail(
            agent_name,
            f"No project specified. Usage: {agent_name} --project=<id> (or pass project_id).",
        )
    try:
        uid = uuid.UUID(ctx.user_id)
    except ValueError:
        return AgentResult.fail(agent_name, "Invalid caller identity.")

    from fastapi import HTTPException

    from app.core.db import get_pool
    from app.core.filesystem import workspace as project_workspace
    from app.core.helpers import resolve_project_id

    async with get_pool().acquire() as conn:
        try:
            pid = await resolve_project_id(conn, ctx.project_id, uid)
        except HTTPException as exc:
            return AgentResult.fail(agent_name, str(exc.detail))
    ws = project_workspace(str(pid))
    if not ws.exists():
        return AgentResult.fail(agent_name, "Project workspace is empty.")
    return ws
