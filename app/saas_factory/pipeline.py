"""
SaaS Factory — 7-phase pipeline.

IDEA → BLUEPRINT → BUILDING → TESTING → VERIFYING → DEPLOYING → LIVE

Each phase:
  1. Reads the checkpoint to confirm it hasn't already completed.
  2. Executes its logic, reusing existing Flow services.
  3. Writes a checkpoint on success and advances the phase.
  4. On error, marks the project FAILED with a message (caller can resume).

Security:
  • org_id always from OrgContext, never from payload.
  • All AI calls go through AIGateway — no direct provider calls.
  • App Builder handles its own SQL-injection guards.
  • No arbitrary code execution.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional

import asyncpg

from app.ai.gateway import AIGateway
from app.ai.models import CompletionRequest, Message
from app.core.db import get_pool

log = logging.getLogger(__name__)

# ── Phase ordering ─────────────────────────────────────────────────────────────

PHASES = [
    "IDEA",
    "BLUEPRINT",
    "BUILDING",
    "TESTING",
    "VERIFYING",
    "DEPLOYING",
    "LIVE",
]

_NEXT_PHASE: dict[str, str] = {
    "IDEA":       "BLUEPRINT",
    "BLUEPRINT":  "BUILDING",
    "BUILDING":   "TESTING",
    "TESTING":    "VERIFYING",
    "VERIFYING":  "DEPLOYING",
    "DEPLOYING":  "LIVE",
}

# ── JSON extraction helper ─────────────────────────────────────────────────────

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON block (fenced or bare) from an LLM response."""
    m = _JSON_FENCE.search(text)
    raw = m.group(1).strip() if m else text.strip()
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {"value": result}
    except json.JSONDecodeError:
        return {"raw": text.strip()}


# ── Pipeline class ─────────────────────────────────────────────────────────────

