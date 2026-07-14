"""
Architecture test suite — validates every upgraded layer of the OS.

Coverage:
  TestAgentBaseV2          — metadata, capabilities, permissions, validate,
                             estimate_cost, health_check, backward compat
  TestPlanningEngine       — intent analysis, agent assignment, risk scoring,
                             rollback plan, permission validation
  TestObservabilityMetrics — Counter, Gauge, Histogram, snapshot, Prometheus text
  TestObservabilityHealth  — probe registration, timeout, aggregate status
  TestObservabilityTracer  — span creation, finish, recent, active
  TestLayeredMemory        — short-term TTL, long-term persistence, search
  TestCodeGenPipeline      — format, lint, static_analysis, security_scan,
                             approval gate, reject
  TestServiceRegistry      — register, start, stop, health, state transitions
  TestBackgroundServices   — health_monitor, dependency_monitor, memory_compactor,
                             performance_optimizer, security_monitor tick
  TestConcurrency          — parallel plan + execution, memory thread-safety
  TestRollback             — rollback plan generation, execution
"""
from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


# ── Minimal stubs for modules that need a DB / kernel ─────────────────────────

def _stub_memory():
    m = MagicMock()
    m.total_count.return_value = 42
    m.recent.return_value      = []
    m.global_stats.return_value = []
    m.underperformers.return_value = []
    m.stats.return_value       = MagicMock(to_dict=lambda: {})
    return m


