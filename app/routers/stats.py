import json
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter

from app.core.db import get_pool

router = APIRouter(tags=["stats"])


@router.get("/api/stats")
async def get_stats():
    async with get_pool().acquire() as conn:
        project_count = await conn.fetchval("SELECT COUNT(*) FROM projects")
        run_count     = await conn.fetchval("SELECT COUNT(*) FROM agent_runs")
        completed     = await conn.fetchval("SELECT COUNT(*) FROM agent_runs WHERE status='completed'")
        conv_count    = await conn.fetchval("SELECT COUNT(*) FROM conversations")
        msg_count     = await conn.fetchval("SELECT COUNT(*) FROM messages")
        logs          = await conn.fetch(
            "SELECT action, details, created_at FROM usage_logs ORDER BY created_at DESC LIMIT 10"
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
async def stats_timeseries(days: int = 14):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT DATE(created_at) as day, COUNT(*) as count "
            "FROM messages WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL "
            "GROUP BY day ORDER BY day",
            str(days),
        )
        build_rows = await conn.fetch(
            "SELECT DATE(created_at) as day, COUNT(*) as count "
            "FROM usage_logs WHERE action='build' AND created_at >= NOW() - ($1 || ' days')::INTERVAL "
            "GROUP BY day ORDER BY day",
            str(days),
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
async def list_agent_runs(project_id: Optional[str] = None):
    import uuid
    async with get_pool().acquire() as conn:
        if project_id:
            rows = await conn.fetch(
                "SELECT id,project_id,agent_type,status,started_at,completed_at "
                "FROM agent_runs WHERE project_id=$1 ORDER BY started_at DESC",
                uuid.UUID(project_id),
            )
        else:
            rows = await conn.fetch(
                "SELECT id,project_id,agent_type,status,started_at,completed_at "
                "FROM agent_runs ORDER BY started_at DESC"
            )
    return [{"id": str(r["id"]), "project_id": str(r["project_id"]), "agent_type": r["agent_type"],
             "status": r["status"], "started_at": r["started_at"].isoformat(),
             "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None}
            for r in rows]


@router.get("/api/usage-logs")
async def list_usage_logs():
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, action, details, created_at FROM usage_logs ORDER BY created_at DESC LIMIT 100"
        )
    return [{"id": str(r["id"]), "action": r["action"],
             "details": dict(r["details"]) if r["details"] else {},
             "created_at": r["created_at"].isoformat()} for r in rows]
