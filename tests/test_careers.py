"""Career assistant regression tests: no live mailbox, network, model or production DB."""

import base64
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.core.careers.engine import (
    assess,
    canonical_job_url,
    closing_date,
    draft_application,
    mime_text,
    parse_alert,
    salary_from_text,
)
from app.core.careers.models import CareerProfile
from app.core.careers.service import CareerService
from app.tenancy.context import OrgContext

ALERT = """Indeed Job Alert
See matching results on Indeed: https://ae.indeed.com/jobs?q=accountant

Supply Chain & Accounts Officer
Example Company - Dubai
AED6,000 - AED8,000 a month
Easily apply
Coordinate supplier orders and shipping; practical Zoho Books knowledge required.
8 days ago
https://ae.indeed.com/rc/clk/dl?jk=8b1f472f65632b95&otpToken=PRIVATE

Customer Support & Sales
Example Services - Dubai
From AED4,000 a month
Training provided; prior industry experience not mandatory.
https://ae.indeed.com/viewjob?jk=79c60f05d50f2150
"""


@pytest.mark.parametrize(
    "url",
    [
        "http://ae.indeed.com/viewjob?jk=8b1f472f65632b95",
        "https://ae.indeed.com.evil.test/viewjob?jk=8b1f472f65632b95",
        "https://ae.indeed.com@127.0.0.1/viewjob?jk=8b1f472f65632b95",
        "https://ae.indeed.com:8443/viewjob?jk=8b1f472f65632b95",
        "https://127.0.0.1/",
        "javascript:alert(1)",
        "https://ae.indeed.com/jobs?q=sales",
        "https://www.linkedin.com/jobs/view/invalid/",
    ],
)
def test_unsafe_or_non_job_urls_rejected(url):
    assert canonical_job_url(url) is None


def test_extracts_two_jobs_and_strips_private_tokens():
    jobs = parse_alert(ALERT)
    assert len(jobs) == 2
    assert jobs[0]["title"] == "Supply Chain & Accounts Officer"
    assert jobs[0]["company"] == "Example Company"
    assert jobs[0]["location"] == "Dubai"
    assert jobs[0]["salary"]["min"] == 6000
    assert "PRIVATE" not in str(jobs)
    assert jobs[0]["verification"] == "email_only"
    assert jobs[1]["salary"]["max"] is None


def test_duplicate_urls_do_not_create_duplicate_jobs():
    assert len(parse_alert(ALERT + ALERT)) == 2


def test_linkedin_plain_alert():
    text = "Business Manager\nExample Dairies\nدبي\nعرض الوظيفة: https://www.linkedin.com/comm/jobs/view/4470888126/?midToken=private"
    jobs = parse_alert(text)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Business Manager"
    assert jobs[0]["location"] == "دبي"
    assert jobs[0]["url"] == "https://www.linkedin.com/jobs/view/4470888126/"


@pytest.mark.parametrize(
    "text,period,kind,low,high",
    [
        ("AED6,000 - AED8,000 a month", "monthly", "listed_unverified", 6000, 8000),
        ("Up to AED4,000 a month", "monthly", "listed_unverified", None, 4000),
        ("From AED4,000 a month", "monthly", "listed_unverified", 4000, None),
        ("AED30,000 a month OTE", "monthly", "commission_or_ote", 30000, 30000),
        ("Estimated AED5,000 a month", "monthly", "estimated", 5000, 5000),
        ("AED120,000 per year", "annual", "listed_unverified", 120000, 120000),
        ("225 درهم إماراتي في الساعة", "hourly", "listed_unverified", 225, 225),
        ("٦٬٠٠٠ - ٨٬٠٠٠ درهم في الشهر", "monthly", "listed_unverified", 6000, 8000),
    ],
)
def test_salary_preserves_period_and_basis(text, period, kind, low, high):
    salary = salary_from_text(text)
    assert (salary["period"], salary["kind"], salary["min"], salary["max"]) == (
        period,
        kind,
        low,
        high,
    )


