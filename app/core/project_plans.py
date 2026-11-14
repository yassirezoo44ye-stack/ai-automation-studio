"""Durable private project plans, linked tasks, and dependency validation."""
import json
import uuid
from fastapi import HTTPException


async def plan_organization(request):
    from app.tenancy.context import optional_org_id
    requested = (request.headers.get('X-Organization-Id') or request.query_params.get('org_id')
                 or request.path_params.get('org_id'))
    if requested:
        try:
            uuid.UUID(requested)
        except ValueError:
            raise HTTPException(400, 'Invalid organization context') from None
    org = await optional_org_id(request)
    if requested and org is None:
        raise HTTPException(404, 'Organization not found')
    return uuid.UUID(str(org)) if org else None


async def init_schema(conn):
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS project_plans (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            organization_id UUID,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            request_id UUID NOT NULL,
            title TEXT NOT NULL,
            goal TEXT NOT NULL,
            body JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, request_id)
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS project_plan_tasks (
            plan_id UUID NOT NULL REFERENCES project_plans(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL,
            task_id UUID NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
            PRIMARY KEY(plan_id, node_id)
        )
    ''')
    await conn.execute('CREATE INDEX IF NOT EXISTS project_plans_owner ON project_plans(user_id, organization_id, created_at DESC)')
    from app.core.project_runs import init_schema as init_runs
    await init_runs(conn)


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


async def plan_detail(conn, plan_id, user_id, org_id):
    row = await conn.fetchrow('''
        SELECT p.*, project.name AS project_name FROM project_plans p
        JOIN projects project ON project.id=p.project_id AND project.user_id=p.user_id
        WHERE p.id=$1 AND p.user_id=$2 AND p.organization_id IS NOT DISTINCT FROM $3::uuid
    ''', plan_id, user_id, org_id)
    if not row:
        raise HTTPException(404, 'Plan not found')
    states = await conn.fetch('''
        SELECT link.node_id, t.id, t.status FROM project_plan_tasks link
        JOIN tasks t ON t.id=link.task_id WHERE link.plan_id=$1
    ''', plan_id)
    state_map = {s['node_id']: s for s in states}
    body = decode(row['body'])
    nodes = [{**node, 'task_id': str(state_map[node['key']]['id']) if node['key'] in state_map else None,
              'status': state_map[node['key']]['status'] if node['key'] in state_map else 'deleted'}
             for node in body['tasks']]
    return {'id': str(row['id']), 'project_id': str(row['project_id']),
            'project_name': row['project_name'], 'title': row['title'], 'goal': row['goal'],
            'tasks': nodes, 'created_at': row['created_at'].isoformat(),
            'completed': sum(n['status'] == 'done' for n in nodes), 'total': len(nodes)}


async def validate_task_transition(conn, task_id, owner_email, org_id, status):
    """Serialize updates per plan, including updates through the legacy Tasks API."""
    plan = await conn.fetchrow('''
        SELECT p.id, p.body, p.organization_id, link.node_id FROM project_plans p
        JOIN project_plan_tasks link ON link.plan_id=p.id
        JOIN tasks t ON t.id=link.task_id
        WHERE t.id=$1 AND t.owner_email=$2 FOR UPDATE OF p
    ''', task_id, owner_email)
    if not plan:
        return
    if plan['organization_id'] != org_id:
        raise HTTPException(404, 'Task not found')
    active = await conn.fetchval("SELECT 1 FROM project_task_runs WHERE task_id=$1 AND status IN ('queued','running')", task_id)
    if active:
        raise HTTPException(409, 'Cancel or finish the active run before modifying this task')
    if status is None:
        return
    nodes = decode(plan['body'])['tasks']
    states = await conn.fetch('''
        SELECT link.node_id, t.status FROM project_plan_tasks link
        JOIN tasks t ON t.id=link.task_id WHERE link.plan_id=$1
    ''', plan['id'])
    current = {s['node_id']: s['status'] for s in states}
    node = next(n for n in nodes if n['key'] == plan['node_id'])
    if status in ('in_progress', 'done') and any(current.get(dep) != 'done' for dep in node['depends_on']):
        raise HTTPException(409, 'Complete prerequisite tasks first')
    if status != 'done' and any(plan['node_id'] in n['depends_on'] and
                                current.get(n['key']) in ('in_progress', 'done') for n in nodes):
        raise HTTPException(409, 'Reset dependent tasks first')
