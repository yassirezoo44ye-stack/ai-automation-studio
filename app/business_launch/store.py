"""Organization-scoped persistence for the opt-in launch prototype.

Caller must supply an org_id from verified OrgContext, never user input.
No router is registered and no schema is initialized in production.
"""
from __future__ import annotations

import uuid

from app.business_launch.workflow import LaunchState, Stage, advance


def _uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


async def create_project(conn, *, org_id: str, user_id: str, name: str, idea: str):
    if not 1 <= len(name.strip()) <= 120:
        raise ValueError("Project name must be 1-120 characters")
    if not 10 <= len(idea.strip()) <= 3000:
        raise ValueError("Idea must be 10-3000 characters")
    return await conn.fetchrow(
        """INSERT INTO business_launch_projects
           (org_id, created_by_user_id, name, idea)
           VALUES ($1, $2, $3, $4)
           RETURNING id, org_id, name, idea, stage, created_at, updated_at""",
        _uuid(org_id), _uuid(user_id), name.strip(), idea.strip(),
    )


async def list_projects(conn, *, org_id: str):
    return await conn.fetch(
        """SELECT id, name, idea, stage, created_at, updated_at
           FROM business_launch_projects WHERE org_id=$1
           ORDER BY created_at DESC LIMIT 50""",
        _uuid(org_id),
    )


async def get_project(conn, *, org_id: str, project_id: str):
    return await conn.fetchrow(
        """SELECT id, name, idea, stage, created_at, updated_at
           FROM business_launch_projects WHERE id=$1 AND org_id=$2""",
        _uuid(project_id), _uuid(org_id),
    )


async def advance_project(conn, *, org_id: str, project_id: str,
                          actor_user_id: str, approve: bool = False):
    """Atomic compare-and-swap stage update; never permits silent skipping.

    Approval requires the API layer to independently verify owner permission.
    The store accepts actor_user_id only from a verified authentication context.
    """
    row = await get_project(conn, org_id=org_id, project_id=project_id)
    if row is None:
        return None
    current = Stage(row["stage"])
    next_state = advance(LaunchState(current), approved_by_owner=approve)
    if next_state.stage == current:
        return row
    return await conn.fetchrow(
        """UPDATE business_launch_projects
           SET stage=$3,
               approved_by_user_id=CASE WHEN $4 THEN $5 ELSE approved_by_user_id END,
               approved_at=CASE WHEN $4 THEN now() ELSE approved_at END,
               updated_at=now()
           WHERE id=$1 AND org_id=$2 AND stage=$6
           RETURNING id, name, idea, stage, created_at, updated_at""",
        _uuid(project_id), _uuid(org_id), next_state.stage.value,
        approve, _uuid(actor_user_id), current.value,
    )