def test_deadline_is_separate_from_receipt_and_enforced():
    deadline = closing_date("Please apply no later than Monday 19th October 2026.")
    assert deadline == "2026-10-19"
    job = {**parse_alert(ALERT)[0], "deadline": deadline}
    result = assess(
        job, CareerProfile(skills=["Zoho Books"], cities=["Dubai"]), date(2026, 10, 26)
    )
    assert result["expired"] and result["score"] == 0


def test_missing_licence_is_gap_but_unknown_language_is_check():
    job = {
        **parse_alert(ALERT)[0],
        "description": "UAE driving licence is mandatory. English and Hindi required.",
    }
    result = assess(
        job, CareerProfile(uae_driving_license=False, languages=["English"])
    )
    assert any("licence" in gap for gap in result["gaps"])
    assert "Required language to confirm: hindi" in result["checks"]
    assert "Required language to confirm: english" not in result["checks"]
    assert result["acceptance_probability"] is None


def test_no_salary_points_for_ote_or_annual_figures():
    profile = CareerProfile(minimum_monthly_aed=5000)
    for salary in [
        "AED30,000 a month OTE",
        "AED120,000 a year",
        "Estimated AED8,000 a month",
    ]:
        job = {**parse_alert(ALERT)[0], "salary": salary_from_text(salary)}
        assert assess(job, profile)["score"] == 0


def test_mime_prefers_nested_plain_and_ignores_attachments():
    def encoded(s):
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

    payload = {
        "parts": [
            {"mimeType": "text/html", "body": {"data": encoded("<p>HTML</p>")}},
            {"parts": [{"mimeType": "text/plain", "body": {"data": encoded(ALERT)}}]},
            {"mimeType": "application/pdf", "body": {"attachmentId": "no-download"}},
        ]
    }
    assert mime_text(payload) == ALERT


def test_draft_contains_only_provided_summary():
    text = draft_application(
        parse_alert(ALERT)[0], CareerProfile(summary="I have four years in food sales.")
    )
    assert "four years in food sales" in text
    assert "revenue" not in text and "[Your name]" in text


class Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return Acquire(self.conn)


@pytest.mark.asyncio
async def test_owner_filters_are_passed_for_private_reads_writes_and_drafts():
    from types import SimpleNamespace

    conn = SimpleNamespace(fetchval=AsyncMock(return_value=None))
    svc = CareerService(Pool(conn))
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "viewer",
    )
    import uuid

    job_id = uuid.uuid4()
    assert await svc.job(ctx, job_id) is None
    await svc.status(ctx, job_id, "saved")
    assert await svc.draft(ctx, job_id) is None
    for call in conn.fetchval.call_args_list:
        sql, org_id, user_id, *_ = call.args
        assert "organization_id=$1 AND user_id=$2" in sql
        assert str(org_id) == ctx.org_id and str(user_id) == ctx.user_id


@pytest.mark.asyncio
async def test_oauth_state_is_single_use_owner_bound_before_exchange(monkeypatch):
    from types import SimpleNamespace

    from app.core.careers import gmail
    from app.core.careers.models import OAuthExchange

    conn = SimpleNamespace(fetchval=AsyncMock(return_value=None))
    exchange = AsyncMock()
    monkeypatch.setattr(gmail, "exchange", exchange)
    svc = CareerService(Pool(conn))
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "member",
    )
    with pytest.raises(ValueError, match="state"):
        await svc.oauth_finish(ctx, OAuthExchange(code="test", state="a" * 32))
    exchange.assert_not_awaited()
    sql, _, org_id, user_id = conn.fetchval.call_args.args
    assert sql.startswith("DELETE") and "expires_at>now()" in sql
    assert str(org_id) == ctx.org_id and str(user_id) == ctx.user_id


@pytest.mark.asyncio
async def test_import_conflict_preserves_existing_status():
    from types import SimpleNamespace

    conn = SimpleNamespace(fetchval=AsyncMock(side_effect=["new-id", None]))
    svc = CareerService(Pool(conn))
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "member",
    )
    result = await svc.import_on(conn, ctx, ALERT)
    assert result["inserted"] == 1 and result["duplicates"] == 1
    assert all("DO NOTHING" in c.args[0] for c in conn.fetchval.call_args_list)


