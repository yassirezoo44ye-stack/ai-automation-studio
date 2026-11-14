# Durable project planning

The AI workspace has a **Projects & plans / المشاريع والخطط** tab. A signed-in
user describes an idea, generates a structured draft, edits task titles and
acceptance criteria, then explicitly creates a private project, saved plan and
linked tasks. Reopening the tab lists saved plans and restores task progress
from PostgreSQL. The browser is not the source of truth.

## Behavior and boundaries

- Drafting uses the existing InferenceEngine with the verified caller and current
  organization. Skill instructions supplement the JSON output contract. No
  tools or autonomous execution are enabled. Invalid/provider-failed responses
  return a controlled error; there is no fabricated fallback plan.
- The reviewed draft is validated again on save: bounded fields, unique task
  keys, existing prerequisites and an acyclic dependency graph.
- Save creates a project (or verifies an explicit existing project), the plan,
  and all task links in one database transaction. A caller-scoped request UUID
  and transaction lock prevent concurrent/retried saves from creating duplicates.
  Reusing that UUID for different content/context returns 409. A failure rolls
  the complete transaction back.
- Plans are private to the verified user and exact organization context,
  including the personal/no-organization context. Projects retain the existing
  per-user ownership model; this does not add shared-team project permissions.
- Starting/completing a task requires its prerequisites to be done. Reopening a
  completed prerequisite requires resetting active/completed dependents first.
  The same checks apply through the existing Tasks update API, under a parent
  plan row lock to serialize concurrent progress changes.
- Task status is manually reported progress, not evidence that an agent ran code,
  deployed a resource, or verified an acceptance criterion. Criteria remain a
  human-reviewed checklist.
- Deleting a task through the existing Tasks API leaves its planned node marked
  deleted; dependent work remains blocked. Deleting its project cascades the plan
  and links. This feature adds no plan-delete or task-recovery interface.

## API

| Method | Path | Result |
| --- | --- | --- |
| POST | `/api/project-plans/draft` | Validated draft; no project/task writes |
| POST | `/api/project-plans` | Atomic save; body has `request_id`, `draft`, optional `project_id` |
| GET | `/api/project-plans` | Latest 100 private plans; optional `project_id` filter |
| GET | `/api/project-plans/{id}` | Saved criteria, dependencies and current task states |
| PUT | `/api/project-plans/{id}/tasks/{key}` | Persist pending/in_progress/done with dependency checks |

Use the existing authentication and organization headers. User and organization
IDs are never accepted as authoritative request-body fields.

## Existing planning API

The older `/api/plan` endpoint family remains available for execution estimates.
Its bounded in-process cache is now scoped to the verified user and organization;
it is not durable storage. Registry visibility and project ownership are verified
before planning. `/execute` refuses plans requiring approval or failing validation
and runs the exact validated schedule through forced agent selection, rather than
asking another planner to invent a different execution plan. This does not add an
approval UI for those legacy executions.

## Rollout and verification

`app.factory.lifespan` initializes `project_plans` and `project_plan_tasks` after
the existing task tables, following the repository's actual schema-init mechanism.
Both tables and the owner index use idempotent creation. Existing projects and
tasks are unchanged; older app versions can ignore the additional tables.

Real PostgreSQL integration tests are in `tests/test_project_plans.py`:

```bash
PROJECT_PLAN_TEST_DATABASE_URL=postgresql://... python -m pytest tests/test_project_plans.py tests/test_planning_owner_scope.py -q
```

CI's existing `STUDY_TEST_DATABASE_URL` is also accepted. Tests isolate themselves
in temporary schemas and exercise replay/concurrent saves, full rollback,
user/organization/project isolation, dependency guards through both APIs, and
provider-output validation. Provider completions are fixtures, not live paid calls.

The browser verification used the actual component and API against PostgreSQL 16,
with a deterministic provider and a loopback-only test identity. It covered draft,
review/edit, save, task progress, reload, reopen and completion without page errors.
It does not establish live-provider quality or production account behavior.
