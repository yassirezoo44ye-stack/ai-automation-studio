"""
LeadService — CRUD + AI qualification + notification dispatch.

All methods are org-scoped: callers pass a verified org_id from OrgContext,
never from untrusted request data.

AI qualification uses the existing AgentRuntime (app/core/ai/agents/runtime.py)
with a structured prompt.  If the runtime fails (network, quota, etc.) the lead
stays in status='new' and ai_score/ai_notes carry the failure reason — the lead
is NOT lost, qualification failure is surfaced explicitly.

Follow-up automation: if the org has an automation definition tagged
'lead_followup' in its metadata, a manual run is enqueued.  When no definition
exists, the lead record is the sole persistent artifact and the API response
includes follow_up_status='no_definition' so the caller knows delivery was not
triggered.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

VALID_STATUSES = ("new", "qualified", "contacted", "won", "lost")


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for key in ("id", "organization_id"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    for key in ("created_at", "updated_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat()
    return d


class LeadService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── Create ───────────────────────────────────────────────────────────────

    async def create(
        self, *,
        org_id: str,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        source: Optional[str] = None,
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO leads (organization_id, name, email, phone, source)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                uuid.UUID(org_id), name, email, phone, source,
            )
        return _row_to_dict(row)

    # ── List ─────────────────────────────────────────────────────────────────

    async def list(
        self, *,
        org_id: str,
        status: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        params: list[Any] = [uuid.UUID(org_id)]
        where = ["organization_id = $1"]
        if status:
            params.append(status)
            where.append(f"status = ${len(params)}")
        if before:
            params.append(uuid.UUID(before))
            where.append(f"id < ${len(params)}")
        params.append(limit)
        q = (
            f"SELECT * FROM leads WHERE {' AND '.join(where)} "
            f"ORDER BY created_at DESC LIMIT ${len(params)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q, *params)
        return [_row_to_dict(r) for r in rows]

    # ── Get one ──────────────────────────────────────────────────────────────

    async def get(self, *, lead_id: str, org_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM leads WHERE id = $1 AND organization_id = $2",
                uuid.UUID(lead_id), uuid.UUID(org_id),
            )
        return _row_to_dict(row) if row else None

    # ── Update status ─────────────────────────────────────────────────────────

    async def update_status(
        self, *, lead_id: str, org_id: str, status: str,
    ) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE leads
                SET status = $1, updated_at = now()
                WHERE id = $2 AND organization_id = $3
                RETURNING *
                """,
                status, uuid.UUID(lead_id), uuid.UUID(org_id),
            )
        return _row_to_dict(row) if row else None

    # ── AI qualification ──────────────────────────────────────────────────────

    async def qualify(
        self, *, lead_id: str, org_id: str,
    ) -> dict[str, Any]:
        """
        Run AI qualification via AgentRuntime.  Stores ai_score + ai_notes and
        sets status='qualified' on success.  On failure stores the error in
        ai_notes, leaves status='new', returns the updated lead.
        """
        lead = await self.get(lead_id=lead_id, org_id=org_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        prompt = (
            f"You are a sales qualification assistant. Score this lead from 1 to 10 "
            f"based on their potential as a customer for a SaaS automation platform "
            f"targeting small agencies (2-20 employees).\n\n"
            f"Lead information:\n"
            f"  Name: {lead.get('name', '')}\n"
            f"  Email: {lead.get('email') or 'not provided'}\n"
            f"  Phone: {lead.get('phone') or 'not provided'}\n"
            f"  Source: {lead.get('source') or 'not provided'}\n\n"
            f"Respond ONLY with JSON: "
            f'{{\"score\": <integer 1-10>, \"notes\": \"<one sentence rationale>\"}}'
        )

        ai_score: Optional[int] = None
        ai_notes: Optional[str] = None
        new_status = "new"

        try:
            from app.core.ai.agents.runtime import AgentConfig, AgentRuntime
            cfg = AgentConfig(
                name="lead-qualifier",
                system_prompt="You are a concise sales qualification assistant. Reply only with the requested JSON.",
                max_tokens=256,
                temperature=0.3,
            )
            result = await AgentRuntime(cfg).run(prompt)
            if result.success and result.content:
                parsed = _parse_qualification(result.content)
                ai_score = parsed.get("score")
                ai_notes = parsed.get("notes")
                new_status = "qualified"
            else:
                ai_notes = f"AI qualification failed: {result.error or 'no content'}"
        except Exception as exc:
            log.warning("lead qualification error lead_id=%s: %s", lead_id, exc)
            ai_notes = f"AI qualification unavailable: {exc}"

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE leads
                SET ai_score = $1, ai_notes = $2, status = $3, updated_at = now()
                WHERE id = $4 AND organization_id = $5
                RETURNING *
                """,
                ai_score, ai_notes, new_status,
                uuid.UUID(lead_id), uuid.UUID(org_id),
            )
        return _row_to_dict(row) if row else lead

    # ── Notification dispatch ─────────────────────────────────────────────────

    async def dispatch_qualified_notification(
        self, *, lead: dict[str, Any], org_id: str,
    ) -> None:
        score_str = str(lead.get("ai_score")) if lead.get("ai_score") else "N/A"
        lead_name = lead.get("name", "Unknown")

        # ── In-app notifications (always attempted, always silenced on error) ──
        try:
            from app.core.notifications.service import get_notification_service
            svc = get_notification_service()
            member_ids = await svc.org_member_ids(organization_id=org_id)
            for user_id in member_ids:
                await svc.create(
                    user_id=user_id,
                    organization_id=org_id,
                    type_="lead.qualified",
                    category="workflow",
                    severity="success",
                    title=f"Lead qualified: {lead_name}",
                    message=f"Score {score_str}/10 — {lead.get('ai_notes') or 'Ready for follow-up.'}",
                    source="lead_engine",
                    action={"label": "View leads", "href": "/leads"},
                )
        except Exception as exc:
            log.warning("lead in-app notification failed lead_id=%s: %s", lead.get("id"), exc)

        # ── Team email alert (only when SMTP_HOST is configured) ──────────────
        import os
        if not os.getenv("SMTP_HOST"):
            log.debug("lead team email skipped — SMTP_HOST not configured lead_id=%s", lead.get("id"))
            return
        try:
            from app.core.email import send_email
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT u.email FROM users u
                    JOIN organization_members om ON om.user_id = u.id
                    WHERE om.organization_id = $1 AND om.deleted_at IS NULL
                      AND u.email IS NOT NULL
                    """,
                    uuid.UUID(org_id),
                )
            subject = f"New qualified lead: {lead_name} (Score {score_str}/10)"
            html = (
                f"<p><strong>{lead_name}</strong> has been qualified by the AI engine.</p>"
                f"<p><strong>Score:</strong> {score_str}/10</p>"
                f"<p><strong>Notes:</strong> {lead.get('ai_notes') or '—'}</p>"
                f"<p><a href='/leads'>View in Lead Engine →</a></p>"
            )
            for row in rows:
                member_email = row["email"]
                try:
                    await send_email(member_email, subject, html)
                    log.info("lead team email sent to=%s lead_id=%s", member_email, lead.get("id"))
                except Exception as exc:
                    log.warning("lead team email failed to=%s lead_id=%s: %s", member_email, lead.get("id"), exc)
        except Exception as exc:
            log.warning("lead team email dispatch error lead_id=%s: %s", lead.get("id"), exc)


def _parse_qualification(content: str) -> dict[str, Any]:
    match = re.search(r'\{[^{}]+\}', content, re.DOTALL)
    if not match:
        return {"notes": content[:200]}
    try:
        import json
        data = json.loads(match.group())
        score = data.get("score")
        if isinstance(score, (int, float)):
            score = max(1, min(10, int(score)))
        else:
            score = None
        return {"score": score, "notes": str(data.get("notes", ""))[:500]}
    except Exception:
        return {"notes": content[:200]}


_service_instance: Optional[LeadService] = None


def get_lead_service() -> LeadService:
    if _service_instance is None:
        raise RuntimeError("LeadService not initialized — call init_lead_service() at startup")
    return _service_instance


def init_lead_service(pool: asyncpg.Pool) -> LeadService:
    global _service_instance
    _service_instance = LeadService(pool)
    return _service_instance