def test_html_alert_links_before_company_do_not_lose_details():
    html = """<table><tr><td><a href="https://ae.indeed.com/rc/clk?jk=8b1f472f65632b95&amp;token=private">Supply Chain Officer</a>
    <div>Example Company</div><div>Dubai</div><p>AED6,000 - AED8,000 a month</p><p>Zoho Books required.</p></td></tr>
    <tr><td><a href="https://ae.indeed.com/viewjob?jk=79c60f05d50f2150">Customer Support</a><div>Example Services</div><div>Dubai</div><p>From AED4,000 a month</p></td></tr></table>"""
    jobs = parse_alert(html)
    assert len(jobs) == 2
    assert jobs[0]["company"] == "Example Company"
    assert jobs[0]["salary"]["min"] == 6000
    assert jobs[1]["title"] == "Customer Support"


def test_two_of_three_languages_is_a_choice_not_three_requirements():
    job = {
        **parse_alert(ALERT)[0],
        "description": "Proficiency in at least two languages among Hindi, Malayalam and Tamil is required; Arabic is an advantage.",
    }
    result = assess(job, CareerProfile(languages=["Hindi", "Malayalam"]))
    assert not any("language" in x for x in result["checks"])
    result = assess(job, CareerProfile(languages=["English"]))
    assert any("at least 2 languages" in x for x in result["checks"])


def test_optional_licence_is_not_a_hard_gap():
    job = {
        **parse_alert(ALERT)[0],
        "description": "A driving licence is not mandatory.",
    }
    assert not assess(job, CareerProfile(uae_driving_license=False))["gaps"]


def test_html_only_gmail_keeps_job_links_for_extraction():
    html = '<table><tr><td><a href="https://ae.indeed.com/viewjob?jk=79c60f05d50f2150">Customer Support</a><p>Example Services</p><p>Dubai</p><p>From AED4,000 a month</p></td></tr></table>'
    payload = {
        "mimeType": "text/html",
        "body": {"data": base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")},
    }
    assert len(parse_alert(mime_text(payload))) == 1


@pytest.mark.asyncio
async def test_invalid_oauth_state_route_is_safe_and_returns_no_tokens(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.routers import careers

    app = FastAPI()
    app.include_router(careers.router)
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "member",
    )
    app.dependency_overrides[careers.org_context] = lambda: ctx
    fake = AsyncMock()
    fake.oauth_finish.side_effect = ValueError("Invalid or expired OAuth state")
    monkeypatch.setattr(careers, "service", lambda: fake)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/careers/gmail/exchange", json={"code": "fake", "state": "b" * 32}
        )
    assert response.status_code == 400
    assert "token" not in response.text.lower()
    assert fake.oauth_finish.call_args.args[0] == ctx


@pytest.mark.asyncio
async def test_other_users_job_routes_return_404(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.routers import careers

    app = FastAPI()
    app.include_router(careers.router)
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "viewer",
    )
    app.dependency_overrides[careers.org_context] = lambda: ctx
    fake = AsyncMock()
    fake.status.return_value = None
    fake.draft.return_value = None
    fake.job.return_value = None
    monkeypatch.setattr(careers, "service", lambda: fake)
    job_id = "33333333-3333-3333-3333-333333333333"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = [
            await client.patch(
                f"/api/careers/jobs/{job_id}/status", json={"status": "saved"}
            ),
            await client.post(f"/api/careers/jobs/{job_id}/draft"),
            await client.post(f"/api/careers/jobs/{job_id}/verify"),
        ]
    assert all(response.status_code == 404 for response in responses)
    assert all("Job not found" in response.text for response in responses)
    assert fake.job.call_args.args[0] == ctx


