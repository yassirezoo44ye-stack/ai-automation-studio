"""PostgreSQL-backed task-run queue. Leases never automatically replay interrupted work."""
import asyncio
import contextlib
import json
import logging
import uuid

from fastapi import HTTPException

from app.core.project_plans import decode, plan_detail

log = logging.getLogger(__name__)
TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')


async def init_schema(conn):
    await conn.execute('''CREATE TABLE IF NOT EXISTS project_task_runs (
        id UUID PRIMARY KEY,
        plan_id UUID NOT NULL REFERENCES project_plans(id) ON DELETE CASCADE,
        node_id TEXT NOT NULL,
        task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        organization_id UUID,
        request_id UUID NOT NULL,
        runner TEXT NOT NULL CHECK(runner IN ('skill','inspect_project')),
        skill_id TEXT,
        snapshot JSONB NOT NULL,
        approval_hash TEXT NOT NULL,
        approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed','cancelled','interrupted')),
        output TEXT,
        error TEXT,
        log JSONB NOT NULL DEFAULT '["queued_after_approval"]',
        lease_id UUID,
        lease_until TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        UNIQUE(user_id, request_id)
    )''')
    await conn.execute("CREATE INDEX IF NOT EXISTS project_runs_pending ON project_task_runs(created_at) WHERE status='queued'")
    await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS project_runs_active_task ON project_task_runs(task_id) WHERE status IN ('queued','running')")


def serialize_run(row, detail=False):
    keys = ['id', 'plan_id', 'node_id', 'runner', 'skill_id', 'status', 'created_at', 'started_at', 'finished_at']
    data = {key: row[key] for key in keys}
    for key in ('id', 'plan_id'):
        data[key] = str(data[key])
    for key in ('created_at', 'started_at', 'finished_at'):
        data[key] = data[key].isoformat() if data[key] else None
    if detail:
        data.update(output=row['output'], error=row['error'], log=decode(row['log']),
                    snapshot=decode(row['snapshot']), approval_hash=row['approval_hash'],
                    acceptance_verified=False)
    return data


async def expire_leases(conn):
    await conn.execute("""UPDATE project_task_runs SET status='interrupted', finished_at=NOW(),
        error='Worker stopped or timed out. Review before starting another run.',
        log=log || '["interrupted_not_replayed"]'::jsonb
        WHERE status='running' AND lease_until < NOW()""")


async def cancel_run(conn, run_id):
    result = await conn.fetchrow("""UPDATE project_task_runs SET status='cancelled', finished_at=NOW(),
        log=log || '["cancelled_may_be_billed"]'::jsonb
        WHERE id=$1 AND status IN ('queued','running') RETURNING *""", run_id)
    if result is None:
        raise HTTPException(409, 'Run is already terminal')
    return result


