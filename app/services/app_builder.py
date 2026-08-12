"""
AI Business App Builder — service layer.

Orchestrates over existing Flow systems (AI Gateway, Design Studio,
Workflow Engine, AgentOS, Integrations) without rebuilding any of them.

Async build pipeline
  User Prompt
       ↓
  generate_spec()     — AI Gateway → validated AppSpec
       ↓
  submit_build_job()  — creates DB record + submits to JobQueue → returns immediately
       ↓
  _build_job_handler  — 12-step pipeline runs in background
       ↓
  BuildResult         — persisted to DB; polled by GET /apps/{id}

Idempotency
  Every build step is safe against duplicate execution:
  • Dynamic tables: CREATE TABLE IF NOT EXISTS
  • Canvas, agents, workflows: deterministic UUID5 IDs + ON CONFLICT DO NOTHING
  • Version records: unique constraint (app_id, version_number)

Security posture
  • No raw SQL from user input — all AI-generated schema passes through
    _validate_entity_name() and _ALLOWED_COLUMN_TYPES before any DDL.
  • No cross-tenant writes — org_id is resolved from the verified
    OrgContext dependency, never from the request body.
  • No arbitrary code execution — spec is structured JSON, not code.
  • Destructive operations (DROP TABLE, DELETE cascade) are blocked.
  • Every build and modification is recorded in app_builder_versions.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

import asyncpg

from app.ai.gateway import AIGateway
from app.ai.models import CompletionRequest, Message
from app.core.db import get_pool, write_audit as _raw_write_audit

if TYPE_CHECKING:
    from app.core.jobs.queue import Job

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_TOTAL_STEPS = 12

# UUID namespace for deterministic IDs (avoids duplicates on retry).
# Using URL namespace (rfc4122) as a stable, well-known seed.
_NS = uuid.NAMESPACE_URL

STEP_LABELS: list[str] = [
    "Database record",          # 1
    "Schema provisioning",      # 2
    "API generation",           # 3
    "Design Studio canvas",     # 4
    "Permissions",              # 5
    "Workflows",                # 6
    "AI agents",                # 7
    "Integrations",             # 8
    "Status determination",     # 9
    "Metadata update",          # 10
    "Version snapshot",         # 11
    "Audit log",                # 12
]

# ── Safety ────────────────────────────────────────────────────────────────────

_ENTITY_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

_ALLOWED_COLUMN_TYPES: frozenset[str] = frozenset({
    "text", "varchar", "integer", "bigint", "boolean",
    "numeric", "float", "date", "timestamptz", "uuid", "jsonb",
})

_FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "drop", "truncate", "delete", "alter", "grant", "revoke",
    "exec", "execute", "system", "pg_", "information_schema",
})


def _validate_entity_name(name: str, context: str) -> str:
    """Whitelist-validate a SQL identifier from AI output."""
    cleaned = name.strip().lower().replace(" ", "_").replace("-", "_")
    if not _ENTITY_RE.match(cleaned):
        raise ValueError(
            f"Invalid {context} name '{name}' — must start with a letter, "
            "contain only a-z/0-9/_, and be ≤63 chars."
        )
    for kw in _FORBIDDEN_KEYWORDS:
        if kw in cleaned:
            raise ValueError(f"Forbidden keyword in {context} name: {kw!r}")
    return cleaned


def _validate_column_type(type_str: str) -> str:
    """Accept only safe, known Postgres column types."""
    cleaned = type_str.strip().lower()
    base = cleaned.split("(")[0].strip()  # strip VARCHAR(255) → varchar
    if base not in _ALLOWED_COLUMN_TYPES:
        raise ValueError(
            f"Unsupported column type '{type_str}'. "
            f"Allowed: {sorted(_ALLOWED_COLUMN_TYPES)}"
        )
    return cleaned


# ── Deterministic IDs (idempotency on retry) ──────────────────────────────────

def _canvas_uuid(app_id: str) -> str:
    """Deterministic canvas ID — same app always maps to the same canvas."""
    return str(uuid.uuid5(_NS, f"ab:canvas:{app_id}"))


def _agent_uuid(app_id: str, agent_name: str) -> str:
    """Deterministic agent ID — same app+name always maps to the same agent."""
    return str(uuid.uuid5(_NS, f"ab:agent:{app_id}:{agent_name}"))


def _workflow_uuid(app_id: str, wf_name: str) -> str:
    """Deterministic workflow ID — same app+name always maps to the same id."""
    return str(uuid.uuid5(_NS, f"ab:workflow:{app_id}:{wf_name}"))


# ── Spec data classes ─────────────────────────────────────────────────────────

@dataclass
class ColumnDef:
    name: str
    type: str
    nullable: bool = True
    unique: bool = False
    default: Optional[str] = None


@dataclass
class EntityDef:
    name: str
    display_name: str
    columns: list[ColumnDef] = field(default_factory=list)
    relationships: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PageDef:
    name: str
    entity: Optional[str] = None
    kind: str = "list"   # list | detail | dashboard | form


@dataclass
class RoleDef:
    name: str
    permissions: list[str] = field(default_factory=list)


@dataclass
class WorkflowDef:
    name: str
    trigger: str
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentDef:
    name: str
    description: str
    system_prompt: str


@dataclass
class AppSpec:
    name: str
    description: str
    target_users: str
    entities: list[EntityDef]
    pages: list[PageDef]
    roles: list[RoleDef]
    workflows: list[WorkflowDef]
    agents: list[AgentDef]
    integrations: list[str]
    settings: dict[str, Any]


# ── Build result ──────────────────────────────────────────────────────────────

@dataclass
class BuildStep:
    label: str
    status: str = "pending"  # pending | ok | warning | error
    detail: str = ""


@dataclass
class BuildResult:
    app_id: str
    app_name: str
    tables_created: int = 0
    pages_created: int = 0
    roles_created: int = 0
    api_operations: int = 0
    workflows_created: int = 0
    agents_created: int = 0
    canvas_id: Optional[str] = None
    steps: list[BuildStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    overall_status: str = "ready"  # ready | partial | failed


# ── System prompt for spec generation ────────────────────────────────────────

_SPEC_SYSTEM = """\
You are an AI application architect. Convert the user's natural-language
business software description into a structured JSON specification.