@pytest.mark.asyncio
async def test_invalid_status_and_job_id_rejected_before_storage(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.routers import careers

    app = FastAPI()
    app.include_router(careers.router)
    app.dependency_overrides[careers.org_context] = lambda: OrgContext(
        "a", "b", "", "viewer"
    )
    fake = AsyncMock()
    monkeypatch.setattr(careers, "service", lambda: fake)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/api/careers/jobs/invalid/status", json={"status": "send"}
        )
    assert response.status_code == 422
    fake.status.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_sync_returns_busy_without_reading_mail(monkeypatch):
    from types import SimpleNamespace

    from app.core.careers import gmail

    conn = SimpleNamespace(fetchval=AsyncMock(return_value=False))
    read = AsyncMock()
    monkeypatch.setattr(gmail, "read_alerts", read)
    svc = CareerService(Pool(conn))
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "member",
    )
    assert (await svc.sync(ctx))["busy"] is True
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_race_rechecks_due_time_after_acquiring_lock(monkeypatch):
    from types import SimpleNamespace

    from app.core.careers import gmail

    conn = SimpleNamespace(
        fetchval=AsyncMock(return_value=True),
        fetchrow=AsyncMock(
            return_value={"refresh_encrypted": "unused", "enabled": True, "due": False}
        ),
        execute=AsyncMock(),
    )
    read = AsyncMock()
    monkeypatch.setattr(gmail, "read_alerts", read)
    svc = CareerService(Pool(conn))
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "member",
    )
    assert (await svc.sync(ctx, scheduled=True))["inserted"] == 0
    read.assert_not_awaited()
    assert "pg_advisory_unlock" in conn.execute.call_args.args[0]


def test_oauth_request_uses_pkce_and_only_readonly_scope(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    from app.core.careers import gmail

    monkeypatch.setattr(
        gmail,
        "settings",
        lambda: ("test-client", "test-secret", "https://example.test/careers"),
    )
    state, verifier, url = gmail.authorization()
    params = parse_qs(urlsplit(url).query)
    assert params["scope"] == [gmail.SCOPE]
    assert params["access_type"] == ["offline"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] == [state]
    assert verifier not in url


@pytest.mark.asyncio
async def test_gmail_sync_reads_only_alerts_and_preserves_message_arrival(monkeypatch):
    import httpx

    from app.core.careers import gmail

    monkeypatch.setattr(
        gmail,
        "settings",
        lambda: ("test-client", "test-secret", "https://example.test/careers"),
    )
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "test-access"})
        if request.url.path.endswith("/messages"):
            assert "newer_than:30d" in request.url.params["q"]
            assert "from:bayt.com" in request.url.params["q"]
            return httpx.Response(
                200, json={"messages": [{"id": "done"}, {"id": "new"}]}
            )
        assert request.url.path.endswith("/messages/new")
        return httpx.Response(
            200,
            json={
                "internalDate": "1793000000000",
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(ALERT.encode()).decode()},
                },
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        gmail.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    alerts = await gmail.read_alerts("test-refresh", {"done"})
    assert len(alerts) == 1 and alerts[0][0] == "new"
    assert alerts[0][1] == ALERT and alerts[0][2].startswith("2026-10-26")
    assert all(
        r.method == "GET" for r in requests if r.url.host != "oauth2.googleapis.com"
    )