class ProjectRunWorker:
    def __init__(self, pool, execute=None):
        self.pool = pool
        self.execute = execute or self.execute_agent
        self.loop_task = None
        self.active = set()
        self.stopping = False
        self.last_error = None

    async def start(self):
        self.stopping = False
        self.loop_task = asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping = True
        if self.loop_task:
            self.loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.loop_task
        for task in list(self.active):
            task.cancel()
        await asyncio.gather(*self.active, return_exceptions=True)

    async def loop(self):
        while not self.stopping:
            try:
                async with self.pool.acquire() as conn:
                    await expire_leases(conn)
                if len(self.active) < 2:
                    row = await self.claim()
                    if row:
                        task = asyncio.create_task(self.perform(row))
                        self.active.add(task)
                        task.add_done_callback(self.active.discard)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.last_error = type(error).__name__
                log.warning('Project run polling failed (%s)', self.last_error)
            await asyncio.sleep(2)

    async def claim(self):
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("""SELECT * FROM project_task_runs WHERE status='queued'
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""")
            if row is None:
                return None
            lease = uuid.uuid4()
            return await conn.fetchrow("""UPDATE project_task_runs SET status='running',
                started_at=NOW(),lease_id=$2,lease_until=NOW()+INTERVAL '150 seconds',
                log=log || '["started"]'::jsonb WHERE id=$1 RETURNING *""", row['id'], lease)

    async def execute_agent(self, row):
        from app.agents.kernel import get_agent_kernel
        snapshot = decode(row['snapshot'])
        agent_name = row['skill_id'] if row['runner'] == 'skill' else 'inspect_project'
        # Names come only from the server allowlist and stored approval, never from goal text.
        prompt = ('Produce a deliverable for this approved task. Report gaps honestly; '
                  'acceptance remains subject to user review.\n' + json.dumps(snapshot, ensure_ascii=False))
        return await get_agent_kernel().run(
            prompt, caller='project_plan', user_id=str(row['user_id']),
            organization_id=str(row['organization_id']) if row['organization_id'] else None,
            project_id=snapshot['project_id'], run_id=str(row['id']), forced_intent=agent_name,
        )

    async def authorized(self, row):
        async with self.pool.acquire() as conn:
            valid = await conn.fetchval('''SELECT 1 FROM project_plans p JOIN projects project ON project.id=p.project_id
                WHERE p.id=$1 AND p.user_id=$2 AND project.user_id=$2
                AND p.organization_id IS NOT DISTINCT FROM $3::uuid''', row['plan_id'], row['user_id'], row['organization_id'])
        if not valid:
            return False
        async with self.pool.acquire() as conn:
            detail = await plan_detail(conn, row['plan_id'], row['user_id'], row['organization_id'])
        node = next((n for n in detail['tasks'] if n['key'] == row['node_id']), None)
        if node is None or node['task_id'] is None or node['status'] != 'in_progress':
            return False
        states = {n['key']: n['status'] for n in detail['tasks']}
        if any(states.get(dep) != 'done' for dep in node['depends_on']):
            return False
        if row['organization_id']:
            from app.tenancy.service import get_tenancy_service
            return await get_tenancy_service().get_member_role(str(row['organization_id']), str(row['user_id'])) is not None
        return True

    async def perform(self, row):
        operation = None
        status, output, error = 'failed', None, 'Agent could not produce a result. Review and retry.'
        try:
            if not await self.authorized(row):
                error = 'Project access or organization membership is no longer valid'
                return
            # A run cancelled before starting must not invoke the model.
            async with self.pool.acquire() as conn:
                state = await conn.fetchval('SELECT status FROM project_task_runs WHERE id=$1', row['id'])
            if state != 'running':
                return
            operation = asyncio.create_task(self.execute(row))
            for _ in range(60):
                done, _pending = await asyncio.wait({operation}, timeout=2)
                if operation in done:
                    result = operation.result()
                    if result.success and (result.output or '').strip():
                        output = (result.output or '').replace(chr(0), chr(0xfffd))
                        if len(output) > 40000:
                            output = output[:39930] + '\n[Output truncated at the server limit; review before acceptance.]'
                        status, error = 'completed', None
                    elif row['runner'] == 'inspect_project':
                        error = 'Project inspection failed. Check that source files and manifests are present and safe.'
                    break
                async with self.pool.acquire() as conn:
                    state = await conn.fetchval('SELECT status FROM project_task_runs WHERE id=$1', row['id'])
                if state != 'running':
                    return
            else:
                status, error = 'interrupted', 'Run exceeded its execution window. Review before retrying.'
        except asyncio.CancelledError:
            status, error = 'interrupted', 'Worker shut down. Review before retrying.'
        except Exception:
            error = 'Agent execution failed. Review the task and try a new run.'
        finally:
            if operation and not operation.done():
                operation.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await operation
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("""UPDATE project_task_runs SET status=$3,output=$4,error=$5,finished_at=NOW(),
                        log=log || $6::jsonb WHERE id=$1 AND lease_id=$2 AND status='running'""",
                        row['id'], row['lease_id'], status, output, error,
                        json.dumps(['result_ready' if status == 'completed' else 'stopped_' + status]))
            except Exception as exc:
                log.warning('Project run finalization failed (%s)', type(exc).__name__)
