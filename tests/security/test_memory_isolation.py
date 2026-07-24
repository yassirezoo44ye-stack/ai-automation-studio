"""
Security Regression Suite — Memory Isolation.

AgentMemory and LayeredMemory are both single, process-wide stores shared
by every tenant — neither has a native per-org partition, so isolation is
enforced entirely by the org_id filtering added to their read paths. Every
test here proves one thing: organization A can never read organization B's
raw execution/memory content, whether through the store's own API or the
HTTP endpoints built on top of it.

Relocated (unmodified, plus one new class extracted from
tests/test_agent_os.py's TestAgentMemory — see below) from
tests/test_security_hardening.py, tests/test_agent_os.py, and
tests/test_architecture.py as part of the Security Testing phase's
tests/security/ reorganization. No behavioral change.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.memory import AgentMemory, ExecutionRecord


# ═══════════════════════════════════════════════════════════════════════════════
# AgentMemory — org scoping at the store level (from test_agent_os.py's
# TestAgentMemory; extracted into its own class since the rest of that
# class is general functional coverage, not security-motivated)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_memory() -> AgentMemory:
    import threading
    mem = AgentMemory.__new__(AgentMemory)
    mem._lock    = threading.Lock()
    mem._records = []
    return mem


class TestAgentMemoryOrgIsolation:
    def test_recent_org_scoping_excludes_other_orgs(self):
        # AgentMemory is a single, process-wide log shared by every
        # tenant — recent(org_id=...) must never leak another org's
        # raw execution content (input/args/error) to the caller.
        mem = _make_memory()
        mem._records += [
            ExecutionRecord(agent="a", input="org-a secret", args="", success=True,
                             duration_ms=1.0, organization_id="org-a"),
            ExecutionRecord(agent="b", input="org-b secret", args="", success=True,
                             duration_ms=1.0, organization_id="org-b"),
            ExecutionRecord(agent="c", input="no-org legacy", args="", success=True,
                             duration_ms=1.0, organization_id=None),
        ]
        org_a = mem.recent(10, org_id="org-a")
        assert len(org_a) == 1
        assert org_a[0].input == "org-a secret"

        org_b = mem.recent(10, org_id="org-b")
        assert len(org_b) == 1
        assert org_b[0].input == "org-b secret"

        unscoped = mem.recent(10)
        assert len(unscoped) == 3  # no org_id passed — internal/system use only

    def test_global_stats_org_scoping(self):
        # global_stats/underperformers/total_count are aggregate (not raw
        # content) but still keyed by agent name across every tenant —
        # Agent Execution Isolation phase: org_id must scope them the same
        # way recent() already is, or /api/agentos/performance and
        # AutonomyEngine's prompt-building disclose another org's usage.
        mem = _make_memory()
        mem._records += [
            ExecutionRecord(agent="shared", input="x", args="", success=True,
                             duration_ms=1.0, organization_id="org-a"),
            ExecutionRecord(agent="shared", input="x", args="", success=False,
                             duration_ms=1.0, organization_id="org-b"),
            ExecutionRecord(agent="shared", input="x", args="", success=False,
                             duration_ms=1.0, organization_id="org-b"),
        ]
        a_stats = mem.global_stats(org_id="org-a")
        assert a_stats[0].call_count == 1
        assert a_stats[0].success_rate == 1.0

        b_stats = mem.global_stats(org_id="org-b")
        assert b_stats[0].call_count == 2
        assert b_stats[0].success_rate == 0.0

        assert mem.total_count(org_id="org-a") == 1
        assert mem.total_count(org_id="org-b") == 2
        assert mem.total_count() == 3  # unscoped — internal/system use only

        # org-b's own view flags its own underperformer...
        assert any(s.name == "shared" for s in mem.underperformers(
            threshold=0.7, min_calls=1, org_id="org-b"))
        # ...but org-a's view of its own data must not, since org-a's own
        # slice is 100% success — org-a never sees org-b dragged the
        # global number down.
        assert not any(s.name == "shared" for s in mem.underperformers(
            threshold=0.7, min_calls=1, org_id="org-a"))


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-tenant agent-execution memory leak (app/agents/memory.py, agent_os_api.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentosMemoryEndpointIsOrgScoped(unittest.TestCase):
    """GET /api/agentos/memory used to return every org's raw execution
    history (input/args/error) with zero tenant scoping — any
    authenticated user of any org could read it. It must resolve the
    caller's verified org (app.tenancy.context.optional_org_id, the same
    pattern used by the cross-org billing fix earlier this phase) and
    pass it through to AgentMemory.recent(org_id=...)."""

    def test_resolves_and_passes_verified_org_id(self):
        import asyncio

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-42")):
                mem = MagicMock()
                mem.recent = MagicMock(return_value=[])
                with patch("app.agents.memory.get_memory", return_value=mem):
                    from app.routers.agent_os_api import agentos_memory
                    req = MagicMock()
                    result = await agentos_memory(req, n=50)
                    return mem.recent, result

        recent_mock, result = asyncio.run(_run())
        recent_mock.assert_called_once_with(50, org_id="org-42")
        self.assertEqual(result, {"count": 0, "records": []})

    def _real_memory_with_two_tenants(self):
        """A real (non-mocked) AgentMemory, in-process only — same
        construction pattern tests/test_agent_os.py's _make_memory() uses
        — pre-populated with one record each for org-a and org-b, so the
        isolation tests below exercise the real recent(org_id=...)
        filtering logic end-to-end, not a mock's assertion."""
        import threading
        from app.agents.memory import AgentMemory, ExecutionRecord
        mem = AgentMemory.__new__(AgentMemory)
        mem._lock = threading.Lock()
        mem._records = [
            ExecutionRecord(agent="echo", input="org-a confidential business data", args="",
                             success=True, duration_ms=1.0, organization_id="org-a"),
            ExecutionRecord(agent="echo", input="org-b confidential business data", args="",
                             success=True, duration_ms=1.0, organization_id="org-b"),
        ]
        return mem

    def test_org_a_cannot_read_org_b_records(self):
        import asyncio

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-a")), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        self.assertEqual(result["count"], 1)
        inputs = [r["input"] for r in result["records"]]
        self.assertIn("org-a confidential business data", inputs)
        self.assertNotIn("org-b confidential business data", inputs)

    def test_org_b_cannot_read_org_a_records(self):
        # Same check, other direction — isolation must not be a one-way
        # accident of iteration/insertion order.
        import asyncio

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-b")), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        self.assertEqual(result["count"], 1)
        inputs = [r["input"] for r in result["records"]]
        self.assertIn("org-b confidential business data", inputs)
        self.assertNotIn("org-a confidential business data", inputs)

    def test_empty_result_when_caller_org_has_no_records(self):
        import asyncio

        mem = self._real_memory_with_two_tenants()  # only org-a / org-b have data

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-c")), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        self.assertEqual(result, {"count": 0, "records": []})

    def test_forged_org_id_is_ignored_when_membership_verification_fails(self):
        # optional_org_id resolves the raw X-Organization-Id header value
        # ONLY after verifying real DB membership (app.tenancy.context) —
        # a caller who names an org they don't belong to gets None back,
        # never the forged id. This proves the endpoint relies on that
        # verified value, not on a client-supplied header directly.
        import asyncio
        from unittest.mock import MagicMock as MM

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context._get_current_user_dep") as get_dep, \
                 patch("app.tenancy.context.get_tenancy_service") as get_svc, \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from fastapi.security import HTTPBearer
                with patch.object(HTTPBearer, "__call__", new=AsyncMock(return_value="creds")):
                    get_dep.return_value = AsyncMock(return_value={"id": "attacker"})
                    svc = MM()
                    svc.get_member_role = AsyncMock(return_value=None)  # not a member of org-a
                    get_svc.return_value = svc

                    req = MM()
                    req.headers = {"X-Organization-Id": "org-a"}  # forged/claimed, not actually a member
                    req.query_params = {}
                    req.path_params = {}

                    from app.routers.agent_os_api import agentos_memory
                    return await agentos_memory(req, n=50)

        result = asyncio.run(_run())
        # Falls back to the no-org bucket (org_id=None), never org-a's data
        self.assertEqual(result, {"count": 0, "records": []})

    def test_garbage_org_id_cannot_bypass_filtering(self):
        import asyncio

        mem = self._real_memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value=None)), \
                 patch("app.agents.memory.get_memory", return_value=mem):
                from app.routers.agent_os_api import agentos_memory
                return await agentos_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        # org_id=None is the explicit "no org" bucket — must not silently
        # widen to "every org", which is exactly the original leak.
        self.assertEqual(result, {"count": 0, "records": []})

    def test_missing_authentication_returns_401(self):
        # /api/agentos/memory is gated by factory.py's api_auth_middleware
        # like every other /api/* route outside PUBLIC_PREFIXES — an
        # unauthenticated request must never reach the handler at all.
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            import os
            os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
            os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
            from app.factory import create_app
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/agentos/memory")

        self.assertEqual(asyncio.run(_run()).status_code, 401)


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-tenant LayeredMemory leak (app/memory/layered.py, diagnostics_api.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticsMemoryEndpointIsOrgScoped(unittest.TestCase):
    """GET /api/diagnostics/memory and POST /api/diagnostics/memory/search
    read from LayeredMemory — a single, process-wide store shared by
    every tenant — with zero org scoping. Same fix shape as the AgentOS
    memory leak: resolve the caller's verified org via
    app.tenancy.context.optional_org_id and pass it through."""

    def _memory_with_two_tenants(self):
        import time
        import uuid
        from app.memory.layered import LayeredMemory, MemoryItem
        mem = LayeredMemory()
        mem.add(MemoryItem(id=str(uuid.uuid4()), layer="", kind="execution",
                            content="org-a confidential business data", tags=[],
                            created_at=time.time(), agent="assistant",
                            organization_id="org-a"))
        mem.add(MemoryItem(id=str(uuid.uuid4()), layer="", kind="execution",
                            content="org-b confidential business data", tags=[],
                            created_at=time.time(), agent="assistant",
                            organization_id="org-b"))
        return mem

    def test_org_a_cannot_read_org_b_records(self):
        import asyncio

        mem = self._memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-a")), \
                 patch("app.memory.layered.get_layered_memory", return_value=mem):
                from app.routers.diagnostics_api import diagnostics_memory
                return await diagnostics_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        contents = [r["content"] for r in result["records"]]
        self.assertIn("org-a confidential business data", contents)
        self.assertNotIn("org-b confidential business data", contents)

    def test_org_b_cannot_read_org_a_records(self):
        import asyncio

        mem = self._memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-b")), \
                 patch("app.memory.layered.get_layered_memory", return_value=mem):
                from app.routers.diagnostics_api import diagnostics_memory
                return await diagnostics_memory(MagicMock(), n=50)

        result = asyncio.run(_run())
        contents = [r["content"] for r in result["records"]]
        self.assertIn("org-b confidential business data", contents)
        self.assertNotIn("org-a confidential business data", contents)

    def test_forged_org_id_is_ignored_when_membership_verification_fails(self):
        import asyncio
        from unittest.mock import MagicMock as MM

        mem = self._memory_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context._get_current_user_dep") as get_dep, \
                 patch("app.tenancy.context.get_tenancy_service") as get_svc, \
                 patch("app.memory.layered.get_layered_memory", return_value=mem):
                from fastapi.security import HTTPBearer
                with patch.object(HTTPBearer, "__call__", new=AsyncMock(return_value="creds")):
                    get_dep.return_value = AsyncMock(return_value={"id": "attacker"})
                    svc = MM()
                    svc.get_member_role = AsyncMock(return_value=None)  # not a member of org-a
                    get_svc.return_value = svc

                    req = MM()
                    req.headers = {"X-Organization-Id": "org-a"}
                    req.query_params = {}
                    req.path_params = {}

                    from app.routers.diagnostics_api import diagnostics_memory
                    return await diagnostics_memory(req, n=50)

        result = asyncio.run(_run())
        contents = [r["content"] for r in result["records"]]
        self.assertNotIn("org-a confidential business data", contents)
        self.assertNotIn("org-b confidential business data", contents)

    def test_missing_authentication_returns_401(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport

        async def _run():
            import os
            os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
            os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")
            from app.factory import create_app
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/diagnostics/memory")

        self.assertEqual(asyncio.run(_run()).status_code, 401)


# ═══════════════════════════════════════════════════════════════════════════════
# LayeredMemory — org scoping at the store level (from test_architecture.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLayeredMemoryOrgScoping(unittest.TestCase):
    """LayeredMemory is a single, process-wide store shared by every
    tenant — recent()/search() must never leak another org's raw item
    content to a caller scoping by org_id."""

    def setUp(self):
        from app.memory.layered import LayeredMemory
        self.mem = LayeredMemory()

    def _item(self, content: str, organization_id):
        import uuid
        import time
        from app.memory.layered import MemoryItem
        return MemoryItem(
            id=str(uuid.uuid4()), layer="", kind="execution",
            content=content, tags=[], created_at=time.time(),
            agent="assistant", success=True,
            organization_id=organization_id,
        )

    def test_recent_scoped_to_own_org(self):
        self.mem.add(self._item("org-a secret", "org-a"))
        self.mem.add(self._item("org-b secret", "org-b"))
        records = self.mem.recent(10, org_id="org-a")
        contents = [r.content for r in records]
        self.assertIn("org-a secret", contents)
        self.assertNotIn("org-b secret", contents)

    def test_recent_excludes_other_org_even_with_same_kind_and_agent(self):
        # Same kind + agent across two orgs on purpose — isolation must
        # hold on organization_id alone. Uses membership checks, not
        # exact counts: LongTermMemory persists to a shared on-disk file
        # across the whole test session (by design — durable long-term
        # memory), so other tests' org-b records legitimately accumulate
        # here too; what matters is zero cross-contamination, not volume.
        self.mem.add(self._item("org-a confidential marker", "org-a"))
        self.mem.add(self._item("org-b confidential marker", "org-b"))
        org_b_records = self.mem.recent(50, org_id="org-b")
        contents = [r.content for r in org_b_records]
        self.assertIn("org-b confidential marker", contents)
        self.assertNotIn("org-a confidential marker", contents)
        self.assertTrue(all(r.organization_id == "org-b" for r in org_b_records))

    def test_search_scoped_to_own_org(self):
        self.mem.add(self._item("deploy failed on production server", "org-a"))
        self.mem.add(self._item("deploy failed on production server", "org-b"))
        results = self.mem.search("deploy failed production", org_id="org-a")
        self.assertTrue(len(results) >= 1)
        self.assertTrue(all(r.organization_id == "org-a" for r in results))

    def test_no_org_id_returns_only_no_org_bucket_not_everything(self):
        # A caller with no verified org (org_id=None) must be scoped to
        # the no-org bucket, never fall through to "everyone's data" —
        # the exact bug caught before the AgentMemory fix landed.
        self.mem.add(self._item("org-a secret", "org-a"))
        self.mem.add(self._item("legacy no-org item", None))
        records = self.mem.recent(10, org_id=None)
        contents = [r.content for r in records]
        self.assertIn("legacy no-org item", contents)
        self.assertNotIn("org-a secret", contents)

    def test_unscoped_default_is_internal_only_cross_tenant_view(self):
        # Leaving org_id unset entirely (the default) is the deliberate
        # internal/system escape hatch — both orgs' items must appear
        # together in one unscoped read, proving org isn't being
        # filtered when the caller didn't ask for scoping.
        self.mem.add(self._item("org-a unscoped-view marker", "org-a"))
        self.mem.add(self._item("org-b unscoped-view marker", "org-b"))
        records = self.mem.recent(10)  # both items are the most recent 2 additions
        contents = [r.content for r in records]
        self.assertIn("org-a unscoped-view marker", contents)
        self.assertIn("org-b unscoped-view marker", contents)

    def test_concurrent_access_from_multiple_orgs_stays_isolated(self):
        """Multiple orgs writing/reading LayeredMemory concurrently must
        never see each other's items — proves org filtering holds under
        the same threaded-write pattern test_parallel_memory_writes uses
        to prove thread-safety."""
        import threading
        errors: list[str] = []
        seen_leak: list[str] = []

        def _work(org: str):
            try:
                for i in range(20):
                    self.mem.add(self._item(f"{org}-item-{i}", org))
                records = self.mem.recent(100, org_id=org)
                for r in records:
                    if r.organization_id != org:
                        seen_leak.append(f"{org} saw {r.organization_id}'s item")
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_work, args=(org,))
                   for org in ("org-a", "org-b", "org-c")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        self.assertEqual(seen_leak, [], f"Cross-org leaks: {seen_leak}")


if __name__ == "__main__":
    unittest.main()