@pytest.mark.asyncio
async def test_provider_failure_excludes_raw_response_and_token(monkeypatch):
    import httpx

    from app.core.careers import gmail

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda r: httpx.Response(400, json={"error_description": "PRIVATE_TOKEN_VALUE"})
    )
    monkeypatch.setattr(
        gmail.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    with pytest.raises(gmail.GmailUnavailable) as caught:
        await gmail.token_request({"refresh_token": "PRIVATE_TOKEN_VALUE"})
    assert "PRIVATE_TOKEN_VALUE" not in str(caught.value)


def test_failed_public_verification_keeps_requirements_unverified():
    job = {**parse_alert(ALERT)[0], "verification": "unavailable"}
    result = assess(job, CareerProfile())
    assert (
        "Full requirements unverified / الشروط الكاملة غير متحققة" in result["checks"]
    )
    assert result["priority"] == "review"


@pytest.mark.parametrize(
    ("url", "canonical", "source"),
    [
        (
            "https://www.bayt.com/en/uae/jobs/sales-executive-4963240/?utm_source=alert&token=PRIVATE",
            "https://www.bayt.com/en/uae/jobs/sales-executive-4963240/",
            "bayt",
        ),
        (
            "https://www.gulftalent.com/uae/jobs/accountant-447123?ref=alert",
            "https://www.gulftalent.com/uae/jobs/accountant-447123",
            "gulftalent",
        ),
        (
            "https://www.naukrigulf.com/sales-jobs-in-dubai-uae-in-example-2-to-5-years-n-cd-1-jid-201023000123?src=jobalert",
            "https://www.naukrigulf.com/sales-jobs-in-dubai-uae-in-example-2-to-5-years-n-cd-1-jid-201023000123",
            "naukrigulf",
        ),
    ],
)
def test_gulf_job_boards_are_canonicalised_without_tracking(url, canonical, source):
    assert canonical_job_url(url) == canonical
    jobs = parse_alert(f"Sales Executive\nExample Foods - Dubai\n{url}\n")
    assert [(j["url"], j["source"]) for j in jobs] == [(canonical, source)]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bayt.com.evil.test/en/uae/jobs/sales-4963240/",
        "https://www.bayt.com/en/uae/jobs/",
        "https://www.bayt.com/en/uae/jobs/sales-4963240/apply/",
        "https://www.gulftalent.com/uae/jobs/search",
        "https://www.naukrigulf.com/sales-jobs-in-dubai",
        "http://www.naukrigulf.com/sales-jid-201023000123",
    ],
)
def test_gulf_job_board_non_job_or_spoofed_urls_rejected(url):
    assert canonical_job_url(url) is None


def test_sync_limits_are_clamped_and_query_names_all_sources(monkeypatch):
    from app.core import config
    from app.core.careers import gmail

    monkeypatch.setattr(config, "CAREER_GMAIL_LOOKBACK_DAYS", "365")
    monkeypatch.setattr(config, "CAREER_GMAIL_MAX_MESSAGES", "not-a-number")
    assert gmail.limits() == (90, 150)
    monkeypatch.setattr(config, "CAREER_GMAIL_LOOKBACK_DAYS", "0")
    monkeypatch.setattr(config, "CAREER_GMAIL_MAX_MESSAGES", "9999")
    assert gmail.limits() == (1, 500)
    q = gmail.query(30)
    assert q.startswith("newer_than:30d -in:trash -in:spam (")
    for sender in gmail.SENDERS:
        assert "from:" + sender in q


@pytest.mark.asyncio
async def test_sync_reads_at_most_the_configured_number_of_pages(monkeypatch):
    import httpx

    from app.core import config
    from app.core.careers import gmail

    monkeypatch.setattr(
        gmail, "settings", lambda: ("id", "secret", "https://example.test/careers")
    )
    monkeypatch.setattr(config, "CAREER_GMAIL_MAX_MESSAGES", "100")
    lists = []

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "a"})
        lists.append(request)
        return httpx.Response(200, json={"messages": [], "nextPageToken": "more"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        gmail.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    assert await gmail.read_alerts("r", set()) == []
    assert len(lists) == 2


@pytest.mark.asyncio
async def test_unconfigured_connection_lists_missing_names_never_values(monkeypatch):
    from types import SimpleNamespace

    from app.core import config

    monkeypatch.setattr(config, "CAREER_GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(config, "CAREER_GOOGLE_CLIENT_SECRET", "PRIVATE_SECRET_VALUE")
    monkeypatch.setattr(config, "CAREER_GOOGLE_REDIRECT_URI", "")
    conn = SimpleNamespace(fetchrow=AsyncMock(return_value=None))
    ctx = OrgContext(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "",
        "member",
    )
    result = await CareerService(Pool(conn)).connection(ctx)
    assert result["configured"] is False
    assert result["missing"] == [
        "CAREER_GOOGLE_CLIENT_ID",
        "CAREER_GOOGLE_REDIRECT_URI",
    ]
    assert result["redirect_uri"] is None
    assert "PRIVATE_SECRET_VALUE" not in repr(result)