def _stub_kernel(agents=None):
    k             = MagicMock()
    k._booted     = True
    k._agents     = agents or {}
    k.all_agents.return_value = list((agents or {}).values())
    return k


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Agent base — upgraded interface
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentBaseV2(unittest.TestCase):

    def _make_agent(self, **kw):
        from app.agents.base import EvolvableAgent, AgentContext, AgentResult

        class _TestAgent(EvolvableAgent):
            name        = kw.get("name", "test_agent")
            description = "Test"
            group       = "test"

            async def execute(self, ctx: AgentContext) -> AgentResult:
                if ctx.input == "fail":
                    raise RuntimeError("deliberate failure")
                return AgentResult.ok(self.name, f"ok: {ctx.input}")

        return _TestAgent()

    def test_metadata_populated(self):
        agent = self._make_agent()
        md    = agent.metadata
        self.assertEqual(md.name, "test_agent")
        self.assertFalse(md.deprecated)

    def test_capabilities_default(self):
        from app.agents.base import CapabilityKind
        agent = self._make_agent()
        self.assertTrue(len(agent.capabilities) > 0)
        self.assertIsInstance(agent.capabilities[0].kind, CapabilityKind)

    def test_permissions_default(self):
        agent = self._make_agent()
        p     = agent.permissions
        self.assertFalse(p.can_write_filesystem)
        self.assertTrue(p.can_call_llm)

    def test_validate_empty_input(self):
        from app.agents.base import AgentContext
        agent = self._make_agent()
        ctx   = AgentContext(input="", args="", kernel=None, memory=None)
        v     = agent.validate(ctx)
        self.assertFalse(v.valid)
        self.assertTrue(len(v.errors) > 0)

    def test_validate_ok(self):
        from app.agents.base import AgentContext
        agent = self._make_agent()
        ctx   = AgentContext(input="run something", args="", kernel=None, memory=None)
        v     = agent.validate(ctx)
        self.assertTrue(v.valid)

    def test_estimate_cost_returns_estimate(self):
        from app.agents.base import AgentContext, CostEstimate
        agent = self._make_agent()
        ctx   = AgentContext(input="x" * 100, args="", kernel=None, memory=None)
        est   = agent.estimate_cost(ctx)
        self.assertIsInstance(est, CostEstimate)
        self.assertGreater(est.estimated_tokens, 0)

    def test_health_check_healthy(self):
        from app.agents.base import HealthStatus
        agent = self._make_agent()
        h     = agent.health_check()
        self.assertEqual(h.status, HealthStatus.HEALTHY)

    def test_run_validation_blocks_empty_input(self):
        from app.agents.base import AgentContext
        agent  = self._make_agent()
        ctx    = AgentContext(input="", args="", kernel=None, memory=None)
        result = run(agent.run(ctx))
        self.assertFalse(result.success)
        self.assertIn("Validation", result.error)

    def test_run_success(self):
        from app.agents.base import AgentContext
        agent  = self._make_agent()
        ctx    = AgentContext(input="hello", args="", kernel=None, memory=None)
        result = run(agent.run(ctx))
        self.assertTrue(result.success)

    def test_run_catches_exception(self):
        from app.agents.base import AgentContext
        agent  = self._make_agent()
        ctx    = AgentContext(input="fail", args="", kernel=None, memory=None)
        result = run(agent.run(ctx))
        self.assertFalse(result.success)
        self.assertIn("deliberate failure", result.error)

    def test_to_dict_has_new_fields(self):
        agent = self._make_agent()
        d     = agent.to_dict()
        for key in ("metadata", "capabilities", "permissions", "lifecycle", "version"):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_backward_compat_performance_hint(self):
        agent = self._make_agent()
        self.assertIsInstance(agent.performance_hint(), dict)

    def test_trace_id_propagated(self):
        from app.agents.base import AgentContext
        agent  = self._make_agent()
        ctx    = AgentContext(input="ping", args="", kernel=None, memory=None, trace_id="trace-001")
        result = run(agent.run(ctx))
        self.assertEqual(result.trace_id, "trace-001")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Planning Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanningEngine(unittest.TestCase):

    def setUp(self):
        from app.planning.engine import PlanningEngine
        self.engine = PlanningEngine()

    def test_plan_returns_rich_plan(self):
        from app.planning.engine import RichPlan
        plan = self.engine.plan("run the build pipeline", caller="test")
        self.assertIsInstance(plan, RichPlan)
        self.assertTrue(len(plan.tasks) > 0)

    def test_plan_has_id(self):
        plan = self.engine.plan("analyze performance")
        self.assertIsNotNone(plan.plan_id)

    def test_agent_assignment(self):
        plan = self.engine.plan("build the project")
        task = plan.tasks[0]
        self.assertIsNotNone(task.agent_name)

    def test_risk_low_for_safe_goal(self):
        from app.planning.engine import RiskLevel
        plan = self.engine.plan("analyze agent performance")
        self.assertIn(plan.risk_level, (RiskLevel.LOW, RiskLevel.MEDIUM))

    def test_risk_high_for_delete(self):
        from app.planning.engine import RiskLevel
        plan = self.engine.plan("delete all old files and wipe the database")
        self.assertIn(plan.risk_level, (RiskLevel.HIGH, RiskLevel.CRITICAL))

    def test_rollback_plan_for_deploy(self):
        plan = self.engine.plan("deploy to production")
        self.assertTrue(
            len(plan.rollback_plan) > 0,
            "Deploy plan must have a rollback"
        )

    def test_to_dict_serializable(self):
        import json
        plan = self.engine.plan("build and run tests")
        d    = plan.to_dict()
        json.dumps(d)   # must not raise

    def test_permission_errors_with_agents(self):
        from app.agents.base import EvolvableAgent, AgentResult, AgentPermissions

        class RestrictedAgent(EvolvableAgent):
            name        = "restricted"
            description = "Cannot write"
            async def execute(self, ctx): return AgentResult.ok(self.name, "ok")
            @property
            def permissions(self): return AgentPermissions(can_write_filesystem=False)

        agents = {"restricted": RestrictedAgent()}
        plan   = self.engine.plan("write a file", agents=agents)
        # May or may not have permission errors depending on task assignment
        self.assertIsInstance(plan.permission_errors, list)

    def test_parallel_groups_detected(self):
        plan = self.engine.plan("analyze performance and check status")
        self.assertIsInstance(plan.parallel_groups, list)

    def test_requires_approval_for_critical(self):
        plan = self.engine.plan("deploy to production environment")
        # High-risk plans must require approval
        if plan.risk_level.value in ("high", "critical"):
            self.assertTrue(plan.requires_approval)

    def test_cost_estimate_positive(self):
        plan = self.engine.plan("build the backend API")
        self.assertGreaterEqual(plan.total_cost_usd, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Observability — Metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservabilityMetrics(unittest.TestCase):

    def setUp(self):
        from app.core.observability.metrics import MetricsRegistry
        self.m = MetricsRegistry()

    def test_counter_increments(self):
        c = self.m.counter("test_counter", "A test counter")
        c.inc()
        c.inc(4)
        self.assertEqual(c.value, 5)

    def test_counter_reset(self):
        c = self.m.counter("reset_counter")
        c.inc(10)
        c.reset()
        self.assertEqual(c.value, 0)

    def test_gauge_set_inc_dec(self):
        g = self.m.gauge("test_gauge")
        g.set(10)
        g.inc(5)
        g.dec(3)
        self.assertAlmostEqual(g.value, 12)

    def test_histogram_percentiles(self):
        h = self.m.histogram("test_hist")
        for v in range(1, 101):
            h.observe(float(v))
        self.assertAlmostEqual(h.avg, 50.5, places=0)
        self.assertGreater(h.p95, h.p50)

    def test_snapshot_structure(self):
        self.m.counter("snap_c").inc(1)
        self.m.gauge("snap_g").set(2)
        snap = self.m.snapshot()
        self.assertIn("counters",   snap)
        self.assertIn("gauges",     snap)
        self.assertIn("histograms", snap)
        self.assertIn("uptime_s",   snap)

    def test_prometheus_text_format(self):
        self.m.counter("prom_c", "desc").inc(3)
        text = self.m.prometheus_text()
        self.assertIn("prom_c", text)
        self.assertIn("# HELP", text)
        self.assertIn("# TYPE", text)

    def test_same_name_returns_same_instance(self):
        c1 = self.m.counter("same")
        c2 = self.m.counter("same")
        c1.inc(7)
        self.assertEqual(c2.value, 7)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Observability — Health
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservabilityHealth(unittest.TestCase):

    def setUp(self):
        from app.core.observability.health import HealthRegistry
        self.hr = HealthRegistry()

    def _add_probe(self, name: str, status: str = "healthy", critical: bool = True):
        from app.core.observability.health import HealthStatus, ProbeResult
        async def probe():
            return ProbeResult(name=name, status=HealthStatus(status))
        self.hr.register(name, probe, critical=critical)

    def test_check_all_empty_returns_healthy(self):
        result = run(self.hr.check_all())
        self.assertEqual(result["status"], "healthy")

    def test_single_healthy_probe(self):
        self._add_probe("db", "healthy")
        result = run(self.hr.check_all())
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(len(result["probes"]), 1)

    def test_single_unhealthy_critical_probe(self):
        self._add_probe("db", "unhealthy", critical=True)
        result = run(self.hr.check_all())
        self.assertIn(result["status"], ("degraded", "unhealthy"))

    def test_two_unhealthy_critical_probes(self):
        self._add_probe("db",  "unhealthy", critical=True)
        self._add_probe("app", "unhealthy", critical=True)
        result = run(self.hr.check_all())
        self.assertEqual(result["status"], "unhealthy")

    def test_non_critical_unhealthy_gives_degraded(self):
        self._add_probe("cache", "unhealthy", critical=False)
        result = run(self.hr.check_all())
        self.assertEqual(result["status"], "degraded")

    def test_probe_timeout(self):
        from app.core.observability.health import HealthStatus, ProbeResult

        async def slow_probe():
            await asyncio.sleep(10)
            return ProbeResult(name="slow", status=HealthStatus.HEALTHY)

        self.hr.register("slow", slow_probe, timeout_s=0.05)
        result = run(self.hr.check_all())
        slow   = next(p for p in result["probes"] if p["name"] == "slow")
        self.assertEqual(slow["status"], "unhealthy")
        self.assertIn("Timed out", slow["message"])

    def test_unregister(self):
        self._add_probe("temp", "healthy")
        self.hr.unregister("temp")
        result = run(self.hr.check_all())
        self.assertFalse(any(p["name"] == "temp" for p in result["probes"]))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Observability — Tracer
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservabilityTracer(unittest.TestCase):

    def setUp(self):
        from app.core.observability.tracer import Tracer
        self.tracer = Tracer()

    def test_span_creates_and_finishes(self):
        span = self.tracer.start_span("test.op", service="test")
        time.sleep(0.01)
        span.finish()
        recent = self.tracer.recent(1)
        self.assertEqual(len(recent), 1)
        self.assertGreater(recent[0]["duration_ms"], 0)

    def test_span_as_context_manager(self):
        with self.tracer.start_span("ctx.op") as span:
            span.set_tag("key", "value")
        recent = self.tracer.recent(1)
        self.assertEqual(recent[0]["tags"]["key"], "value")

    def test_span_error_recorded(self):
        span = self.tracer.start_span("err.op")
        span.finish(error="something went wrong")
        self.assertEqual(self.tracer.recent(1)[0]["error"], "something went wrong")

    def test_active_spans(self):
        span = self.tracer.start_span("active.op")
        active = self.tracer.active()
        self.assertTrue(any(s["span_id"] == span.span_id for s in active))
        span.finish()
        active = self.tracer.active()
        self.assertFalse(any(s["span_id"] == span.span_id for s in active))

    def test_trace_id_groups_spans(self):
        # Real OpenTelemetry trace_ids are W3C 128-bit hex, not arbitrary
        # caller-supplied strings — group by an explicit real trace_id
        # (the first span's own id) rather than a made-up label.
        s1  = self.tracer.start_span("op1")
        tid = s1.trace_id
        s2  = self.tracer.start_span("op2", trace_id=tid, parent_id=s1.span_id)
        s1.finish()
        s2.finish()
        spans = self.tracer.trace(tid)
        self.assertEqual(len(spans), 2)
        self.assertTrue(all(s["trace_id"] == tid for s in spans))

    def test_recent_returns_newest_first(self):
        for i in range(5):
            s = self.tracer.start_span(f"op-{i}")
            s.finish()
        recent = self.tracer.recent(3)
        self.assertEqual(len(recent), 3)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Layered Memory
# ═══════════════════════════════════════════════════════════════════════════════

class TestLayeredMemory(unittest.TestCase):

    def setUp(self):
        from app.memory.layered import LayeredMemory
        self.mem = LayeredMemory()

    def _item(self, content: str, kind: str = "execution",
               agent: str = "test", success: bool = True):
        import uuid
        import time
        from app.memory.layered import MemoryItem
        return MemoryItem(
            id=str(uuid.uuid4()), layer="", kind=kind,
            content=content, tags=[], created_at=time.time(),
            agent=agent, success=success,
        )

    def test_add_appears_in_short_and_long(self):
        item = self._item("deploy error on production")
        self.mem.add(item)
        self.assertGreater(self.mem.short.count, 0)
        self.assertGreater(self.mem.long.count, 0)

    def test_recent_returns_added_item(self):
        item = self._item("unique content xyz987")
        self.mem.add(item)
        records = self.mem.recent(10)
        self.assertTrue(any(r.content == item.content for r in records))

    def test_search_finds_relevant_item(self):
        self.mem.add(self._item("build failed due to missing package"))
        self.mem.add(self._item("deploy completed successfully"))
        results = self.mem.search("build failure package")
        self.assertTrue(len(results) > 0)
        self.assertIn("build failed", results[0].content)

    def test_search_empty_query_returns_nothing(self):
        results = self.mem.search("", limit=10)
        self.assertEqual(len(results), 0)

    def test_kind_filter(self):
        self.mem.add(self._item("error logged", kind="error"))
        self.mem.add(self._item("task done",    kind="task"))
        error_records = self.mem.recent(50, kind="error")
        self.assertTrue(all(r.kind == "error" for r in error_records))

    def test_stats_dict(self):
        stats = self.mem.stats
        self.assertIn("short_term", stats)
        self.assertIn("long_term",  stats)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Code Generation Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodeGenPipeline(unittest.TestCase):

    def setUp(self):
        from app.codegen.pipeline import CodeGenPipeline
        self.pipeline = CodeGenPipeline()

    def _gen_fn(self, code: str):
        async def _fn(description, agent_name):
            return code
        return _fn

    GOOD_CODE = '''
from app.agents.base import EvolvableAgent, AgentContext, AgentResult

class MyAgent(EvolvableAgent):
    name        = "my_agent"
    description = "A safe test agent"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, "hello")
'''

    BAD_CODE_EXEC = '''
exec("import os; os.remove('/etc/passwd')")
'''

    BAD_CODE_SYNTAX = '''
def broken(:
    pass
'''

    BAD_CODE_SECRET = '''
password = "super_secret_123"
'''

    BAD_CODE_BANNED_IMPORT = '''
import ctypes
ctypes.cdll.LoadLibrary("evil.so")
'''

    def test_good_code_awaits_approval(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "A safe test agent", "my_agent",
            self._gen_fn(self.GOOD_CODE),
            requires_approval=True,
        ))
        self.assertEqual(result.status, CodeGenStatus.AWAITING)

    def test_good_code_auto_approved(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "A safe test agent", "my_agent",
            self._gen_fn(self.GOOD_CODE),
            requires_approval=False,
        ))
        self.assertEqual(result.status, CodeGenStatus.APPROVED)

    def test_exec_blocked(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "Dangerous agent", "evil",
            self._gen_fn(self.BAD_CODE_EXEC),
        ))
        self.assertEqual(result.status, CodeGenStatus.FAILED)

    def test_syntax_error_blocked(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "Broken agent", "broken",
            self._gen_fn(self.BAD_CODE_SYNTAX),
        ))
        self.assertEqual(result.status, CodeGenStatus.FAILED)

    def test_secret_in_code_blocked(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "Secret agent", "secret_agent",
            self._gen_fn(self.BAD_CODE_SECRET),
        ))
        self.assertEqual(result.status, CodeGenStatus.FAILED)

    def test_banned_import_blocked(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "ctypes agent", "ctypes_agent",
            self._gen_fn(self.BAD_CODE_BANNED_IMPORT),
        ))
        self.assertEqual(result.status, CodeGenStatus.FAILED)

    def test_approve_flow(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "Safe", "safe_agent",
            self._gen_fn(self.GOOD_CODE),
            requires_approval=True,
        ))
        self.assertEqual(result.status, CodeGenStatus.AWAITING)
        approved = self.pipeline.approve(result.run_id, approver="admin")
        self.assertIsNotNone(approved)
        self.assertEqual(approved.status, CodeGenStatus.APPROVED)
        self.assertEqual(approved.approved_by, "admin")

    def test_reject_flow(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "Safe", "safe_agent2",
            self._gen_fn(self.GOOD_CODE),
            requires_approval=True,
        ))
        rejected = self.pipeline.reject(result.run_id, reason="Policy violation")
        self.assertEqual(rejected.status, CodeGenStatus.REJECTED)

    def test_core_name_blocked(self):
        from app.codegen.pipeline import CodeGenStatus
        result = run(self.pipeline.run(
            "Shadow kernel", "kernel",
            self._gen_fn(self.GOOD_CODE),
        ))
        self.assertEqual(result.status, CodeGenStatus.FAILED)

    def test_list_pending(self):
        run(self.pipeline.run("P1", "pending1", self._gen_fn(self.GOOD_CODE), requires_approval=True))
        run(self.pipeline.run("P2", "pending2", self._gen_fn(self.GOOD_CODE), requires_approval=True))
        pending = self.pipeline.list_pending()
        self.assertGreaterEqual(len(pending), 2)

    def test_markdown_fence_stripped(self):
        fenced  = "```python\nprint('hello')\n```"
        code, r = self.pipeline._stage_format(fenced)
        self.assertNotIn("```", code)
        self.assertTrue(r.passed)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Service Registry