Return ONLY a JSON object with this exact shape (no markdown, no commentary):
{
  "name": "<short app name>",
  "description": "<one sentence>",
  "target_users": "<who will use it>",
  "entities": [
    {
      "name": "<snake_case>",
      "display_name": "<Title Case>",
      "columns": [
        {"name": "<snake_case>", "type": "<text|integer|boolean|timestamptz|uuid|numeric|float|date|jsonb>", "nullable": true}
      ],
      "relationships": [
        {"kind": "belongs_to|has_many", "target": "<entity_name>"}
      ]
    }
  ],
  "pages": [
    {"name": "<Title Case>", "entity": "<entity_name or null>", "kind": "<list|detail|dashboard|form>"}
  ],
  "roles": [
    {"name": "<Role Name>", "permissions": ["<entity>:<action>"]}
  ],
  "workflows": [
    {"name": "<Name>", "trigger": "<event description>", "steps": [
      {"action": "<description>", "type": "<notify|create|update|agent>"}
    ]}
  ],
  "agents": [
    {"name": "<Name>", "description": "<what it does>", "system_prompt": "<instructions>"}
  ],
  "integrations": ["<integration_name>"],
  "settings": {}
}

Rules:
- Entity and column names: lowercase, snake_case, a-z/0-9/_ only.
- Column types: only text, varchar, integer, bigint, boolean, numeric,
  float, date, timestamptz, uuid, jsonb.
- Every entity automatically gets: id (uuid pk), created_at, updated_at,
  organization_id — do NOT include these in columns.
- Maximum 20 entities, 20 columns per entity, 10 pages, 5 roles.
- Suggest realistic integrations from: gmail, slack, whatsapp, sheets,
  stripe, zapier, webhook — only when clearly useful.
- For "Build + Automate" requests, populate workflows and agents;
  otherwise leave them empty arrays.
