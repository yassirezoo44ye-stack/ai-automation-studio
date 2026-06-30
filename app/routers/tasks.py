import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import anthropic
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import owner_email
from app.core.db import get_pool, ensure_tasks_table
from app.core.helpers import get_ai_client, anthropic_error_message

router = APIRouter(tags=["tasks"])

_TASK_STATUSES   = ("pending", "in_progress", "done")
_TASK_PRIORITIES = ("low", "medium", "high")
_TASK_RECURRENCE = ("none", "daily", "weekly", "monthly")

TASK_EXTRACT_SYSTEM = """Extract concrete, actionable tasks that were mentioned, requested, or agreed to in this conversation.
Respond with ONLY a JSON array (no markdown fences, no explanation). Each item:
{"title": "short specific action", "priority": "low"|"medium"|"high", "category": "short label or null", "notes": "1-2 sentences of context or null"}
Return [] if there are no real actionable tasks. Do not invent tasks that weren't actually discussed."""


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    notes: Optional[str] = Field(None, max_length=5000)
    project_id: Optional[str] = None
    priority: str = Field("medium", pattern="^(low|medium|high)$")
    category: Optional[str] = Field(None, max_length=100)
    tags: List[str] = Field(default_factory=list)
    due_date: Optional[str] = None
    recurrence: str = Field("none", pattern="^(none|daily|weekly|monthly)$")


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    notes: Optional[str] = Field(None, max_length=5000)
    project_id: Optional[str] = None
    priority: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[List[str]] = None
    due_date: Optional[str] = None
    recurrence: Optional[str] = Field(None, pattern="^(none|daily|weekly|monthly)$")
    status: Optional[str] = Field(None, pattern="^(pending|in_progress|done)$")


