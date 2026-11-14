"""Lead AI assistance: follow-up drafts and the pipeline brief. No live model or DB."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.leads.ai import (
    LeadAIError,
    followup_draft,
    pipeline_brief,
    pipeline_stats,
)

LEAD = {
    "id": "11111111-1111-1111-1111-111111111111", "name": "Sara — Bright Dental",
    "email": "sara@example.com", "phone": "+971500000000", "source": "website",
    "status": "qualified", "ai_tier": "hot", "ai_score": 9,
    "ai_notes": "Agency of 8 asking about automated follow-ups.",
    "created_at": "2026-10-20T10:00:00+00:00",
}


def answer(payload):
    return AsyncMock(return_value=payload if isinstance(payload, str) else json.dumps(payload))


def run(coro):
    return asyncio.run(coro)


# ── Follow-up draft ───────────────────────────────────────────────────────────

def test_followup_uses_only_lead_facts_and_is_never_sent():
    complete = answer({"subject": "Following up\non your enquiry",
                       "body": "Hi Sara, thanks for asking about automated follow-ups. [Your name]"})
    draft = run(followup_draft(complete, LEAD, "ar"))
    assert draft == {"subject": "Following up on your enquiry",
                     "body": "Hi Sara, thanks for asking about automated follow-ups. [Your name]",
                     "sent": False}
    system, prompt, _ = complete.call_args.args
    assert "never invent" in system and "untrusted" in system
    assert "Arabic" in prompt and '<data name="lead">' in prompt
    # Contact details are not needed to write the email and are not sent to the model.
    assert "sara@example.com" not in prompt and "+971500000000" not in prompt


@pytest.mark.parametrize("payload", [
    "no json here",
    {"subject": "Hi"},
    {"subject": "Hello there", "body": "Too short."},
    {"subject": ["x"], "body": "x" * 50},
])
def test_followup_rejects_unusable_answers(payload):
    with pytest.raises(LeadAIError):
        run(followup_draft(answer(payload), LEAD))


# ── Pipeline brief ────────────────────────────────────────────────────────────

COUNTS = [
    {"ai_tier": "hot", "status": "qualified", "n": 2},
    {"ai_tier": "warm", "status": "contacted", "n": 3},
    {"ai_tier": None, "status": "new", "n": 4},
    {"ai_tier": "cold", "status": "lost", "n": 1},
    {"ai_tier": "hot", "status": "won", "n": 1},
]


def test_stats_are_counted_exactly():
    stats = pipeline_stats(COUNTS)
    assert stats["total"] == 11 and stats["open"] == 9
    assert stats["tiers"] == {"hot": 3, "warm": 3, "cold": 1, "unscored": 4}
    assert stats["statuses"] == {"new": 4, "qualified": 2, "contacted": 3, "won": 1, "lost": 1}


def test_brief_actions_must_point_at_leads_that_were_given():
    other = {**LEAD, "id": "22222222-2222-2222-2222-222222222222", "name": "Omar", "ai_tier": "warm"}
    complete = answer({
        "summary": "Two strong leads; call Sara today.",
        "actions": [
            {"n": 1, "action": "Call Sara today"},
            {"n": 1, "action": "Duplicate"},
            {"n": 7, "action": "Invented lead"},
            {"n": True, "action": "Bool is not an index"},
            {"n": 2, "action": "  Send   Omar the case study "},
            {"n": 2},
        ],
    })
    brief = run(pipeline_brief(complete, pipeline_stats(COUNTS), [LEAD, other], "en",
                               now=datetime(2026, 10, 28, tzinfo=timezone.utc)))
    assert brief["summary"] == "Two strong leads; call Sara today."
    assert brief["actions"] == [
        {"lead_id": LEAD["id"], "name": LEAD["name"], "action": "Call Sara today"},
        {"lead_id": other["id"], "name": "Omar", "action": "Send Omar the case study"},
    ]
    assert brief["stats"]["total"] == 11
    _, prompt, _ = complete.call_args.args
    assert '"age_days": 7' in prompt and "sara@example.com" not in prompt


def test_empty_pipeline_needs_no_ai_call():
    complete = AsyncMock()
    brief = run(pipeline_brief(complete, pipeline_stats([]), []))
    assert brief == {"stats": pipeline_stats([]), "summary": None, "actions": []}
    complete.assert_not_awaited()


@pytest.mark.parametrize("payload", [{"actions": []}, {"summary": "ok", "actions": "none"}, "nope"])
def test_brief_rejects_unusable_answers(payload):
    with pytest.raises(LeadAIError):
        run(pipeline_brief(answer(payload), pipeline_stats(COUNTS), [LEAD]))


# ── Service wiring ────────────────────────────────────────────────────────────

class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


ORG = "33333333-3333-3333-3333-333333333333"


def test_brief_queries_only_this_orgs_open_leads(monkeypatch):
    from app.core.leads.service import LeadService

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[COUNTS, []])
    svc = LeadService(_Pool(conn))
    monkeypatch.setattr(svc, "ai_complete", lambda **kw: AsyncMock())
    brief = run(svc.pipeline_brief(org_id=ORG, user_id=None))
    assert brief["summary"] is None and brief["stats"]["total"] == 11
    (count_sql, *count_args), (open_sql, *open_args) = [c.args for c in conn.fetch.call_args_list]
    assert "WHERE organization_id = $1" in count_sql and str(count_args[0]) == ORG
    assert "organization_id = $1 AND status = ANY($2::text[])" in open_sql
    assert str(open_args[0]) == ORG and open_args[1] == ["new", "qualified", "contacted"]


def test_followup_for_missing_lead_returns_none_without_ai(monkeypatch):
    from app.core.leads.service import LeadService

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    svc = LeadService(_Pool(conn))
    complete = AsyncMock()
    monkeypatch.setattr(svc, "ai_complete", lambda **kw: complete)
    assert run(svc.ai_followup(lead_id=LEAD["id"], org_id=ORG)) is None
    complete.assert_not_awaited()
    sql, *args = conn.fetchrow.call_args.args
    assert "organization_id = $2" in sql and str(args[1]) == ORG


def test_gateway_errors_become_safe_messages(monkeypatch):
    from app.ai import gateway
    from app.core.leads.service import LeadService

    class Broken:
        def __init__(self, pool):
            pass

        async def complete(self, *a, **k):
            raise RuntimeError("provider key sk-secret rejected")

    monkeypatch.setattr(gateway, "AIGateway", Broken, raising=False)
    complete = LeadService(_Pool(AsyncMock())).ai_complete(org_id=ORG, user_id=None)
    with pytest.raises(LeadAIError) as err:
        run(complete("system", "prompt", 10))
    assert "sk-secret" not in str(err.value)


def test_routes_are_registered_with_write_permission():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app" / "routers" / "leads.py").read_text()
    for route in ('@router.post("/brief")', '@router.post("/{lead_id}/ai-followup")'):
        block = src[src.index(route):src.index(route) + 400]
        assert 'require_permission("leads", "write")' in block
        assert "except LeadAIError" in src[src.index(route):src.index(route) + 900]
