import json
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.core.auth import owner_user_id
from app.core.db import get_pool

router = APIRouter(tags=["stats"])


@router.get("/api/stats")
async def get_stats(request: Request):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        project_count = await conn.fetchval(
            "SELECT COUNT(*) FROM projects WHERE user_id=$1", uid)
        run_count     = await conn.fetchval(
            "SELECT COUNT(*) FROM agent_runs ar JOIN projects p ON ar.project_id=p.id "
            "WHERE p.user_id=$1", uid)
        completed     = await conn.fetchval(
            "SELECT COUNT(*) FROM agent_runs ar JOIN projects p ON ar.project_id=p.id "
            "WHERE p.user_id=$1 AND ar.status='completed'", uid)
        conv_count    = await conn.fetchval(
            "SELECT COUNT(*) FROM conversations c JOIN projects p ON c.project_id=p.id "
            "WHERE p.user_id=$1", uid)
        msg_count     = await conn.fetchval(
            "SELECT COUNT(*) FROM messages m "
            "JOIN conversations c ON m.conversation_id=c.id "
            "JOIN projects p ON c.project_id=p.id WHERE p.user_id=$1", uid)
        logs          = await conn.fetch(
            "SELECT action, details, created_at FROM usage_logs "
            "WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10", uid,
        )
    return {
        "projects":       int(project_count),
        "agent_runs":     int(run_count),
        "completed_runs": int(completed),
        "conversations":  int(conv_count),
        "messages":       int(msg_count),
        "success_rate":   round(int(completed) / max(int(run_count), 1) * 100, 1),
        "recent_activity": [
            {
                "action":  r["action"],
                "details": (json.loads(r["details"]) if isinstance(r["details"], str)
                            else (dict(r["details"]) if r["details"] else {})),
                "time":    r["created_at"].isoformat(),
            }
            for r in logs
        ],
    }


@router.get("/api/stats/timeseries")
async def stats_timeseries(request: Request, days: int = 14):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        rows = await conn.fetch(
            "SELECT DATE(m.created_at) as day, COUNT(*) as count "
            "FROM messages m "
            "JOIN conversations c ON m.conversation_id=c.id "
            "JOIN projects p ON c.project_id=p.id "
            "WHERE p.user_id=$1 AND m.created_at >= NOW() - ($2 || ' days')::INTERVAL "
            "GROUP BY day ORDER BY day",
            uid, str(days),
        )
        build_rows = await conn.fetch(
            "SELECT DATE(created_at) as day, COUNT(*) as count "
            "FROM usage_logs WHERE user_id=$1 AND action='build' "
            "AND created_at >= NOW() - ($2 || ' days')::INTERVAL "
            "GROUP BY day ORDER BY day",
            uid, str(days),
        )
    msg_map   = {str(r["day"]): int(r["count"]) for r in rows}
    build_map = {str(r["day"]): int(r["count"]) for r in build_rows}

    labels, msgs, builds = [], [], []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        labels.append(d[5:])
        msgs.append(msg_map.get(d, 0))
        builds.append(build_map.get(d, 0))
    return {"labels": labels, "messages": msgs, "builds": builds}


@router.get("/api/agent-runs")
async def list_agent_runs(request: Request, project_id: Optional[str] = None):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        if project_id:
            owned = await conn.fetchval(
                "SELECT 1 FROM projects WHERE id=$1 AND user_id=$2",
                uuid.UUID(project_id), uid,
            )
            if not owned:
                raise HTTPException(404, "Project not found")
            rows = await conn.fetch(
                "SELECT id,project_id,agent_type,status,started_at,completed_at "
                "FROM agent_runs WHERE project_id=$1 ORDER BY started_at DESC",
                uuid.UUID(project_id),
            )
        else:
            rows = await conn.fetch(
                "SELECT ar.id,ar.project_id,ar.agent_type,ar.status,ar.started_at,ar.completed_at "
                "FROM agent_runs ar JOIN projects p ON ar.project_id=p.id "
                "WHERE p.user_id=$1 ORDER BY ar.started_at DESC",
                uid,
            )
    return [{"id": str(r["id"]), "project_id": str(r["project_id"]), "agent_type": r["agent_type"],
             "status": r["status"], "started_at": r["started_at"].isoformat(),
             "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None}
            for r in rows]


@router.get("/api/usage-logs")
async def list_usage_logs(request: Request):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        rows = await conn.fetch(
            "SELECT id, action, details, created_at FROM usage_logs "
            "WHERE user_id=$1 ORDER BY created_at DESC LIMIT 100", uid,
        )
    return [{"id": str(r["id"]), "action": r["action"],
             "details": dict(r["details"]) if r["details"] else {},
             "created_at": r["created_at"].isoformat()} for r in rows]