def _parse_due_date(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid due_date — use ISO 8601 (e.g. 2026-07-10T09:00:00Z)")


def _parse_uuid(value: Optional[str], field: str):
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(400, f"Invalid {field}")


def _task_row_to_dict(row) -> dict:
    d = dict(row)
    for k in ("id", "project_id", "conversation_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("due_date", "created_at", "updated_at", "completed_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def _next_due_date(due, recurrence: str):
    if not due or recurrence == "none":
        return None
    if recurrence == "daily":
        return due + timedelta(days=1)
    if recurrence == "weekly":
        return due + timedelta(weeks=1)
    if recurrence == "monthly":
        month = due.month + 1
        year = due.year + (1 if month > 12 else 0)
        month = month if month <= 12 else 1
        day = min(due.day, 28)
        return due.replace(year=year, month=month, day=day)
    return None


@router.get("/api/tasks")
async def list_tasks(
    request: Request,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "due_date",
):
    await ensure_tasks_table()
    owner = owner_email(request)
    clauses = ["owner_email = $1"]
    params: list = [owner]

    def add(clause: str, value):
        params.append(value)
        clauses.append(clause.format(n=len(params)))

    if status:
        if status not in _TASK_STATUSES:
            raise HTTPException(400, "Invalid status filter")
        add("status = ${n}", status)
    if priority:
        if priority not in _TASK_PRIORITIES:
            raise HTTPException(400, "Invalid priority filter")
        add("priority = ${n}", priority)
    if category:
        add("category = ${n}", category)
    if project_id:
        add("project_id = ${n}", _parse_uuid(project_id, "project_id"))
    if search:
        add("(title ILIKE ${n} OR notes ILIKE ${n})", f"%{search}%")

    sort_col = {
        "due_date": "due_date NULLS LAST, priority DESC",
        "priority": "priority DESC, due_date NULLS LAST",
        "created":  "created_at DESC",
        "title":    "title ASC",
    }.get(sort, "due_date NULLS LAST")

    query = f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY {sort_col}"
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, *params)
    return {"tasks": [_task_row_to_dict(r) for r in rows]}


@router.post("/api/tasks")
async def create_task(body: TaskCreate, request: Request):
    await ensure_tasks_table()
    owner = owner_email(request)
    pid = _parse_uuid(body.project_id, "project_id")
    due = _parse_due_date(body.due_date)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow('''
            INSERT INTO tasks (owner_email, project_id, title, notes, priority, category, tags, due_date, recurrence)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *
        ''', owner, pid, body.title.strip(), body.notes, body.priority,
             body.category, body.tags, due, body.recurrence)
    return _task_row_to_dict(row)


@router.put("/api/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate, request: Request):
    await ensure_tasks_table()
    owner = owner_email(request)
    tid = _parse_uuid(task_id, "task_id")
    fields, params = [], []

    def set_field(col: str, value):
        params.append(value)
        fields.append(f"{col} = ${len(params)}")

    if body.title is not None:      set_field("title", body.title.strip())
    if body.notes is not None:      set_field("notes", body.notes)
    if body.project_id is not None: set_field("project_id", _parse_uuid(body.project_id, "project_id"))
    if body.priority is not None:   set_field("priority", body.priority)
    if body.category is not None:   set_field("category", body.category)
    if body.tags is not None:       set_field("tags", body.tags)
    if body.due_date is not None:   set_field("due_date", _parse_due_date(body.due_date))
    if body.recurrence is not None: set_field("recurrence", body.recurrence)
    if body.status is not None:
        set_field("status", body.status)
        set_field("completed_at", datetime.utcnow() if body.status == "done" else None)

    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at = NOW()")
    params.extend([tid, owner])

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE tasks SET {', '.join(fields)} WHERE id = ${len(params)-1} AND owner_email = ${len(params)} RETURNING *",
            *params,
        )
        if not row:
            raise HTTPException(404, "Task not found")

        if body.status == "done" and row["recurrence"] != "none" and row["due_date"]:
            next_due = _next_due_date(row["due_date"], row["recurrence"])
            if next_due:
                await conn.execute('''
                    INSERT INTO tasks (owner_email, project_id, conversation_id, title, notes, priority, category, tags, due_date, recurrence, source)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ''', owner, row["project_id"], row["conversation_id"], row["title"], row["notes"],
                     row["priority"], row["category"], row["tags"], next_due, row["recurrence"], row["source"])

    return _task_row_to_dict(row)


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    await ensure_tasks_table()
    owner = owner_email(request)
    tid = _parse_uuid(task_id, "task_id")
    async with get_pool().acquire() as conn:
        deleted = await conn.fetchval(
            "WITH d AS (DELETE FROM tasks WHERE id=$1 AND owner_email=$2 RETURNING 1) SELECT COUNT(*) FROM d",
            tid, owner,
        )
    if not deleted:
        raise HTTPException(404, "Task not found")
    return {"deleted": True}


@router.post("/api/tasks/from-conversation/{conversation_id}")
async def extract_tasks_from_conversation(conversation_id: str, request: Request):
    await ensure_tasks_table()
    owner = owner_email(request)
    conv_id = _parse_uuid(conversation_id, "conversation_id")
    ai = get_ai_client()

    async with get_pool().acquire() as conn:
        conv = await conn.fetchrow("SELECT id, project_id FROM conversations WHERE id=$1", conv_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        msgs = await conn.fetch(
            "SELECT role, content FROM messages WHERE conversation_id=$1 ORDER BY created_at ASC LIMIT 100",
            conv_id,
        )

    if not msgs:
        return {"created": []}

    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)[:12000]

    try:
        msg = ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=2000,
            system=TASK_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
    except anthropic.BadRequestError as e:
        raise HTTPException(402, anthropic_error_message(e))
    except Exception as e:
        raise HTTPException(502, str(e))

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(502, "Claude returned invalid JSON while extracting tasks.")

    created = []
    async with get_pool().acquire() as conn:
        for item in items[:20]:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            priority = item.get("priority") if item.get("priority") in _TASK_PRIORITIES else "medium"
            row = await conn.fetchrow('''
                INSERT INTO tasks (owner_email, project_id, conversation_id, title, notes, priority, category, source)
                VALUES ($1,$2,$3,$4,$5,$6,$7,'ai') RETURNING *
            ''', owner, conv["project_id"], conv_id, title, item.get("notes"), priority, item.get("category"))
            created.append(_task_row_to_dict(row))

    return {"created": created}
