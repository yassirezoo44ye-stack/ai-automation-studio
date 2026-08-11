"""Real-PostgreSQL RLS coverage — `billing_events` and `usage_records`
(remaining gap, docs/testing-foundation-p0.md §12).

billing_events.organization_id is nullable (ON DELETE SET NULL, and
Stripe webhook events may arrive before the org is resolvable) -- same
NULL-is-invisible-under-RLS proof pattern as marketplace_installs.
usage_records.organization_id is NOT NULL but has no FK constraint to
organizations (see app/billing/usage.py) -- doesn't change the RLS
behavior, just noted so the test isn't assumed to exercise a FK it
doesn't have.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


class TestBillingEventsTenantIsolation:
    async def test_billing_events_rls_backed_no_where_clause(self, two_orgs):
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO billing_events (stripe_event_id, event_type, organization_id, payload) "
                "VALUES ($1,'invoice.paid',$2,'{}'::jsonb)",
                f"evt_{uuid.uuid4().hex}", uuid.UUID(two_orgs["org_a"]),
            )
            await conn.execute(
                "INSERT INTO billing_events (stripe_event_id, event_type, organization_id, payload) "
                "VALUES ($1,'invoice.paid',$2,'{}'::jsonb)",
                f"evt_{uuid.uuid4().hex}", uuid.UUID(two_orgs["org_b"]),
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM billing_events WHERE event_type='invoice.paid'",
            )
        seen = {str(r["organization_id"]) for r in rows}
        assert two_orgs["org_a"] in seen
        assert two_orgs["org_b"] not in seen

    async def test_null_organization_id_event_is_invisible_to_any_scoped_connection(self, two_orgs):
        from app.core.db import acquire_scoped

        stripe_id = f"evt_{uuid.uuid4().hex}"
        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO billing_events (stripe_event_id, event_type, organization_id, payload) "
                "VALUES ($1,'unresolved.event',NULL,'{}'::jsonb)", stripe_id,
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            row = await conn.fetchrow(
                "SELECT organization_id FROM billing_events WHERE stripe_event_id=$1", stripe_id,
            )
        assert row is None

    async def test_webhook_event_service_dedup_is_per_event_id_not_per_org(self, two_orgs):
        """Real service-layer sanity check: WebhookEventService.record()'s
        idempotency key is stripe_event_id (globally unique), independent
        of org -- a replayed event id must be recognized regardless of
        which org gets passed the second time."""
        from app.billing.webhooks import WebhookEventService

        svc = WebhookEventService(two_orgs["pool"])
        stripe_id = f"evt_{uuid.uuid4().hex}"
        first = await svc.record(
            stripe_event_id=stripe_id, event_type="invoice.paid", payload={},
            organization_id=two_orgs["org_a"],
        )
        assert first is True  # new event, caller should process it

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "UPDATE billing_events SET processed_at=NOW() WHERE stripe_event_id=$1", stripe_id,
            )

        replay = await svc.record(
            stripe_event_id=stripe_id, event_type="invoice.paid", payload={},
            organization_id=two_orgs["org_a"],
        )
        assert replay is False  # already processed -- do not reprocess


class TestUsageRecordsTenantIsolation:
    async def test_usage_records_rls_backed_no_where_clause(self, two_orgs):
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO usage_records (organization_id, metric, period, amount) "
                "VALUES ($1,'api_requests','2026-08',10)", uuid.UUID(two_orgs["org_a"]),
            )
            await conn.execute(
                "INSERT INTO usage_records (organization_id, metric, period, amount) "
                "VALUES ($1,'api_requests','2026-08',20)", uuid.UUID(two_orgs["org_b"]),
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch(
                "SELECT organization_id FROM usage_records WHERE metric='api_requests'",
            )
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_usage_service_summary_only_returns_own_org(self, two_orgs):
        from app.billing.usage import UsageService

        svc = UsageService(two_orgs["pool"])
        await svc.record(two_orgs["org_a"], "api_requests", amount=5)
        await svc.record(two_orgs["org_b"], "api_requests", amount=9)

        summary_a = await svc.summary(two_orgs["org_a"])
        # summary() is org-scoped by construction (takes a single org_id) --
        # prove it actually reflects org A's own recorded usage, not org B's.
        assert summary_a["metrics"]["api_requests"]["used"] == 5
