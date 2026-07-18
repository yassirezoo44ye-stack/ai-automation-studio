import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import owner_user_id as _owner_user_id
from app.core.db import get_pool

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


@router.post("/api/projects", status_code=201)
async def create_project(project: ProjectCreate, request: Request):
    async with get_pool().acquire() as conn:
        uid = await _owner_user_id(conn, request)
        pid = await conn.fetchval(
            "INSERT INTO projects (user_id, name, description) VALUES ($1,$2,$3) RETURNING id",
            uid, project.name, project.description,
        )
    return {"id": str(pid), "message": "Project created"}


@router.get("/api/projects")
async def list_projects(request: Request):
    async with get_pool().acquire() as conn:
        uid = await _owner_user_id(conn, request)
        rows = await conn.fetch(
            "SELECT id, name, description, status, created_at, updated_at "
            "FROM projects WHERE user_id=$1 ORDER BY created_at DESC",
            uid,
        )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "description": r["description"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/api/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    async with get_pool().acquire() as conn:
        uid = await _owner_user_id(conn, request)
        row = await conn.fetchrow(
            "SELECT id, name, description, status, created_at, updated_at "
            "FROM projects WHERE id=$1 AND user_id=$2",
            uuid.UUID(project_id), uid,
        )
    if not row:
        raise HTTPException(404, "Project not found")
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


@router.put("/api/projects/{project_id}")
async def update_project(project_id: str, project: ProjectUpdate, request: Request):
    async with get_pool().acquire() as conn:
        uid = await _owner_user_id(conn, request)
        result = await conn.execute(
            "UPDATE projects "
            "SET name=COALESCE($1,name), description=COALESCE($2,description), updated_at=NOW() "
            "WHERE id=$3 AND user_id=$4",
            project.name, project.description, uuid.UUID(project_id), uid,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Project not found")
    return {"message": "Updated"}


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, request: Request):
    async with get_pool().acquire() as conn:
        uid = await _owner_user_id(conn, request)
        result = await conn.execute(
            "DELETE FROM projects WHERE id=$1 AND user_id=$2",
            uuid.UUID(project_id), uid,
        )
    if result == "DELETE 0":
        raise HTTPException(404, "Project not found")
    return {"message": "Deleted"}
