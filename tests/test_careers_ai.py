"""Career assistant AI: grounding, validation and wiring. No live model or DB."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.careers import ai
from app.core.careers.ai import CareerAIError
from app.core.careers.models import CareerProfile, ImportAlert
from app.core.careers.service import CareerService
from app.tenancy.context import OrgContext

CTX = OrgContext(
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222",
    "",
    "member",
)
CV = """Ahmed Example — Dubai
Sales Executive, Example Foods (2020–2024). FMCG distribution.
Skills: Zoho Books, key account management, Excel.
Languages: English, العربية."""

PASTED = """Hi, we are hiring!

Warehouse Supervisor at Gulf Logistics — Jebel Ali
AED 7,000 per month. Forklift licence required.
Closing date: 30 December 2026
https://careers.gulflogistics.example/jobs/77

Accounts Assistant
Example Trading - Dubai
https://ae.indeed.com/rc/clk/dl?jk=8b1f472f65632b95&otpToken=PRIVATE
"""
# No LinkedIn/Indeed links: the rules parser finds nothing here.
PLAIN = PASTED.split("Accounts Assistant")[0]


def answer(payload):
    complete = AsyncMock(return_value=payload if isinstance(payload, str) else json.dumps(payload))
    return complete


# ── Profile from CV ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_profile_keeps_only_terms_found_in_the_cv():
    complete = answer({
        "summary": "Sales executive with four years in FMCG distribution.",
        "roles": ["Sales Executive", "Chief Executive Officer"],
        "skills": ["Zoho Books", "Excel", "excel", "Python"],
        "sectors": ["FMCG"],
        "languages": ["English", "Arabic", "French"],
        "cities": ["Dubai", "Abu Dhabi"],
        "experience_years": 4,
    })
    profile = await ai.extract_profile(complete, CV)
    assert profile.roles == ["Sales Executive"]          # invented title dropped
    assert profile.skills == ["Zoho Books", "Excel"]     # invented + duplicate dropped
    assert profile.languages == ["English", "Arabic"]    # Arabic written as العربية
    assert profile.cities == ["Dubai"]
    assert profile.experience_years == 4
    system, prompt, _ = complete.call_args.args
    assert "untrusted" in system and '<data name="cv">' in prompt and CV in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    "Sorry, I cannot help with that.",
    {"roles": "Sales Executive"},
    {"summary": 42},
    "[1, 2]",
])
async def test_profile_rejects_malformed_answers(payload):
    with pytest.raises(CareerAIError):
        await ai.extract_profile(answer(payload), CV)


@pytest.mark.asyncio
async def test_profile_ignores_impossible_experience():
    profile = await ai.extract_profile(answer({"experience_years": 99}), CV)
    assert profile.experience_years is None


# ── Jobs from any pasted text ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jobs_are_grounded_in_the_pasted_text():
    complete = answer({"jobs": [
        {"title": "Warehouse Supervisor", "company": "Gulf Logistics", "location": "Jebel Ali",
         "url": "https://careers.gulflogistics.example/jobs/77"},
        {"title": "Accounts Assistant", "company": "Example Trading", "location": "Dubai",
         "url": "https://ae.indeed.com/rc/clk/dl?jk=8b1f472f65632b95&otpToken=PRIVATE"},
        {"title": "Head of Strategy", "company": "Invented Co", "location": "Dubai", "url": ""},
    ]})
    jobs = await ai.extract_jobs(complete, PASTED)
    assert [j["title"] for j in jobs] == ["Warehouse Supervisor", "Accounts Assistant"]
    warehouse, accounts = jobs
    # Description, salary and deadline come from the source text, not the model.
    assert "Forklift licence required" in warehouse["description"]
    assert "Accounts Assistant" not in warehouse["description"]
    assert warehouse["salary"]["min"] == 7000 and warehouse["salary"]["period"] == "monthly"
    assert warehouse["deadline"] == "2026-12-30"
    assert warehouse["source"] == "other" and warehouse["verification"] == "pasted_text"
    assert warehouse["extracted_by"] == "ai"
    # Allowlisted links are canonicalised and lose private tokens.
    assert accounts["url"] == "https://ae.indeed.com/viewjob?jk=8b1f472f65632b95"
    assert accounts["source"] == "indeed"
    assert len({j["key"] for j in jobs}) == 2


@pytest.mark.asyncio
async def test_job_links_and_details_not_in_text_are_dropped():
    jobs = await ai.extract_jobs(answer({"jobs": [
        {"title": "Warehouse Supervisor", "company": "Made Up LLC", "location": "Jebel Ali",
         "url": "https://evil.example/phish"},
    ]}), PASTED)
    assert jobs[0]["url"] == "" and jobs[0]["company"] == ""
    assert jobs[0]["location"] == "Jebel Ali"


@pytest.mark.asyncio
async def test_non_https_links_are_dropped():
    text = "Driver needed\nhttp://jobs.example/1"
    jobs = await ai.extract_jobs(answer({"jobs": [{"title": "Driver", "url": "http://jobs.example/1"}]}), text)
    assert jobs[0]["url"] == ""


@pytest.mark.asyncio
async def test_jobs_answer_must_be_a_list():
    with pytest.raises(CareerAIError):
        await ai.extract_jobs(answer({"jobs": "none"}), PASTED)


# ── Draft and fit ─────────────────────────────────────────────────────────────

JOB = {"title": "Sales Executive", "company": "Example Foods", "location": "Dubai",
       "description": "FMCG sales. Zoho Books required."}
PROFILE = CareerProfile(summary="Four years in FMCG sales.", roles=["Sales Executive"],
                        skills=["Zoho Books"], minimum_monthly_aed=9000)


@pytest.mark.asyncio
async def test_draft_uses_profile_and_listing_as_data_and_hides_salary_target():
    text = "Subject: Application — Sales Executive\n\nDear Hiring Team, ...\n[Your name]"
    complete = answer("```\n" + text + "\n```")
    assert await ai.draft(complete, JOB, PROFILE) == text
    system, prompt, _ = complete.call_args.args
    assert "never invent" in system
    assert '<data name="candidate_profile">' in prompt and '<data name="job">' in prompt
    assert "9000" not in prompt and "minimum_monthly_aed" not in prompt


@pytest.mark.asyncio
async def test_too_short_draft_is_rejected():
    with pytest.raises(CareerAIError):
        await ai.draft(answer("OK"), JOB, PROFILE)


@pytest.mark.asyncio
async def test_fit_is_validated_and_tied_to_the_profile():
    result = await ai.fit(answer({
        "summary": "Strong sales match; confirm the Zoho level.",
        "strengths": ["FMCG sales", "Zoho Books"], "gaps": [], "questions": ["Team size?"],
    }), JOB, PROFILE, "ar")
    assert result["summary"].startswith("Strong") and result["strengths"] == ["FMCG sales", "Zoho Books"]
    assert result["profile_hash"] == ai.profile_hash(PROFILE) and result["language"] == "ar"
    with pytest.raises(CareerAIError):
        await ai.fit(answer({"summary": "x", "gaps": [1, 2]}), JOB, PROFILE)
    with pytest.raises(CareerAIError):
        await ai.fit(answer({"strengths": []}), JOB, PROFILE)


# ── Gateway binding ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gateway_call_is_metered_to_the_caller_and_errors_are_generic(monkeypatch):
    from app.ai import gateway

    calls = []

    class FakeGateway:
        def __init__(self, pool):
            pass

        async def complete(self, request, *, user_id=None, org_id=None):
            calls.append((request, user_id, org_id))
            return SimpleNamespace(content="ok")

    monkeypatch.setattr(gateway, "AIGateway", FakeGateway)
    complete = ai.gateway_complete(object(), org_id=CTX.org_id, user_id=CTX.user_id)
    assert await complete("system", "prompt", 100) == "ok"
    request, user_id, org_id = calls[0]
    assert (user_id, org_id) == (CTX.user_id, CTX.org_id)
    assert request.system == "system" and request.max_tokens == 100

    class Broken(FakeGateway):
        async def complete(self, *a, **k):
            raise RuntimeError("provider key sk-secret rejected")

    monkeypatch.setattr(gateway, "AIGateway", Broken)
    with pytest.raises(CareerAIError) as err:
        await complete("system", "prompt", 100)
    assert "sk-secret" not in str(err.value)

    from app.billing import QuotaExceeded

    class OverQuota(FakeGateway):
        async def complete(self, *a, **k):
            raise QuotaExceeded("tokens", 10, 10)

    monkeypatch.setattr(gateway, "AIGateway", OverQuota)
    with pytest.raises(QuotaExceeded):
        await complete("system", "prompt", 100)


# ── Service: AI only when the rules parser finds nothing ──────────────────────

class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _Conn:
    def __init__(self):
        self.fetchval = AsyncMock(side_effect=lambda *a: "new-id")
        self.execute = AsyncMock()

    def transaction(self):
        return _Tx()


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                pass

        return _Acquire()


INDEED_ALERT = """Customer Support & Sales
Example Services - Dubai
From AED4,000 a month
https://ae.indeed.com/viewjob?jk=79c60f05d50f2150
"""


@pytest.mark.asyncio
async def test_supported_alerts_never_call_the_ai(monkeypatch):
    svc = CareerService(_Pool(_Conn()))
    complete = AsyncMock()
    monkeypatch.setattr(svc, "ai_complete", lambda ctx: complete)
    result = await svc.import_alert(CTX, ImportAlert(text=INDEED_ALERT, use_ai=True))
    assert result["method"] == "rules" and result["inserted"] == 1
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_text_uses_ai_only_when_asked(monkeypatch):
    conn = _Conn()
    svc = CareerService(_Pool(conn))
    complete = answer({"jobs": [{"title": "Warehouse Supervisor", "url": ""}]})
    monkeypatch.setattr(svc, "ai_complete", lambda ctx: complete)

    plain = await svc.import_alert(CTX, ImportAlert(text=PLAIN))
    assert plain["method"] == "rules" and plain["found"] == 0
    complete.assert_not_awaited()

    result = await svc.import_alert(CTX, ImportAlert(text=PLAIN, use_ai=True))
    assert result["method"] == "ai" and result["inserted"] == 1 and result["warning"] is None
    sql, org_id, user_id, _key, data = conn.fetchval.call_args.args
    assert "organization_id,user_id" in sql
    assert (str(org_id), str(user_id)) == (CTX.org_id, CTX.user_id)
    assert json.loads(data)["extracted_by"] == "ai"


@pytest.mark.asyncio
async def test_fit_is_stored_on_the_owners_job_and_marked_stale_after_profile_change(monkeypatch):
    conn = _Conn()
    stored = {"title": "Sales Executive", "description": "FMCG", "salary": {}}
    conn.fetchval = AsyncMock(side_effect=lambda sql, *a: (
        json.dumps(stored) if "SELECT data" in sql else json.dumps(PROFILE.model_dump()) if "SELECT profile" in sql else None
    ))
    svc = CareerService(_Pool(conn))
    monkeypatch.setattr(svc, "ai_complete", lambda ctx: answer({"summary": "Good match."}))
    result = await svc.ai_fit(CTX, "33333333-3333-3333-3333-333333333333", "en")
    assert result["summary"] == "Good match." and result["stale"] is False
    sql, org_id, user_id, _job_id, data = conn.execute.call_args.args
    assert "organization_id=$1 AND user_id=$2 AND id=$3" in sql and "'ai_fit'" in sql
    assert str(org_id) == CTX.org_id and str(user_id) == CTX.user_id

    other = CareerProfile(summary="Changed")
    rows = [{"id": "33333333-3333-3333-3333-333333333333", "status": "new",
             "created_at": SimpleNamespace(isoformat=lambda: "2026-10-28T00:00:00"),
             "data": json.dumps({**stored, "deadline": None, "ai_fit": json.loads(data)})}]
    conn.fetch = AsyncMock(return_value=rows)
    conn.fetchval = AsyncMock(return_value=json.dumps(other.model_dump()))
    [item] = await svc.jobs(CTX)
    assert item["ai_fit"]["stale"] is True


# ── Routes ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_routes_map_failures_and_missing_jobs(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.routers import careers

    app = FastAPI()
    app.include_router(careers.router)
    app.dependency_overrides[careers.org_context] = lambda: CTX
    fake = AsyncMock()
    fake.extract_profile.side_effect = CareerAIError("AI is unavailable right now.")
    fake.ai_draft.return_value = None
    fake.ai_fit.return_value = None
    fake.job.return_value = {"url": "https://careers.example/jobs/1", "title": "Driver"}
    monkeypatch.setattr(careers, "service", lambda: fake)
    job = "33333333-3333-3333-3333-333333333333"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        extracted = await client.post("/api/careers/profile/extract", json={"text": CV})
        draft = await client.post(f"/api/careers/jobs/{job}/ai-draft")
        fit = await client.post(f"/api/careers/jobs/{job}/fit", json={"language": "ar"})
        verify = await client.post(f"/api/careers/jobs/{job}/verify")
        short = await client.post("/api/careers/profile/extract", json={"text": "too short"})
    assert extracted.status_code == 502 and "unavailable" in extracted.text
    assert draft.status_code == 404 and fit.status_code == 404
    assert fake.ai_fit.call_args.args[2] == "ar"
    assert verify.status_code == 400 and "LinkedIn and Indeed" in verify.text
    assert short.status_code == 422
