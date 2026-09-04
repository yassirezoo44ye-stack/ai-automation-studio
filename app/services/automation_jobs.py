"""
Automation JobQueue handlers — Phase 5 Gate 3.

Registered in app/factory.py lifespan for:
  automation.trigger.schedule  — schedule-based trigger dispatch
  automation.trigger.webhook   — webhook-based trigger dispatch

Both handlers:
  1. Load the automation definition (scoped to the job's organization_id)
  2. Build an Engine A WorkflowRun from the stored blueprint
  3. Execute via Engine A
  4. Persist the run and step state via AutomationPersistence

JobQueue payload contract:
  {
    "definition_id":   "uuid-string",
    "organization_id": "uuid-string",
    "trigger_id":      "string",
    "body":            {...}   # webhook body, schedule trigger only has context
  }
"""
from __future__ import annotations

import json
import logging

from app.core.jobs.queue import Job
from app.core.workflow.engine import WorkflowBuilder, RetryPolicy
from app.core.workflow.persistence import get_automation_persistence
from app.plugins.workflow_nodes import get_workflow_node_registry

log = logging.getLogger(__name__)


async def _run_definition(
    definition_id: str,
    org_id: str,
    extra_context: dict | None = None,
    triggered_by: str = "schedule",
) -> None:
    """Load a definition by ID+org, build a WorkflowRun, execute it, persist results."""
    import uuid
    from app.core.db import get_pool
    from app.core.workflow.engine import get_workflow_engine

    try:
        def_uuid = uuid.UUID(definition_id)
        org_uuid = uuid.UUID(org_id)
    except ValueError:
        log.error("automation job: invalid definition_id=%s or org_id=%s", definition_id, org_id)
        return

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, definition, is_active, deleted_at
            FROM automation_definitions
            WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL
            """,
            def_uuid, org_uuid,
        )

    if not row:
        log.warning(
            "automation job: definition %s not found for org %s — skipping",
            definition_id, org_id,
        )
        return
    if not row["is_active"]:
        log.info(
            "automation job: definition %s is inactive — skipping", definition_id,
        )
        return

    blueprint = row["definition"]
    if isinstance(blueprint, str):
        blueprint = json.loads(blueprint)

    nodes = blueprint.get("nodes", {})
    if not nodes:
        log.warning("automation job: definition %s has no nodes — skipping", definition_id)
        return

    registry = get_workflow_node_registry()
    builder = WorkflowBuilder(row["name"])

    for node_id, node in nodes.items():
        fn_name = node.get("step_fn_name")
        if not fn_name:
            log.warning("node %s in definition %s has no step_fn_name", node_id, definition_id)
            continue
        fn = registry.get_node(fn_name)
        if fn is None:
            log.warning(
                "unknown workflow node function %r in definition %s — skipping node",
                fn_name, definition_id,
            )
            continue
        retry_cfg = node.get("retry") or {}
        retry = RetryPolicy(
            max_attempts=int(retry_cfg.get("max_attempts", 3)),
            base_delay_s=float(retry_cfg.get("base_delay_s", 1.0)),
            max_delay_s=float(retry_cfg.get("max_delay_s", 30.0)),
        )
        builder.step(
            step_id=node_id,
            name=node.get("name", node_id),
            fn=fn,
            args=node.get("args", {}),
            depends_on=node.get("depends_on", []),
            retry=retry,
            timeout_s=node.get("timeout_s"),
            requires_approval=node.get("requires_approval", False),
        )

    context: dict = {
        "organization_id": org_id,
        "definition_id": definition_id,
    }
    if extra_context:
        context.update(extra_context)

    run = builder.build(context=context)
    persistence = get_automation_persistence()

    await persistence.upsert_run(
        run,
        definition_id=definition_id,
        triggered_by=triggered_by,
    )
    await persistence.upsert_steps_bulk(run.run_id, org_id, run.steps)

    engine = get_workflow_engine()
    try:
        result = await engine.execute(run, saga=True)
    except Exception:
        log.exception(
            "automation job: engine.execute failed for run %s (persisting failure)",
            run.run_id,
        )
        result = run  # result will have whatever state Engine A left it in

    await persistence.upsert_run(
        result,
        definition_id=definition_id,
        triggered_by=triggered_by,
    )
    await persistence.upsert_steps_bulk(result.run_id, org_id, result.steps)
    log.info(
        "automation job: run %s finished status=%s", result.run_id, result.status.value,
    )


async def handle_automation_schedule_trigger(job: Job) -> None:
    """JobQueue handler for automation.trigger.schedule jobs."""
    payload = job.payload
    definition_id = payload.get("definition_id")
    org_id = payload.get("organization_id")
    trigger_id = payload.get("trigger_id")

    if not definition_id or not org_id:
        log.error(
            "automation schedule handler: missing definition_id or org_id in payload %s",
            payload,
        )
        return

    job.append_log(f"Dispatching schedule trigger {trigger_id} for definition {definition_id}")
    await _run_definition(
        definition_id=definition_id,
        org_id=org_id,
        extra_context={"trigger_id": trigger_id, "trigger_type": "schedule"},
        triggered_by="schedule",
    )


async def handle_automation_webhook_trigger(job: Job) -> None:
    """JobQueue handler for automation.trigger.webhook jobs."""
    payload = job.payload
    definition_id = payload.get("definition_id")
    org_id = payload.get("organization_id")
    trigger_id = payload.get("trigger_id")
    body = payload.get("body", {})

    if not definition_id or not org_id:
        log.error(
            "automation webhook handler: missing definition_id or org_id in payload %s",
            payload,
        )
        return

    job.append_log(f"Dispatching webhook trigger {trigger_id} for definition {definition_id}")
    await _run_definition(
        definition_id=definition_id,
        org_id=org_id,
        extra_context={
            "trigger_id": trigger_id,
            "trigger_type": "webhook",
            "webhook_body": body,
        },
        triggered_by="webhook",
    )