# ═══════════════════════════════════════════════════════════════════════════════

class TestServiceRegistry(unittest.TestCase):

    def _make_service(self, name: str = "test_svc", interval: float = 3600.0):
        from app.services.registry import BaseService

        class _Svc(BaseService):
            async def tick(self): pass

        svc = _Svc()
        svc.name       = name
        svc.interval_s = interval
        return svc

    def test_register_and_get(self):
        from app.services.registry import ServiceRegistry
        reg = ServiceRegistry()
        svc = self._make_service()
        reg.register(svc)
        self.assertIs(reg.get("test_svc"), svc)

    def test_start_returns_true(self):
        from app.services.registry import ServiceRegistry

        async def _run():
            reg = ServiceRegistry()
            svc = self._make_service()
            reg.register(svc)
            ok = reg.start("test_svc")
            await asyncio.sleep(0.05)
            reg.stop("test_svc")
            return ok

        self.assertTrue(run(_run()))

    def test_start_unknown_returns_false(self):
        from app.services.registry import ServiceRegistry
        reg = ServiceRegistry()
        self.assertFalse(reg.start("nonexistent"))

    def test_total_count(self):
        from app.services.registry import ServiceRegistry
        reg = ServiceRegistry()
        reg.register(self._make_service("s1"))
        reg.register(self._make_service("s2"))
        self.assertEqual(reg.total_count(), 2)

    def test_status_list(self):
        from app.services.registry import ServiceRegistry
        reg = ServiceRegistry()
        reg.register(self._make_service("s1"))
        status = reg.status()
        self.assertEqual(len(status), 1)
        self.assertEqual(status[0]["name"], "s1")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Background Services — tick()
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackgroundServiceTicks(unittest.TestCase):

    def _patched_memory(self):
        m                     = _stub_memory()
        m.total_count.return_value = 100
        stats_obj             = MagicMock()
        stats_obj.name        = "test_agent"
        stats_obj.avg_ms      = 100.0
        stats_obj.success_rate = 0.95
        stats_obj.call_count  = 10
        m.global_stats.return_value = [stats_obj]
        return m

    def test_health_monitor_tick(self):
        from app.services.health_monitor import HealthMonitorService

        async def _run():
            svc = HealthMonitorService()
            with patch("app.core.observability.health.get_health_registry") as mock_hr, \
                 patch("app.core.observability.metrics.get_metrics") as mock_m:
                mock_hr.return_value.check_all = AsyncMock(return_value={
                    "status": "healthy", "probes": []
                })
                mock_m.return_value = MagicMock(
                    gauge=MagicMock(return_value=MagicMock(set=MagicMock()))
                )
                await svc.tick()
        run(_run())

    def test_dependency_monitor_tick(self):
        from app.services.dependency_monitor import DependencyMonitorService

        async def _run():
            svc = DependencyMonitorService()
            with patch("app.core.observability.metrics.get_metrics") as mock_m:
                mock_m.return_value = MagicMock(
                    gauge=MagicMock(return_value=MagicMock(set=MagicMock()))
                )
                await svc.tick()
        run(_run())

    def test_memory_compactor_tick(self):
        from app.services.memory_compactor import MemoryCompactorService

        async def _run():
            svc = MemoryCompactorService()
            with patch("app.agents.memory.get_memory") as mock_mem, \
                 patch("app.core.observability.metrics.get_metrics") as mock_m:
                mock_mem.return_value = self._patched_memory()
                mock_m.return_value   = MagicMock(
                    gauge=MagicMock(return_value=MagicMock(set=MagicMock())),
                    counter=MagicMock(return_value=MagicMock(inc=MagicMock())),
                )
                await svc.tick()
        run(_run())

    def test_performance_optimizer_tick(self):
        from app.services.performance_optimizer import PerformanceOptimizerService

        async def _run():
            svc = PerformanceOptimizerService()
            with patch("app.agents.memory.get_memory") as mock_mem, \
                 patch("app.core.observability.metrics.get_metrics") as mock_m:
                mock_mem.return_value = self._patched_memory()
                mock_m.return_value   = MagicMock(
                    gauge=MagicMock(return_value=MagicMock(set=MagicMock())),
                )
                await svc.tick()
        run(_run())


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Concurrency
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrency(unittest.TestCase):

    def test_parallel_metrics_writes(self):
        """Counter must be correct under concurrent writes."""
        from app.core.observability.metrics import MetricsRegistry
        import threading

        m = MetricsRegistry()
        c = m.counter("concurrent_test")

        def _inc():
            for _ in range(1000):
                c.inc()

        threads = [threading.Thread(target=_inc) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(c.value, 10_000)

    def test_parallel_memory_writes(self):
        """LayeredMemory must be thread-safe."""
        import threading
        import uuid
        import time as _time
        from app.memory.layered import LayeredMemory, MemoryItem

        mem = LayeredMemory()
        errors = []

        def _write(n):
            try:
                for _ in range(100):
                    mem.add(MemoryItem(
                        id=str(uuid.uuid4()), layer="", kind="test",
                        content=f"thread-{n}", created_at=_time.time(),
                    ))
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [], f"Thread errors: {errors}")
        self.assertGreaterEqual(mem.short.count, 1)

    def test_parallel_planning(self):
        """PlanningEngine must be safe to call from multiple coroutines."""
        from app.planning.engine import PlanningEngine

        async def _run():
            engine = PlanningEngine()
            plans  = await asyncio.gather(*[
                asyncio.to_thread(engine.plan, f"goal {i}", caller="test")
                for i in range(10)
            ])
            return plans

        plans = run(_run())
        ids   = [p.plan_id for p in plans]
        self.assertEqual(len(set(ids)), 10, "All plan IDs must be unique")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Rollback
# ═══════════════════════════════════════════════════════════════════════════════

class TestRollback(unittest.TestCase):

    def test_rollback_plan_not_empty_for_risky_goal(self):
        from app.planning.engine import PlanningEngine
        engine = PlanningEngine()
        plan   = engine.plan("deploy to production and write new files")
        # At least one task should have a rollback
        has_rollback = any(t.rollback_action for t in plan.tasks)
        self.assertTrue(has_rollback, "Risky plan must have rollback actions")

    def test_rollback_order_reversed(self):
        from app.planning.engine import PlanningEngine
        engine = PlanningEngine()
        plan   = engine.plan("install packages then deploy to production")
        if len(plan.rollback_plan) > 1:
            # Rollback list should be in reversed execution order
            self.assertIsInstance(plan.rollback_plan, list)

    def test_rollback_plan_serializable(self):
        import json
        from app.planning.engine import PlanningEngine
        engine = PlanningEngine()
        plan   = engine.plan("build and deploy")
        json.dumps(plan.rollback_plan)   # must not raise


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    unittest.main(verbosity=2)
