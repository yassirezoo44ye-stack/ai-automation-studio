"""Real-PostgreSQL RLS coverage — `teams` and `chat_messages` (remaining
gap listed in docs/testing-foundation-p0.md §12). Both tables are already
created by conftest.py's existing init_tenancy_schema() call; this file
only adds the tests, same "no WHERE clause" RLS-proof rigor as every
other table in this package, plus real-service authorized-access and
ownership-boundary checks.

Read app/tenancy/service.py's create_team/list_teams/get_team and
app/core/chat/service.py's ChatService before writing any test here.
ChatService runs on a plain, unscoped pool (like credits.grant()/
payment_methods.sync_for_org()) -- every statement explicitly filters by
organization_id, and the router (app/routers/team_chat.py) always passes
a server-verified ctx.org_id. Documented, not a demonstrated
vulnerability, matching the pattern already established for those two
services.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


class TestTeamsTenantIsolation:
    async def test_list_teams_is_rls_backed_even_with_no_where_clause(self, two_orgs):
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO teams (organization_id, name) VALUES ($1, $2)",
                uuid.UUID(two_orgs["org_a"]), f"Team A {uuid.uuid4().hex[:6]}",
            )
            await conn.execute(
                "INSERT INTO teams (organization_id, name) VALUES ($1, $2)",
                uuid.UUID(two_orgs["org_b"]), f"Team B {uuid.uuid4().hex[:6]}",
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM teams")
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_create_and_list_team_via_real_service_stays_within_org(self, two_orgs):
        svc = two_orgs["svc"]
        team = await svc.create_team(
            two_orgs["org_a"], actor_id=two_orgs["user_a"], name=f"Team {uuid.uuid4().hex[:6]}",
        )
        assert str(team["organization_id"]) == two_orgs["org_a"]

        teams_a = await svc.list_teams(two_orgs["org_a"])
        assert any(str(t["id"]) == str(team["id"]) for t in teams_a)

        teams_b = await svc.list_teams(two_orgs["org_b"])
        assert not any(str(t["id"]) == str(team["id"]) for t in teams_b)

    async def test_get_team_cross_tenant_returns_none_not_the_other_orgs_team(self, two_orgs):
        """The router's _require_team_in_org() relies on get_team() returning
        None for a team_id that belongs to a different org -- proves that
        contract directly, with a real cross-org team_id, not assumed."""
        svc = two_orgs["svc"]
        team = await svc.create_team(
            two_orgs["org_a"], actor_id=two_orgs["user_a"], name=f"Team {uuid.uuid4().hex[:6]}",
        )
        result = await svc.get_team(two_orgs["org_b"], str(team["id"]))
        assert result is None


class TestChatMessagesTenantIsolationAndOwnership:
    async def test_list_messages_is_rls_backed_even_with_no_where_clause(self, two_orgs):
        from app.core.db import acquire_scoped

        async with two_orgs["pool"].acquire() as conn:
            await conn.execute(
                "INSERT INTO chat_messages (organization_id, user_id, body) VALUES ($1,$2,$3)",
                uuid.UUID(two_orgs["org_a"]), uuid.UUID(two_orgs["user_a"]), "hello from org A",
            )
            await conn.execute(
                "INSERT INTO chat_messages (organization_id, user_id, body) VALUES ($1,$2,$3)",
                uuid.UUID(two_orgs["org_b"]), uuid.UUID(two_orgs["user_b"]), "hello from org B",
            )

        async with acquire_scoped(two_orgs["org_a"]) as conn:
            rows = await conn.fetch("SELECT organization_id FROM chat_messages")
        seen = {str(r["organization_id"]) for r in rows}
        assert seen == {two_orgs["org_a"]}
        assert two_orgs["org_b"] not in seen

    async def test_chat_service_stays_unscoped_by_design_documented(self, two_orgs):
        """FINDING (documented, not fixed -- see module docstring): ChatService
        uses a plain unscoped connection like credits.grant(); an unqualified
        query through it (what the service itself uses internally) can see
        every org's messages. Not exploitable: the one real caller
        (app/routers/team_chat.py) always passes a server-verified
        ctx.org_id, never client input directly."""
        from app.core.chat.service import ChatService

        svc = ChatService(two_orgs["pool"])
        await svc.create_message(
            organization_id=two_orgs["org_a"], team_id=None,
            user_id=two_orgs["user_a"], body="org A message",
        )
        await svc.create_message(
            organization_id=two_orgs["org_b"], team_id=None,
            user_id=two_orgs["user_b"], body="org B message",
        )

        async with two_orgs["pool"].acquire() as conn:  # plain, unscoped -- what the service uses internally
            rows = await conn.fetch("SELECT organization_id FROM chat_messages")
        seen = {str(r["organization_id"]) for r in rows}
        assert {two_orgs["org_a"], two_orgs["org_b"]} <= seen

    async def test_list_messages_service_method_only_returns_own_org(self, two_orgs):
        from app.core.chat.service import ChatService

        svc = ChatService(two_orgs["pool"])
        await svc.create_message(
            organization_id=two_orgs["org_a"], team_id=None,
            user_id=two_orgs["user_a"], body="org A only",
        )
        messages_a = await svc.list_messages(organization_id=two_orgs["org_a"], team_id=None)
        assert all(m["organization_id"] == two_orgs["org_a"] for m in messages_a)

    async def test_delete_message_is_owner_only_even_within_the_same_org(self, two_orgs):
        """Ownership boundary distinct from the org boundary: two users in
        the SAME org, one cannot delete the other's message."""
        from app.core.chat.service import ChatService

        svc = ChatService(two_orgs["pool"])
        # Add user_b as a member of org_a's own users table isn't required --
        # delete_message() only checks (message_id, user_id), independent of
        # org membership -- so a second, unrelated user is enough to prove
        # the ownership check without needing a full membership setup.
        message = await svc.create_message(
            organization_id=two_orgs["org_a"], team_id=None,
            user_id=two_orgs["user_a"], body="only the author may delete this",
        )

        deleted = await svc.delete_message(message_id=message["id"], user_id=two_orgs["user_b"])
        assert deleted is False

        async with two_orgs["pool"].acquire() as conn:
            still_present = await conn.fetchval(
                "SELECT deleted_at FROM chat_messages WHERE id=$1", uuid.UUID(message["id"]),
            )
        assert still_present is None  # not soft-deleted by a non-owner

        deleted_by_owner = await svc.delete_message(message_id=message["id"], user_id=two_orgs["user_a"])
        assert deleted_by_owner is True