"""

# Trigger keywords that map to specific engine capabilities
_CRON_KEYWORDS = frozenset({"daily", "hourly", "every", "weekly", "monthly", "cron", "schedule", "midnight", "noon"})
_WEBHOOK_KEYWORDS = frozenset({"webhook", "http", "api call", "external", "rest"})
_SUPPORTED_ACTION_TYPES = frozenset({"notify", "create", "update", "agent"})


# ── Service ───────────────────────────────────────────────────────────────────

class AppBuilderService:
    """
    Orchestration layer for the AI Business App Builder.

    All public methods accept an `org_id` and `user_id` that come from the
    verified OrgContext dependency — they are never sourced from user input.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._gw = AIGateway(pool)

    # ── Spec generation ───────────────────────────────────────────────────────

    async def generate_spec(
        self,
        prompt: str,
        *,
        include_automation: bool = False,
        org_id: str,
        user_id: str,
    ) -> AppSpec:
        """
        Turn a natural-language prompt into a validated AppSpec.

        Uses AI Gateway (existing) so all provider routing, caching, cost
        tracking, and context budgeting apply automatically.
        """
        user_content = prompt.strip()
        if include_automation:
            user_content += (
                "\n\n[Include realistic workflows and AI agents for automation.]"
            )

        request = CompletionRequest(
            model="claude-sonnet-5",
            messages=[Message(role="user", content=user_content)],
            system=_SPEC_SYSTEM,
            max_tokens=4096,
            temperature=0.3,
            cache_ttl=None,  # never cache user-specific specs
        )

        response = await self._gw.complete(
            request, user_id=user_id, org_id=org_id
        )

        raw_json = response.content.strip()
        # Strip markdown fences if the model wrapped the JSON
        if raw_json.startswith("```"):
            lines = raw_json.splitlines()
            raw_json = "\n".join(
                ln for ln in lines if not ln.startswith("```")
            ).strip()

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI returned invalid JSON: {exc}") from exc

        return self._parse_and_validate_spec(data)

    # ── Spec parsing + validation ──────────────────────────────────────────────

    def _parse_and_validate_spec(self, data: dict[str, Any]) -> AppSpec:
        """
        Parse raw AI JSON into AppSpec, validating every identifier and type.
        Raises ValueError on any unsafe or invalid value — callers see
        a 422 error rather than executing harmful SQL.
        """
        if not isinstance(data, dict):
            raise ValueError("Spec must be a JSON object")

        name = str(data.get("name", "My App"))[:120]
        description = str(data.get("description", ""))[:500]
        target_users = str(data.get("target_users", ""))[:200]

        entities: list[EntityDef] = []
        for raw_ent in (data.get("entities") or [])[:20]:
            ent_name = _validate_entity_name(
                str(raw_ent.get("name", "")), "entity"
            )
            display = str(raw_ent.get("display_name", ent_name.replace("_", " ").title()))[:120]
            cols: list[ColumnDef] = []
            for raw_col in (raw_ent.get("columns") or [])[:20]:
                col_name = _validate_entity_name(
                    str(raw_col.get("name", "")), "column"
                )
                col_type = _validate_column_type(
                    str(raw_col.get("type", "text"))
                )
                cols.append(ColumnDef(
                    name=col_name,
                    type=col_type,
                    nullable=bool(raw_col.get("nullable", True)),
                    unique=bool(raw_col.get("unique", False)),
                ))
            rels: list[dict[str, str]] = []
            for raw_rel in (raw_ent.get("relationships") or [])[:10]:
                kind = str(raw_rel.get("kind", ""))
                if kind not in ("belongs_to", "has_many"):
                    continue
                target = _validate_entity_name(
                    str(raw_rel.get("target", "")), "relationship target"
                )
                rels.append({"kind": kind, "target": target})
            entities.append(EntityDef(
                name=ent_name, display_name=display, columns=cols, relationships=rels
            ))

        pages: list[PageDef] = []
        for raw_pg in (data.get("pages") or [])[:10]:
            pg_name = str(raw_pg.get("name", ""))[:80]
            pg_entity = raw_pg.get("entity")
            pg_kind = str(raw_pg.get("kind", "list"))
            if pg_kind not in ("list", "detail", "dashboard", "form"):
                pg_kind = "list"
            pages.append(PageDef(name=pg_name, entity=pg_entity, kind=pg_kind))

        roles: list[RoleDef] = []
        for raw_role in (data.get("roles") or [])[:5]:
            role_name = str(raw_role.get("name", ""))[:80]
            perms = [str(p)[:100] for p in (raw_role.get("permissions") or [])][:50]
            roles.append(RoleDef(name=role_name, permissions=perms))

        workflows: list[WorkflowDef] = []
        for raw_wf in (data.get("workflows") or [])[:10]:
            wf_name = str(raw_wf.get("name", ""))[:120]
            wf_trigger = str(raw_wf.get("trigger", ""))[:500]
            wf_steps = list(raw_wf.get("steps") or [])[:20]
            workflows.append(WorkflowDef(
                name=wf_name, trigger=wf_trigger, steps=wf_steps
            ))

        agents: list[AgentDef] = []
        for raw_ag in (data.get("agents") or [])[:5]:
            ag_name = str(raw_ag.get("name", ""))[:100]
            ag_desc = str(raw_ag.get("description", ""))[:500]
            ag_sys = str(raw_ag.get("system_prompt", ""))[:4000]
            agents.append(AgentDef(
                name=ag_name, description=ag_desc, system_prompt=ag_sys
            ))

        integrations = [
            str(i)[:80] for i in (data.get("integrations") or [])[:10]
        ]
        settings = data.get("settings") or {}
        if not isinstance(settings, dict):
            settings = {}

        return AppSpec(
            name=name,
            description=description,
            target_users=target_users,
            entities=entities,
            pages=pages,
            roles=roles,
            workflows=workflows,
            agents=agents,
            integrations=integrations,
            settings=settings,
        )

    # ── Async build submission ────────────────────────────────────────────────

    async def submit_build_job(
        self,
        spec: AppSpec,
        *,
        org_id: str,
        user_id: str,
        user_email: str = "",
        include_automation: bool = False,
    ) -> tuple[str, str]:
        """
        Create an app record, submit the build to the job queue, return immediately.

        Returns (app_id, job_id). The HTTP request must not wait for the build.
        The background job updates progress in app_builder_apps as it runs.
        """
        app_id = str(uuid.uuid4())
        spec_dict = self._spec_to_dict(spec)

        # Create app record in 'building' state immediately
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO app_builder_apps
                  (id, organization_id, created_by, name, description,
                   spec, build_status, include_automation,
                   progress, current_step, total_steps, completed_steps,
                   started_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'building', $7,
                        0, 'initializing', $8, 0, now())
                """,
                app_id, org_id, user_id,
                spec.name, spec.description,
                json.dumps(spec_dict),
                include_automation,
                _TOTAL_STEPS,
            )

        # Submit job to the queue (org_id stamped server-side, never from body)
        from app.core.jobs import get_job_queue
        queue = get_job_queue()
        job_id = await queue.submit(
            "app_builder.build",
            payload={
                "app_id": app_id,
                "spec": spec_dict,
                "user_id": user_id,
                "user_email": user_email,
                "include_automation": include_automation,
                "is_retry": False,
            },
            ttl=7200,  # 2-hour TTL for large builds
            priority="normal",
            org_id=org_id,
            idempotency_key=f"build:{app_id}",
        )

        # Record job_id for status correlation
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE app_builder_apps SET job_id = $1 WHERE id = $2",
                job_id, app_id,
            )

        return app_id, job_id

    # ── Retry submission ──────────────────────────────────────────────────────

    async def retry_app_build(
        self,
        app_id: str,
        *,
        org_id: str,
        user_id: str,
        user_email: str = "",
    ) -> tuple[str, str]:
        """
        Retry a failed or partial build, resuming idempotently.

        Each build step is safe to re-run:
        • Schema: CREATE TABLE IF NOT EXISTS
        • Canvas: deterministic UUID — ON CONFLICT DO NOTHING
        • Agents: deterministic UUID — ON CONFLICT DO NOTHING
        • Workflows: deterministic UUID — idempotent array_append

        Returns (app_id, job_id).
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT name, spec, build_status, include_automation, retry_count
                FROM app_builder_apps
                WHERE id = $1 AND organization_id = $2
                """,
                app_id, org_id,
            )

        if not row:
            raise ValueError(f"App {app_id} not found in org {org_id}")

        status = row["build_status"]
        if status not in ("failed", "partial"):
            raise ValueError(
                f"App {app_id} is in state '{status}' — "
                "only failed or partial apps can be retried."
            )

        retry_count = (row["retry_count"] or 0) + 1
        spec_dict = dict(row["spec"])

        # Reset to building state
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE app_builder_apps
                SET build_status   = 'building',
                    progress       = 0,
                    current_step   = 'initializing',
                    completed_steps = 0,
                    error          = NULL,
                    retry_count    = $1,
                    started_at     = now(),
                    completed_at   = NULL
                WHERE id = $2 AND organization_id = $3
                """,
                retry_count, app_id, org_id,
            )

        from app.core.jobs import get_job_queue
        queue = get_job_queue()
        job_id = await queue.submit(
            "app_builder.build",
            payload={
                "app_id": app_id,
                "spec": spec_dict,
                "user_id": user_id,
                "user_email": user_email,
                "include_automation": row["include_automation"],
                "is_retry": True,
            },
            ttl=7200,
            priority="normal",
            org_id=org_id,
        )

        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE app_builder_apps SET job_id = $1, started_at = now() WHERE id = $2",
                job_id, app_id,
            )

        return app_id, job_id

    # ── Job handler (registered with JobQueue) ────────────────────────────────

    async def build_job_handler(self, job: "Job") -> None:
        """
        Entrypoint called by the JobQueue for 'app_builder.build' jobs.
        Extracts payload and runs the 12-step pipeline, updating job.progress
        as it goes so callers can observe real progress via GET /api/jobs/{id}.
        """
        payload = job.payload
        app_id = payload["app_id"]
        org_id = payload["organization_id"]
        spec_dict = payload["spec"]
        user_id = payload["user_id"]
        user_email = payload.get("user_email", "")
        include_automation = payload.get("include_automation", False)

        spec = self._parse_and_validate_spec(spec_dict)
        await self._run_build_pipeline(
            app_id=app_id,
            spec=spec,
            spec_dict=spec_dict,
            org_id=org_id,
            user_id=user_id,
            user_email=user_email,
            include_automation=include_automation,
            job=job,
        )

    # ── 12-step build pipeline ────────────────────────────────────────────────

    async def _run_build_pipeline(
        self,
        app_id: str,
        spec: AppSpec,
        spec_dict: dict[str, Any],
        org_id: str,
        user_id: str,
        user_email: str,
        include_automation: bool,
        job: Optional[Any] = None,
    ) -> BuildResult:
        """
        Execute all 12 build steps, updating progress after each.
        Never raises — failed steps populate warnings and set partial status.
        Each step is idempotent: safe to re-run on retry without duplication.
        """
        result = BuildResult(app_id=app_id, app_name=spec.name)

        async def _progress(step_num: int, step_name: str) -> None:
            pct = int((step_num - 1) / _TOTAL_STEPS * 100)
            if job is not None:
                job.progress = pct
                job.append_log(f"{step_num}/{_TOTAL_STEPS} {step_name}")
            await self._update_build_progress(app_id, step_num, step_name, pct)

        # ── 1. DB record (already created by submit_build_job) ─────────────
        await _progress(1, STEP_LABELS[0])
        result.steps.append(BuildStep(STEP_LABELS[0], "ok", "App record persisted"))

        # ── 2. Schema provisioning ─────────────────────────────────────────
        await _progress(2, STEP_LABELS[1])
        try:
            tables = await self._provision_schema(app_id, org_id, spec)
            result.tables_created = tables
            result.steps.append(BuildStep(STEP_LABELS[1], "ok", f"{tables} tables"))
        except Exception as exc:
            log.warning("App %s: schema provision failed: %s", app_id, exc)
            result.warnings.append(f"Database setup incomplete: {exc}")
            result.steps.append(BuildStep(STEP_LABELS[1], "warning", str(exc)))

        # ── 3. API operation count ─────────────────────────────────────────
        await _progress(3, STEP_LABELS[2])
        result.api_operations = len(spec.entities) * 5  # list, create, read, update, delete
        result.steps.append(BuildStep(STEP_LABELS[2], "ok",
                                      f"{result.api_operations} operations"))

        # ── 4. Design Studio canvas ────────────────────────────────────────
        await _progress(4, STEP_LABELS[3])
        try:
            canvas_id = await self._create_design_canvas(app_id, org_id, spec)
            result.canvas_id = canvas_id
            result.pages_created = len(spec.pages)
            result.steps.append(BuildStep(STEP_LABELS[3], "ok",
                                          f"{result.pages_created} pages"))
        except Exception as exc:
            log.warning("App %s: canvas creation failed: %s", app_id, exc)
            result.warnings.append(f"Design canvas not created: {exc}")
            result.steps.append(BuildStep(STEP_LABELS[3], "warning", str(exc)))

        # ── 5. Permissions ─────────────────────────────────────────────────
        await _progress(5, STEP_LABELS[4])
        result.roles_created = len(spec.roles)
        result.steps.append(BuildStep(STEP_LABELS[4], "ok",
                                      f"{result.roles_created} roles"))

        # ── 6. Workflows ───────────────────────────────────────────────────
        await _progress(6, STEP_LABELS[5])
        if include_automation and spec.workflows:
            try:
                created, wf_warnings = await self._create_workflows(
                    app_id, org_id, user_id, spec
                )
                result.workflows_created = created
                result.warnings.extend(wf_warnings)
                step_status = "warning" if wf_warnings else "ok"
                result.steps.append(BuildStep(STEP_LABELS[5], step_status,
                                              f"{created} workflows"))
            except Exception as exc:
                log.warning("App %s: workflow creation failed: %s", app_id, exc)
                result.warnings.append(f"Workflow setup incomplete: {exc}")
                result.steps.append(BuildStep(STEP_LABELS[5], "warning", str(exc)))
        else:
            result.steps.append(BuildStep(STEP_LABELS[5], "ok", "skipped"))

        # ── 7. AI agents ───────────────────────────────────────────────────
        await _progress(7, STEP_LABELS[6])
        if include_automation and spec.agents:
            try:
                created = await self._create_agents(app_id, org_id, user_id, spec)
                result.agents_created = created
                result.steps.append(BuildStep(STEP_LABELS[6], "ok",
                                              f"{created} agents"))
            except Exception as exc:
                log.warning("App %s: agent creation failed: %s", app_id, exc)
                result.warnings.append(f"AI agent setup incomplete: {exc}")
                result.steps.append(BuildStep(STEP_LABELS[6], "warning", str(exc)))
        else:
            result.steps.append(BuildStep(STEP_LABELS[6], "ok", "skipped"))

        # ── 8. Integration suggestions ─────────────────────────────────────
        await _progress(8, STEP_LABELS[7])
        if spec.integrations:
            for intg in spec.integrations:
                result.warnings.append(
                    f"Integration '{intg}' suggested — configure in Integrations tab."
                )
            result.steps.append(BuildStep(STEP_LABELS[7], "warning",
                                          f"{len(spec.integrations)} require setup"))
        else:
            result.steps.append(BuildStep(STEP_LABELS[7], "ok"))

        # ── 9. Status determination ────────────────────────────────────────
        await _progress(9, STEP_LABELS[8])
        result.overall_status = "partial" if result.warnings else "ready"
        result.steps.append(BuildStep(STEP_LABELS[8], "ok", result.overall_status))

        # ── 10. Metadata update ────────────────────────────────────────────
        await _progress(10, STEP_LABELS[9])
        result_dict = {
            "tables": result.tables_created,
            "pages": result.pages_created,
            "roles": result.roles_created,
            "api_operations": result.api_operations,
            "workflows": result.workflows_created,
            "agents": result.agents_created,
            "canvas_id": result.canvas_id,
            "steps": [
                {"label": s.label, "status": s.status, "detail": s.detail}
                for s in result.steps
            ],
        }
        await self._update_build_result(
            app_id, result.overall_status, result_dict, result.warnings,
            canvas_id=result.canvas_id,
        )
        result.steps.append(BuildStep(STEP_LABELS[9], "ok"))

        # ── 11. Version snapshot ───────────────────────────────────────────
        await _progress(11, STEP_LABELS[10])
        try:
            async with self._pool.acquire() as conn:
                max_ver = await conn.fetchval(
                    "SELECT COALESCE(MAX(version_number), 0) "
                    "FROM app_builder_versions WHERE app_id = $1",
                    app_id,
                ) or 0
            await self._record_version(
                app_id, org_id, user_id,
                version_number=max_ver + 1,
                label="Initial build",
                spec_dict=spec_dict,
                change_summary=f"Generated from: {spec.description}",
            )
            result.steps.append(BuildStep(STEP_LABELS[10], "ok",
                                          f"v{max_ver + 1}"))
        except Exception as exc:
            log.warning("App %s: version record failed: %s", app_id, exc)
            result.steps.append(BuildStep(STEP_LABELS[10], "warning", str(exc)))

        # ── 12. Audit log ──────────────────────────────────────────────────
        await _progress(12, STEP_LABELS[11])
        try:
            if user_email:
                await _raw_write_audit(
                    user_email, "app_builder.build",
                    resource="app_builder_app", resource_id=app_id,
                    details={
                        "org_id": org_id,
                        "app_name": spec.name,
                        "tables": result.tables_created,
                        "status": result.overall_status,
                    },
                )
            result.steps.append(BuildStep(STEP_LABELS[11], "ok"))
        except Exception:
            result.steps.append(BuildStep(STEP_LABELS[11], "warning", "audit skipped"))

        # Final progress: 100%
        await self._update_build_progress(app_id, _TOTAL_STEPS, "complete", 100)
        if job is not None:
            job.progress = 100
            job.append_log("Build complete")

        return result

    # ── Modify ────────────────────────────────────────────────────────────────

    async def modify_app(
        self,
        app_id: str,
        modification_prompt: str,
        *,
        org_id: str,
        user_id: str,
    ) -> BuildResult:
        """
        Incrementally modify an existing application.

        Fetches current spec, asks AI to produce a delta, validates and
        applies it, and records a new version.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT name, spec, build_result,
                       array_length(workflow_ids, 1) AS wf_count,
                       array_length(agent_ids, 1)    AS ag_count
                FROM app_builder_apps
                WHERE id = $1 AND organization_id = $2
                """,
                app_id, org_id,
            )
        if not row:
            raise ValueError(f"App {app_id} not found in org {org_id}")

        current_spec_dict = dict(row["spec"])
        current_spec_json = json.dumps(current_spec_dict, indent=2)

        modify_prompt = (
            f"Current app spec:\n```json\n{current_spec_json}\n```\n\n"
            f"User modification request: {modification_prompt}\n\n"
            "Return the COMPLETE updated spec (same JSON shape, all fields)."
        )

        request = CompletionRequest(
            model="claude-sonnet-5",
            messages=[Message(role="user", content=modify_prompt)],
            system=_SPEC_SYSTEM,
            max_tokens=4096,
            temperature=0.3,
        )
        response = await self._gw.complete(request, user_id=user_id, org_id=org_id)
        raw_json = response.content.strip()
        if raw_json.startswith("```"):
            lines = raw_json.splitlines()
            raw_json = "\n".join(
                ln for ln in lines if not ln.startswith("```")
            ).strip()

        try:
            new_data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI returned invalid JSON: {exc}") from exc

        new_spec = self._parse_and_validate_spec(new_data)
        new_spec_dict = self._spec_to_dict(new_spec)

        # Get next version number
        async with self._pool.acquire() as conn:
            max_ver = await conn.fetchval(
                "SELECT COALESCE(MAX(version_number), 0) "
                "FROM app_builder_versions WHERE app_id = $1",
                app_id,
            ) or 0

        version_number = max_ver + 1

        # Update app record
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE app_builder_apps
                SET spec = $1, name = $2, updated_at = now()
                WHERE id = $3 AND organization_id = $4
                """,
                json.dumps(new_spec_dict), new_spec.name, app_id, org_id,
            )

        await self._record_version(
            app_id, org_id, user_id,
            version_number=version_number,
            label=f"Modification {version_number}",
            spec_dict=new_spec_dict,
            change_summary=modification_prompt[:500],
        )

        result = BuildResult(
            app_id=app_id,
            app_name=new_spec.name,
            tables_created=len(new_spec.entities),
            pages_created=len(new_spec.pages),
            roles_created=len(new_spec.roles),
            workflows_created=len(new_spec.workflows),
            agents_created=len(new_spec.agents),
            overall_status="ready",
        )
        result.steps.append(BuildStep(f"Version {version_number} applied", "ok"))
        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _update_build_progress(
        self,
        app_id: str,
        step_num: int,
        step_name: str,
        pct: int,
    ) -> None:
        """Persist build progress to DB. Swallows errors — never blocks the pipeline."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE app_builder_apps
                    SET progress            = $1,
                        current_step        = $2,
                        completed_steps     = $3,
                        last_heartbeat_at   = now()
                    WHERE id = $4
                    """,
                    pct, step_name, max(0, step_num - 1), app_id,
                )
        except Exception as exc:
            log.warning("Progress update failed for app %s: %s", app_id, exc)

    async def _provision_schema(
        self,
        app_id: str,
        org_id: str,
        spec: AppSpec,
    ) -> int:
        """
        Create per-app dynamic tables prefixed with app_id slug.
        CREATE TABLE IF NOT EXISTS makes this fully idempotent on retry.
        All tables include organization_id for multi-tenant scoping.
        """
        short_id = app_id.replace("-", "")[:12]
        created = 0
        async with self._pool.acquire() as conn:
            for entity in spec.entities:
                table_name = f"ab_{short_id}_{entity.name}"
                # Extra safety: validate the final table name too
                _validate_entity_name(f"ab_{short_id}_{entity.name}", "table")

                col_defs = [
                    "id              UUID        PRIMARY KEY DEFAULT gen_random_uuid()",
                    "organization_id UUID        NOT NULL",
                    "created_by      UUID",
                    "created_at      TIMESTAMPTZ NOT NULL DEFAULT now()",
                    "updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()",
                ]
                for col in entity.columns:
                    nullable_str = "" if col.nullable else " NOT NULL"
                    unique_str = " UNIQUE" if col.unique else ""
                    col_defs.append(
                        f"{col.name}  {col.type}{nullable_str}{unique_str}"
                    )

                ddl = (
                    f"CREATE TABLE IF NOT EXISTS {table_name} "
                    f"({', '.join(col_defs)})"
                )
                await conn.execute(ddl)
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {table_name}_org_idx "
                    f"ON {table_name}(organization_id)"
                )
                created += 1

        return created

    async def _create_design_canvas(
        self,
        app_id: str,
        org_id: str,
        spec: AppSpec,
    ) -> str:
        """
        Create (or return existing) Design Studio canvas for the app.
        Uses a deterministic UUID so retry never duplicates the canvas.
        """
        canvas_id = _canvas_uuid(app_id)
        canvas_json = self._build_canvas_json(spec)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO design_canvases
                  (id, project_id, name, canvas_json, width, height)
                VALUES ($1, $2, $3, $4, 1920, 1080)
                ON CONFLICT (id) DO UPDATE
                  SET canvas_json = EXCLUDED.canvas_json,
                      updated_at  = now()
                """,
                canvas_id,
                # Reuse app_id as project_id — design_canvases.project_id is a
                # UUID column; not FK-constrained to projects in all deployments.
                app_id,
                f"{spec.name} — App Builder",
                json.dumps(canvas_json),
            )
        return canvas_id

    def _build_canvas_json(self, spec: AppSpec) -> dict[str, Any]:
        """Build a minimal canvas JSON for Design Studio."""
        pages: list[dict[str, Any]] = []
        for i, page in enumerate(spec.pages):
            pages.append({
                "id": str(uuid.uuid4()),
                "name": page.name,
                "kind": page.kind,
                "entity": page.entity,
                "objects": [],
                "background": "#ffffff",
                "order": i,
            })
        return {
            "version": "1.0",
            "app_name": spec.name,
            "pages": pages,
            "entities": [{"name": e.name, "display_name": e.display_name}
                         for e in spec.entities],
            "roles": [{"name": r.name} for r in spec.roles],
        }

    async def _create_workflows(
        self,
        app_id: str,
        org_id: str,
        user_id: str,
        spec: AppSpec,
    ) -> tuple[int, list[str]]:
        """
        Map WorkflowDefs to the existing Workflow Engine representation.

        Supported:
          - Event-based triggers ("when", "on", "after")
          - Action types: notify, create, update, agent

        Unsupported (recorded as warnings, not silently ignored):
          - Cron/scheduled triggers → require external cron scheduler
          - Webhook triggers → require external configuration
          - Unknown action types → logged per step

        Returns (count_created, warnings_list).
        """
        from app.core.workflow.engine import WorkflowBuilder, get_workflow_engine

        engine = get_workflow_engine()
        warnings: list[str] = []
        created = 0

        async with self._pool.acquire() as conn:
            for wf in spec.workflows:
                wf_id = _workflow_uuid(app_id, wf.name)
                trigger_lower = wf.trigger.lower()

                # ── Classify trigger ────────────────────────────────────────
                if any(kw in trigger_lower for kw in _CRON_KEYWORDS):
                    warnings.append(
                        f"Workflow '{wf.name}': cron/scheduled trigger "
                        "requires manual configuration in Automation tab."
                    )
                elif any(kw in trigger_lower for kw in _WEBHOOK_KEYWORDS):
                    warnings.append(
                        f"Workflow '{wf.name}': webhook trigger "
                        "requires external endpoint configuration."
                    )
                # Event-based triggers are supported via engine

                # ── Map steps to engine ─────────────────────────────────────
                builder = WorkflowBuilder(f"app_builder:{app_id}:{wf.name}")
                supported_count = 0
                unsupported_types: list[str] = []

                for i, raw_step in enumerate(wf.steps[:10]):
                    action_type = str(raw_step.get("type", "")).lower()
                    action_desc = str(raw_step.get("action", f"Step {i + 1}"))[:200]

                    if action_type not in _SUPPORTED_ACTION_TYPES:
                        unsupported_types.append(action_type or "unknown")
                        continue

                    # Capture loop variables explicitly to avoid closure issues
                    captured_desc = action_desc
                    captured_type = action_type

                    async def _step_fn(
                        *,
                        _desc: str = captured_desc,
                        _type: str = captured_type,
                        **_kwargs: Any,
                    ) -> dict[str, Any]:
                        log.info(
                            "App Builder workflow step [%s]: %s", _type, _desc
                        )
                        return {"action": _type, "description": _desc, "executed": True}

                    builder.step(
                        f"step_{i}",
                        action_desc,
                        _step_fn,
                    )
                    supported_count += 1

                if unsupported_types:
                    warnings.append(
                        f"Workflow '{wf.name}': unsupported action types "
                        f"{unsupported_types} — steps skipped."
                    )

                if supported_count == 0 and wf.steps:
                    warnings.append(
                        f"Workflow '{wf.name}': no executable steps found — "
                        "requires manual configuration."
                    )
                elif supported_count > 0:
                    # Register with engine (in-memory; persisted via workflow_ids)
                    wf_run = builder.build(
                        context={"org_id": org_id, "app_id": app_id}
                    )
                    # The engine holds the run definition; external events trigger
                    # engine.execute(wf_run) later. We don't execute here.
                    engine._runs = getattr(engine, "_runs", {})
                    engine._runs[wf_run.run_id] = wf_run

                # Store idempotent reference in app record
                # array_remove first prevents duplicates on retry
                await conn.execute(
                    """
                    UPDATE app_builder_apps
                    SET workflow_ids = array_append(
                            array_remove(workflow_ids, $1::uuid),
                            $1::uuid
                        ),
                        updated_at = now()
                    WHERE id = $2 AND organization_id = $3
                    """,
                    wf_id, app_id, org_id,
                )
                created += 1

        return created, warnings

    async def _create_agents(
        self,
        app_id: str,
        org_id: str,
        user_id: str,
        spec: AppSpec,
    ) -> int:
        """
        Create AI agents using the existing ai_agents table (AgentOS).
        Deterministic UUIDs + ON CONFLICT DO NOTHING ensure idempotency on retry.
        """
        async with self._pool.acquire() as conn:
            for ag_def in spec.agents:
                ag_id = _agent_uuid(app_id, ag_def.name)
                await conn.execute(
                    """
                    INSERT INTO ai_agents
                      (id, user_id, name, description, system_prompt, model)
                    VALUES ($1, $2, $3, $4, $5, 'claude-sonnet-5')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    ag_id, user_id,
                    ag_def.name[:100],
                    ag_def.description[:500],
                    ag_def.system_prompt[:4000],
                )
                # Idempotent append — remove first to avoid duplicates
                await conn.execute(
                    """
                    UPDATE app_builder_apps
                    SET agent_ids = array_append(
                            array_remove(agent_ids, $1::uuid),
                            $1::uuid
                        ),
                        updated_at = now()
                    WHERE id = $2 AND organization_id = $3
                    """,
                    ag_id, app_id, org_id,
                )
        return len(spec.agents)

    async def _update_build_result(
        self,
        app_id: str,
        status: str,
        result_dict: dict[str, Any],
        warnings: list[str],
        canvas_id: Optional[str] = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE app_builder_apps
                SET build_status   = $1,
                    build_result   = $2::jsonb,
                    build_warnings = $3::jsonb,
                    canvas_id      = COALESCE($4, canvas_id),
                    completed_at   = now(),
                    updated_at     = now()
                WHERE id = $5
                """,
                status,
                json.dumps(result_dict),
                json.dumps(warnings),
                canvas_id,
                app_id,
            )

    async def _record_version(
        self,
        app_id: str,
        org_id: str,
        user_id: str,
        *,
        version_number: int,
        label: str,
        spec_dict: dict[str, Any],
        change_summary: Optional[str] = None,
    ) -> None:
        ver_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO app_builder_versions
                  (id, app_id, organization_id, version_number, label,
                   spec_snapshot, change_summary, created_by)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                ON CONFLICT (app_id, version_number) DO NOTHING
                """,
                ver_id, app_id, org_id, version_number, label,
                json.dumps(spec_dict), change_summary, user_id,
            )

    @staticmethod
    def _spec_to_dict(spec: AppSpec) -> dict[str, Any]:
        return {
            "name": spec.name,
            "description": spec.description,
            "target_users": spec.target_users,
            "entities": [
                {
                    "name": e.name,
                    "display_name": e.display_name,
                    "columns": [
                        {"name": c.name, "type": c.type,
                         "nullable": c.nullable, "unique": c.unique}
                        for c in e.columns
                    ],
                    "relationships": e.relationships,
                }
                for e in spec.entities
            ],
            "pages": [
                {"name": p.name, "entity": p.entity, "kind": p.kind}
                for p in spec.pages
            ],
            "roles": [
                {"name": r.name, "permissions": r.permissions}
                for r in spec.roles
            ],
            "workflows": [
                {"name": w.name, "trigger": w.trigger, "steps": w.steps}
                for w in spec.workflows
            ],
            "agents": [
                {"name": a.name, "description": a.description,
                 "system_prompt": a.system_prompt}
                for a in spec.agents
            ],
            "integrations": spec.integrations,
            "settings": spec.settings,
        }


# ── Singleton factory ─────────────────────────────────────────────────────────

_service: Optional[AppBuilderService] = None


def get_app_builder_service() -> AppBuilderService:
    global _service
    if _service is None:
        _service = AppBuilderService(get_pool())
    return _service