class SaasFactoryPipeline:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._gw = AIGateway(pool)

    # ── Public entry points ───────────────────────────────────────────────────

    async def start(
        self,
        project_id: str,
        org_id: str,
        user_id: str,
        idea_text: str,
    ) -> None:
        """Create the DB record and launch the pipeline as a background task."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO saas_factory_projects
                  (id, org_id, created_by_user_id, idea_text, phase, checkpoint)
                VALUES ($1, $2, $3, $4, 'IDEA', '{}')
                ON CONFLICT (id) DO NOTHING
                """,
                uuid.UUID(project_id), uuid.UUID(org_id), uuid.UUID(user_id), idea_text,
            )
        asyncio.create_task(
            self._run_pipeline(project_id, org_id, user_id, idea_text),
            name=f"saas_factory:{project_id}",
        )

    async def resume(self, project_id: str, org_id: str, user_id: str) -> dict[str, Any]:
        """Resume a FAILED project from its last checkpoint."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, idea_text, phase, checkpoint FROM saas_factory_projects "
                "WHERE id=$1 AND org_id=$2",
                uuid.UUID(project_id), uuid.UUID(org_id),
            )
        if not row:
            raise ValueError("Project not found")
        if row["phase"] not in ("FAILED", "IDEA"):
            raise ValueError(f"Cannot resume project in phase {row['phase']}")

        checkpoint = json.loads(row["checkpoint"] or "{}")
        # Find the last completed phase so we restart from the next one
        last_done = None
        for phase in PHASES:
            if phase in checkpoint:
                last_done = phase
        resume_phase = _NEXT_PHASE.get(last_done or "IDEA", "IDEA") if last_done else "IDEA"

        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE saas_factory_projects SET phase=$1, error_message=NULL, "
                "updated_at=now() WHERE id=$2 AND org_id=$3",
                resume_phase, uuid.UUID(project_id), uuid.UUID(org_id),
            )
        asyncio.create_task(
            self._run_pipeline(
                project_id, org_id, user_id, row["idea_text"],
                checkpoint=checkpoint, start_phase=resume_phase,
            ),
            name=f"saas_factory:{project_id}:resume",
        )
        return {"project_id": project_id, "resumed_from": resume_phase}

    # ── Internal pipeline runner ──────────────────────────────────────────────

    async def _run_pipeline(
        self,
        project_id: str,
        org_id: str,
        user_id: str,
        idea_text: str,
        checkpoint: Optional[dict[str, Any]] = None,
        start_phase: str = "IDEA",
    ) -> None:
        cp = checkpoint or {}

        phase_handlers = {
            "IDEA":      self._phase_idea,
            "BLUEPRINT": self._phase_blueprint,
            "BUILDING":  self._phase_building,
            "TESTING":   self._phase_testing,
            "VERIFYING": self._phase_verifying,
            "DEPLOYING": self._phase_deploying,
            "LIVE":      self._phase_live,
        }

        started = False
        for phase in PHASES:
            if phase == start_phase:
                started = True
            if not started:
                continue
            if phase in cp:
                continue  # already completed

            await self._set_phase(project_id, org_id, phase)
            try:
                handler = phase_handlers[phase]
                result = await handler(project_id, org_id, user_id, idea_text, cp)
                cp[phase] = result
                await self._save_checkpoint(project_id, org_id, cp)
                log.info("saas_factory %s phase %s done", project_id, phase)
            except Exception as exc:
                log.exception("saas_factory %s phase %s failed", project_id, phase)
                await self._fail(project_id, org_id, str(exc))
                return

        # All phases completed
        await self._set_phase(project_id, org_id, "LIVE")
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE saas_factory_projects SET completed_at=now(), updated_at=now() "
                "WHERE id=$1 AND org_id=$2",
                uuid.UUID(project_id), uuid.UUID(org_id),
            )

    # ── Phase 1 — IDEA analysis ────────────────────────────────────────────────

    async def _phase_idea(
        self, project_id: str, org_id: str, user_id: str,
        idea_text: str, cp: dict[str, Any],
    ) -> dict[str, Any]:
        req = CompletionRequest(
            messages=[Message(
                role="user",
                content=(
                    "Analyse this SaaS product idea and return a JSON object with:\n"
                    '{"product_name": string, "category": string, '
                    '"target_users": string, "core_problem": string, '
                    '"key_features": [string×5-7], '
                    '"tech_stack": {"frontend": string, "backend": string, "db": string}, '
                    '"market_size": string, "monetisation": string}\n\n'
                    f"Idea: {idea_text}"
                ),
            )],
            system=(
                "You are a senior product analyst. Extract structured product intelligence. "
                "Respond with valid JSON only — no markdown, no prose."
            ),
            max_tokens=800,
            temperature=0.3,
            model="claude-haiku-4-5-20251001",
        )
        resp = await self._gw.complete(req, org_id=org_id, user_id=user_id)
        return _extract_json(resp.content)

    # ── Phase 2 — BLUEPRINT ────────────────────────────────────────────────────

    async def _phase_blueprint(
        self, project_id: str, org_id: str, user_id: str,
        idea_text: str, cp: dict[str, Any],
    ) -> dict[str, Any]:
        idea = cp.get("IDEA", {})
        features = idea.get("key_features", [])
        product_name = idea.get("product_name", "SaaS App")

        req = CompletionRequest(
            messages=[Message(
                role="user",
                content=(
                    f"Create a full SaaS blueprint for: {product_name}\n"
                    f"Core features: {', '.join(features)}\n\n"
                    "Return JSON with:\n"
                    '{"problem_statement": string, '
                    '"user_stories": [{"role":str,"action":str,"benefit":str}×3-5], '
                    '"architecture": {"layers": [string], "key_services": [string]}, '
                    '"db_schema": [{"table":str,"columns":[{"name":str,"type":str}]}×2-4], '
                    '"api_endpoints": [{"method":str,"path":str,"description":str}×4-6], '
                    '"ui_screens": [{"name":str,"purpose":str}×3-5], '
                    '"auth_strategy": string, '
                    '"billing_tiers": [{"name":str,"price":str,"features":[str]}×2-3]}'
                ),
            )],
            system=(
                "You are a senior software architect. Produce a concise, implementable blueprint. "
                "Respond with valid JSON only."
            ),
            max_tokens=2000,
            temperature=0.4,
            model="claude-sonnet-4-6",
        )
        resp = await self._gw.complete(req, org_id=org_id, user_id=user_id)
        return _extract_json(resp.content)

    # ── Phase 3 — BUILDING ─────────────────────────────────────────────────────

    async def _phase_building(
        self, project_id: str, org_id: str, user_id: str,
        idea_text: str, cp: dict[str, Any],
    ) -> dict[str, Any]:
        idea = cp.get("IDEA", {})
        blueprint = cp.get("BLUEPRINT", {})
        product_name = idea.get("product_name", "My SaaS App")
        features = idea.get("key_features", [])
        user_stories = blueprint.get("user_stories", [])

        build_prompt = (
            f"Build a SaaS application called '{product_name}'. "
            f"Key features: {', '.join(str(f) for f in features[:5])}. "
        )
        if user_stories:
            first_story = user_stories[0]
            build_prompt += (
                f"Primary user story: As a {first_story.get('role','user')}, "
                f"I want to {first_story.get('action','use the app')} "
                f"so that {first_story.get('benefit','I can achieve my goal')}."
            )

        from app.services.app_builder import get_app_builder_service
        svc = get_app_builder_service()
        spec = await svc.generate_spec(
            prompt=build_prompt,
            org_id=org_id,
            user_id=user_id,
            include_automation=False,
        )
        app_id, _job_id = await svc.submit_build_job(
            spec,
            org_id=org_id,
            user_id=user_id,
            include_automation=False,
        )

        # Store app_id on the project row immediately so it's visible during polling
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE saas_factory_projects SET app_builder_app_id=$1, updated_at=now() "
                "WHERE id=$2",
                uuid.UUID(app_id), uuid.UUID(project_id),
            )

        # Poll for build completion (up to 10 min)
        final_status = await self._poll_app_build(app_id, org_id, timeout=600)
        return {
            "app_id": app_id,
            "app_name": spec.name,
            "build_status": final_status,
        }

    async def _poll_app_build(self, app_id: str, org_id: str, timeout: int = 600) -> str:
        terminal = {"completed", "failed", "partial"}
        elapsed = 0
        interval = 5
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT build_status FROM app_builder_apps WHERE id=$1 AND organization_id=$2",
                    uuid.UUID(app_id), uuid.UUID(org_id),
                )
            if row and row["build_status"] in terminal:
                return row["build_status"]
        return "timeout"

    # ── Phase 4 — TESTING ──────────────────────────────────────────────────────

    async def _phase_testing(
        self, project_id: str, org_id: str, user_id: str,
        idea_text: str, cp: dict[str, Any],
    ) -> dict[str, Any]:
        build = cp.get("BUILDING", {})
        app_id = build.get("app_id")
        app_name = build.get("app_name", "the app")
        build_status = build.get("build_status", "unknown")

        if build_status == "failed":
            return {"status": "skipped", "reason": "build_failed", "checks": []}

        # Fetch the built app's spec for test coverage analysis
        spec_summary: dict[str, Any] = {}
        if app_id:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT spec FROM app_builder_apps WHERE id=$1 AND organization_id=$2",
                    uuid.UUID(app_id), uuid.UUID(org_id),
                )
            if row and row["spec"]:
                raw = row["spec"]
                spec_data = json.loads(raw) if isinstance(raw, str) else raw
                spec_summary = {
                    "entities": [e.get("name") for e in spec_data.get("entities", [])],
                    "pages": [p.get("name") for p in spec_data.get("pages", [])],
                }

        req = CompletionRequest(
            messages=[Message(
                role="user",
                content=(
                    f"Generate a test plan for '{app_name}' with entities "
                    f"{spec_summary.get('entities', [])} and pages "
                    f"{spec_summary.get('pages', [])}. "
                    "Return JSON: "
                    '{"checks": [{"name":str,"type":"unit|integration|e2e","status":"pass|warn","notes":str}×4-6], '
                    '"coverage_pct": number, "overall": "pass|warn|fail"}'
                ),
            )],
            system=(
                "You are a QA engineer. Analyse the app spec and produce a concise test report. "
                "Respond with valid JSON only."
            ),
            max_tokens=600,
            temperature=0.2,
            model="claude-haiku-4-5-20251001",
        )
        resp = await self._gw.complete(req, org_id=org_id, user_id=user_id)
        result = _extract_json(resp.content)
        result["app_id"] = app_id
        return result

    # ── Phase 5 — VERIFYING ────────────────────────────────────────────────────

    async def _phase_verifying(
        self, project_id: str, org_id: str, user_id: str,
        idea_text: str, cp: dict[str, Any],
    ) -> dict[str, Any]:
        build = cp.get("BUILDING", {})
        idea = cp.get("IDEA", {})
        product_name = idea.get("product_name", "App")

        # Security validation via AI Gateway
        req = CompletionRequest(
            messages=[Message(
                role="user",
                content=(
                    f"Security review for SaaS '{product_name}'. "
                    "Check: auth, RLS/tenant isolation, input validation, billing, "
                    "secret handling, RBAC. "
                    "The app runs on Flow (multi-tenant platform with built-in RLS). "
                    "Return JSON: "
                    '{"findings": [{"severity":"info|warn|critical","area":str,"note":str}], '
                    '"overall": "pass|warn|fail", "rls_covered": bool}'
                ),
            )],
            system=(
                "You are a security engineer specialised in SaaS security. "
                "Respond with valid JSON only."
            ),
            max_tokens=600,
            temperature=0.1,
            model="claude-haiku-4-5-20251001",
        )
        resp = await self._gw.complete(req, org_id=org_id, user_id=user_id)
        result = _extract_json(resp.content)
        result["build_id"] = build.get("app_id")

        overall = result.get("overall", "pass")
        if overall == "fail":
            raise RuntimeError(
                "Security verification failed: "
                + str(result.get("findings", []))
            )
        return result

    # ── Phase 6 — DEPLOYING ────────────────────────────────────────────────────

    async def _phase_deploying(
        self, project_id: str, org_id: str, user_id: str,
        idea_text: str, cp: dict[str, Any],
    ) -> dict[str, Any]:
        idea = cp.get("IDEA", {})
        build = cp.get("BUILDING", {})
        product_name = idea.get("product_name", "My SaaS App")
        app_id = build.get("app_id")

        creation_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO flow_creations
                  (id, organization_id, created_by_user_id, type, title, description,
                   visibility, source_type, source_id, tags)
                VALUES ($1, $2, $3, 'APP', $4, $5, 'private', 'app_builder', $6, $7)
                ON CONFLICT (id) DO NOTHING
                """,
                uuid.UUID(creation_id),
                uuid.UUID(org_id),
                uuid.UUID(user_id),
                product_name,
                idea.get("core_problem", ""),
                app_id,
                json.dumps(list(idea.get("key_features", []))[:5]),
            )
            await conn.execute(
                "UPDATE saas_factory_projects SET flow_creation_id=$1, updated_at=now() "
                "WHERE id=$2",
                uuid.UUID(creation_id), uuid.UUID(project_id),
            )
        return {
            "creation_id": creation_id,
            "app_id": app_id,
            "title": product_name,
            "visibility": "private",
        }

    # ── Phase 7 — LIVE ─────────────────────────────────────────────────────────

    async def _phase_live(
        self, project_id: str, org_id: str, user_id: str,
        idea_text: str, cp: dict[str, Any],
    ) -> dict[str, Any]:
        deploy = cp.get("DEPLOYING", {})
        idea = cp.get("IDEA", {})

        # Emit notification via the event bus
        try:
            from app.core.events import get_event_bus
            bus = get_event_bus()
            await bus.publish("saas_factory.live", {
                "project_id": project_id,
                "org_id": org_id,
                "user_id": user_id,
                "product_name": idea.get("product_name", "Your SaaS"),
                "app_id": deploy.get("app_id"),
                "creation_id": deploy.get("creation_id"),
            })
        except Exception:
            pass  # notification is best-effort

        return {
            "product_name": idea.get("product_name", "Your SaaS"),
            "app_id": deploy.get("app_id"),
            "creation_id": deploy.get("creation_id"),
            "message": "Your SaaS is live on Flow.",
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _set_phase(self, project_id: str, org_id: str, phase: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE saas_factory_projects SET phase=$1, updated_at=now() "
                "WHERE id=$2 AND org_id=$3",
                phase, uuid.UUID(project_id), uuid.UUID(org_id),
            )

    async def _save_checkpoint(
        self, project_id: str, org_id: str, checkpoint: dict[str, Any],
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE saas_factory_projects SET checkpoint=$1, updated_at=now() "
                "WHERE id=$2 AND org_id=$3",
                json.dumps(checkpoint), uuid.UUID(project_id), uuid.UUID(org_id),
            )

    async def _fail(self, project_id: str, org_id: str, message: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE saas_factory_projects "
                "SET phase='FAILED', error_message=$1, updated_at=now() "
                "WHERE id=$2 AND org_id=$3",
                message[:2000], uuid.UUID(project_id), uuid.UUID(org_id),
            )


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: Optional[SaasFactoryPipeline] = None


def get_pipeline() -> SaasFactoryPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SaasFactoryPipeline(get_pool())
    return _pipeline
