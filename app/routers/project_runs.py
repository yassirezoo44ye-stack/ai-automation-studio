"""Explicitly approved, owner-scoped runs of immutable plan tasks."""
import hashlib
import json
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, model_validator

from app.core.ai.skills import validate_skill_ids
from app.core.auth import owner_email
from app.core.db import get_pool
from app.core.project_plans import plan_detail, validate_task_transition
from app.core.project_runs import cancel_run, serialize_run
from app.core.security import ai_rate_limit
from app.routers.project_plans import identity

router = APIRouter(prefix='/api/project-plans', tags=['project-runs'])


class StartRun(BaseModel):
    request_id: uuid.UUID
    approved: Literal[True]
    runner: Literal['skill', 'inspect_project']
    skill_id: str | None = None

    @model_validator(mode='after')
    def valid_runner(self):
        if self.runner == 'skill':
            if self.skill_id is None:
                raise ValueError('Select a skill')
            validate_skill_ids([self.skill_id])
        elif self.skill_id is not None:
            raise ValueError('Inspection does not use a skill')
        return self


@router.post('/{plan_id}/tasks/{node_id}/runs', status_code=202)
async def start_run(plan_id: uuid.UUID, node_id: str, body: StartRun, request: Request):
    ai_rate_limit(request)
    uid, org = await identity(request)
    owner = owner_email(request)
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'plan-runs:' + str(uid))
        owned = await conn.fetchval('''SELECT id FROM project_plans WHERE id=$1 AND user_id=$2
            AND organization_id IS NOT DISTINCT FROM $3::uuid FOR UPDATE''', plan_id, uid, org)
        if not owned:
            raise HTTPException(404, 'Plan not found')
        detail = await plan_detail(conn, plan_id, uid, org)
        previous = await conn.fetchrow('SELECT * FROM project_task_runs WHERE user_id=$1 AND request_id=$2', uid, body.request_id)
        if previous:
            if (previous['plan_id'] != plan_id or previous['node_id'] != node_id or
                    previous['organization_id'] != org or previous['runner'] != body.runner or previous['skill_id'] != body.skill_id):
                raise HTTPException(409, 'Request ID already used for another run')
            return serialize_run(previous)
        node = next((n for n in detail['tasks'] if n['key'] == node_id), None)
        if node is None or node['task_id'] is None:
            raise HTTPException(404, 'Task not found')
        if node['status'] == 'done':
            raise HTTPException(409, 'Reopen the task before starting another run')
        tid = uuid.UUID(node['task_id'])
        await validate_task_transition(conn, tid, owner, org, 'in_progress')
        count = await conn.fetchval("SELECT COUNT(*) FROM project_task_runs WHERE user_id=$1 AND status IN ('queued','running')", uid)
        if count >= 3:
            raise HTTPException(429, 'At most three active runs per user')
        snapshot = {'project_id': detail['project_id'], 'goal': detail['goal'],
                    'task': {key: node[key] for key in ('key', 'title', 'acceptance', 'depends_on', 'priority')}}
        canonical = json.dumps({'snapshot': snapshot, 'runner': body.runner, 'skill_id': body.skill_id}, sort_keys=True, ensure_ascii=False)
        row = await conn.fetchrow('''INSERT INTO project_task_runs
            (id,plan_id,node_id,task_id,user_id,organization_id,request_id,runner,skill_id,snapshot,approval_hash)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11) RETURNING *''',
            uuid.uuid4(), plan_id, node_id, tid, uid, org, body.request_id, body.runner, body.skill_id,
            json.dumps(snapshot, ensure_ascii=False), hashlib.sha256(canonical.encode()).hexdigest())
        await conn.execute("UPDATE tasks SET status='in_progress',updated_at=NOW(),completed_at=NULL WHERE id=$1", tid)
        return serialize_run(row)


@router.get('/{plan_id}/runs')
async def list_runs(plan_id: uuid.UUID, request: Request):
    uid, org = await identity(request)
    async with get_pool().acquire() as conn:
        await plan_detail(conn, plan_id, uid, org)
        rows = await conn.fetch("SELECT * FROM project_task_runs WHERE plan_id=$1 AND user_id=$2 ORDER BY (status IN ('queued','running')) DESC, created_at DESC LIMIT 50", plan_id, uid)
        return {'runs': [serialize_run(row) for row in rows]}


async def owned_run(conn, plan_id, run_id, uid, org):
    await plan_detail(conn, plan_id, uid, org)
    row = await conn.fetchrow('SELECT * FROM project_task_runs WHERE id=$1 AND plan_id=$2 AND user_id=$3', run_id, plan_id, uid)
    if row is None:
        raise HTTPException(404, 'Run not found')
    return row


@router.get('/{plan_id}/runs/{run_id}')
async def get_run(plan_id: uuid.UUID, run_id: uuid.UUID, request: Request):
    uid, org = await identity(request)
    async with get_pool().acquire() as conn:
        row = await owned_run(conn, plan_id, run_id, uid, org)
        return serialize_run(row, detail=True)


@router.delete('/{plan_id}/runs/{run_id}')
async def cancel(plan_id: uuid.UUID, run_id: uuid.UUID, request: Request):
    uid, org = await identity(request)
    async with get_pool().acquire() as conn:
        row = await owned_run(conn, plan_id, run_id, uid, org)
        if row['status'] != 'cancelled':
            row = await cancel_run(conn, run_id)
        return serialize_run(row, detail=True)


@router.get('/{plan_id}/runs/{run_id}/artifact')
async def artifact(plan_id: uuid.UUID, run_id: uuid.UUID, request: Request):
    uid, org = await identity(request)
    async with get_pool().acquire() as conn:
        row = await owned_run(conn, plan_id, run_id, uid, org)
    if row['status'] != 'completed' or row['output'] is None:
        raise HTTPException(409, 'No completed artifact is available')
    return Response(row['output'], media_type='text/plain',
                    headers={'Content-Disposition': f'attachment; filename="flow-run-{run_id}.txt"'})
