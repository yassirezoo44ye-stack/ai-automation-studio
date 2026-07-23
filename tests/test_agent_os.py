"""
Tests for the Agentic OS runtime.

Covers:
  - AgentMemory: record, stats, underperformers
  - IntentParser: alias, pattern, fuzzy, unknown
  - EvolvableAgent: interface, run() timing
  - AgentKernel: boot, register, run, collaborate, plan_and_run
  - EvolutionEngine: analyze (no LLM required)
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock


from app.agents.base    import AgentContext, AgentResult, EvolvableAgent
from app.agents.intent  import IntentParser
from app.agents.memory  import AgentMemory, ExecutionRecord
from app.agents.evolution import EvolutionEngine, EvolutionReport


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

class EchoAgent(EvolvableAgent):
    name        = "echo"
    description = "Echoes args back"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, ctx.args or "empty",
                              data={"args": ctx.args})


class FailAgent(EvolvableAgent):
    name        = "fail"
    description = "Always fails"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.fail(self.name, "intentional failure")


class SlowAgent(EvolvableAgent):
    name        = "slow"
    description = "Takes 50ms"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        await asyncio.sleep(0.05)
        return AgentResult.ok(self.name, "done")


def _make_memory() -> AgentMemory:
    """In-memory only (no file I/O)."""
    mem = AgentMemory.__new__(AgentMemory)
    import threading
    mem._lock    = threading.Lock()
    mem._records = []
    return mem


def _make_kernel() -> "AgentKernel":
    from app.agents.kernel import AgentKernel
    from app.plugins.registry_guard import OwnershipTracker
    k = AgentKernel.__new__(AgentKernel)
    k._agents       = {}
    k._agent_owners = OwnershipTracker("agent")
    k._memory       = _make_memory()
    k._parser       = IntentParser()
    k._booted       = True
    k._modifier     = None
    k._reloader     = None
    k._evolution    = None
    k._router       = None
    k._reflector    = None
    k._deliberation = None
    k._autonomy     = None
    k._loop         = None
    return k


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────────────────
# AgentMemory
# ──────────────────────────────────────────────────────────────────────────────

class TestAgentMemory:
    def _record(self, agent="echo", success=True, ms=10.0, error=None):
        return ExecutionRecord(agent=agent, input="test", args="",
                               success=success, duration_ms=ms, error=error)

    def test_add_and_recent(self):
        mem = _make_memory()
        for i in range(5):
            mem._records.append(self._record())
        assert len(mem.recent(3)) == 3
        assert len(mem.recent(10)) == 5

    def test_total_count(self):
        mem = _make_memory()
        for i in range(7):
            mem._records.append(self._record())
        assert mem.total_count() == 7

    def test_stats_empty(self):
        mem = _make_memory()
        s = mem.stats("nobody")
        assert s.call_count == 0
        assert s.success_rate == 1.0

    def test_stats_with_records(self):
        mem = _make_memory()
        mem._records += [
            self._record("echo", True,  20.0),
            self._record("echo", True,  30.0),
            self._record("echo", False, 40.0),
        ]
        s = mem.stats("echo")
        assert s.call_count == 3
        assert s.success_count == 2
        assert s.fail_count == 1
        assert abs(s.success_rate - 2/3) < 0.01
        assert abs(s.avg_ms - 30.0) < 0.01

    def test_underperformers_threshold(self):
        mem = _make_memory()
        # 1 success, 9 failures → 10% success rate
        for _ in range(9):
            mem._records.append(self._record("bad", False))
        mem._records.append(self._record("bad", True))
        # 5 successes → 100%
        for _ in range(5):
            mem._records.append(self._record("good", True))

        under = mem.underperformers(threshold=0.7, min_calls=3)
        names = [s.name for s in under]
        assert "bad" in names
        assert "good" not in names

    def test_underperformers_respects_min_calls(self):
        mem = _make_memory()
        mem._records.append(self._record("rare", False))   # only 1 call
        under = mem.underperformers(threshold=0.7, min_calls=3)
        assert not any(s.name == "rare" for s in under)

    def test_for_agent(self):
        mem = _make_memory()
        mem._records += [
            self._record("a"), self._record("b"), self._record("a"),
        ]
        assert len(mem.for_agent("a")) == 2
        assert len(mem.for_agent("b")) == 1

    def test_global_stats_ordering(self):
        mem = _make_memory()
        for _ in range(5):
            mem._records.append(self._record("popular"))
        for _ in range(2):
            mem._records.append(self._record("rare"))
        stats = mem.global_stats()
        assert stats[0].name == "popular"
        assert stats[1].name == "rare"

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


# ──────────────────────────────────────────────────────────────────────────────
# StatusAgent — the other raw-content reader that used to leak cross-tenant
# ──────────────────────────────────────────────────────────────────────────────

class TestStatusAgentOrgScoping:
    def test_status_agent_only_sees_own_org_executions(self):
        # Same agent name ("echo") on both records on purpose — isolation
        # must hold on organization_id alone, not accidentally depend on
        # agent name/id ever differing between tenants.
        from app.agents.builtin.status_agent import StatusAgent

        mem = _make_memory()
        mem._records += [
            ExecutionRecord(agent="echo", input="org-a confidential task", args="",
                             success=True, duration_ms=1.0, organization_id="org-a"),
            ExecutionRecord(agent="echo", input="org-b confidential task", args="",
                             success=True, duration_ms=1.0, organization_id="org-b"),
        ]
        kernel = _make_kernel()
        kernel._memory = mem
        ctx = AgentContext(input="status", args="", kernel=kernel, memory=mem,
                           organization_id="org-a")

        result = _run(StatusAgent().execute(ctx))

        assert "org-a confidential task" in result.output
        assert "org-b confidential task" not in result.output

    def test_status_agent_with_no_org_sees_only_no_org_bucket(self):
        # A caller with no verified org (organization_id=None) must be
        # scoped to the no-org bucket, never fall through to "everyone's
        # data" — this is the exact bug caught before the fix landed.
        from app.agents.builtin.status_agent import StatusAgent

        mem = _make_memory()
        mem._records += [
            ExecutionRecord(agent="echo", input="org-a confidential task", args="",
                             success=True, duration_ms=1.0, organization_id="org-a"),
        ]
        kernel = _make_kernel()
        kernel._memory = mem
        ctx = AgentContext(input="status", args="", kernel=kernel, memory=mem,
                           organization_id=None)

        result = _run(StatusAgent().execute(ctx))

        assert "org-a confidential task" not in result.output


# ──────────────────────────────────────────────────────────────────────────────
# IntentParser
# ──────────────────────────────────────────────────────────────────────────────

class TestIntentParser:
    def setup_method(self):
        self.parser = IntentParser(known_agents=["run", "build", "deploy",
                                                  "analyze", "evolve", "plan",
                                                  "status", "help", "echo"])

    def test_exact_alias(self):
        r = self.parser.parse("run ./my-project")
        assert r.intent == "run"
        assert r.confidence == 1.0
        assert r.method == "alias"

    def test_alias_synonyms(self):
        assert self.parser.parse("execute ./x").intent == "run"
        assert self.parser.parse("compile .").intent == "build"
        assert self.parser.parse("ship to production").intent == "deploy"
        assert self.parser.parse("optimize").intent == "evolve"

    def test_natural_language_pattern(self):
        r = self.parser.parse("please run my server in the background")
        assert r.intent == "run"
        assert r.method == "pattern"

    def test_fuzzy_typo(self):
        r = self.parser.parse("bild my project")    # typo: bild → build
        assert r.intent == "build"
        assert r.method == "fuzzy"

    def test_unknown_with_suggestions(self):
        r = self.parser.parse("xyzzy the thing")
        assert r.intent == "unknown"
        assert r.confidence == 0.0
        assert len(r.suggestions) > 0

    def test_empty_input_defaults_to_help(self):
        r = self.parser.parse("")
        assert r.intent == "help"

    def test_args_extracted(self):
        r = self.parser.parse("build ./my-project --output=./dist")
        assert r.intent == "build"
        assert "./my-project" in r.args

    def test_question_mark_alias(self):
        r = self.parser.parse("?")
        assert r.intent == "help"


# ──────────────────────────────────────────────────────────────────────────────
# EvolvableAgent
# ──────────────────────────────────────────────────────────────────────────────

class TestEvolvableAgent:
    def _ctx(self, args="hello"):
        kernel = _make_kernel()
        ctx = AgentContext(
            input="echo hello", args=args,
            kernel=kernel, memory=_make_memory(),
        )
        return ctx

    def test_ok_factory(self):
        r = AgentResult.ok("echo", "output", {"key": "value"}, 15.0)
        assert r.success is True
        assert r.output == "output"
        assert r.data == {"key": "value"}
        assert r.duration_ms == 15.0

    def test_fail_factory(self):
        r = AgentResult.fail("echo", "boom")
        assert r.success is False
        assert "boom" in r.output
        assert r.error == "boom"

    def test_to_dict(self):
        r = AgentResult.ok("echo", "out")
        d = r.to_dict()
        assert d["agent"] == "echo"
        assert d["success"] is True

    def test_run_timing(self):
        agent = EchoAgent()
        ctx   = self._ctx("world")
        result = _run(agent.run(ctx))
        assert result.success
        assert result.duration_ms >= 0

    def test_run_catches_exception(self):
        class BrokenAgent(EvolvableAgent):
            name = "broken"
            description = "Raises"
            group = "test"
            async def execute(self, ctx):
                raise RuntimeError("oops")

        agent = BrokenAgent()
        result = _run(agent.run(self._ctx()))
        assert result.success is False
        assert "oops" in result.error

    def test_performance_hint_default(self):
        agent = EchoAgent()
        assert isinstance(agent.performance_hint(), dict)

    def test_to_dict(self):
        agent = EchoAgent()
        d = agent.to_dict()
        assert d["name"] == "echo"
        assert d["group"] == "test"


# ──────────────────────────────────────────────────────────────────────────────
# AgentKernel
# ──────────────────────────────────────────────────────────────────────────────

class TestAgentKernel:
    def setup_method(self):
        self.kernel = _make_kernel()
        self.kernel.register_agent(EchoAgent())
        self.kernel.register_agent(FailAgent())
        self.kernel.register_agent(SlowAgent())
        self.kernel._parser.update_agents(list(self.kernel._agents.keys()))

    def test_register_and_get(self):
        assert self.kernel.get_agent("echo") is not None
        assert self.kernel.get_agent("nope") is None

    def test_unregister(self):
        self.kernel.register_agent(EchoAgent())
        assert self.kernel.unregister_agent("echo") is True
        assert self.kernel.get_agent("echo") is None
        assert self.kernel.unregister_agent("echo") is False

    def test_all_agents(self):
        agents = self.kernel.all_agents()
        names  = {a.name for a in agents}
        assert "echo" in names and "fail" in names

    def test_run_success(self):
        result = _run(self.kernel.run("echo hello world"))
        assert result.success
        assert "hello world" in result.output or result.agent == "echo"

    def test_run_fail_agent(self):
        result = _run(self.kernel.run("fail"))
        assert result.success is False

    def test_run_unknown_intent(self):
        result = _run(self.kernel.run("xyzzy_nonexistent_command_abc"))
        assert result.success is False
        assert "suggestions" in result.data or "agents" in result.data

    def test_run_records_to_memory(self):
        before = self.kernel._memory.total_count()
        _run(self.kernel.run("echo test"))
        assert self.kernel._memory.total_count() == before + 1

    def test_run_tags_memory_record_with_caller_org(self):
        # Regression: kernel.run() must stamp organization_id onto the
        # ExecutionRecord it writes, or AgentMemory.recent(org_id=...)
        # has nothing to scope by and every tenant's records look
        # ownerless (which recent()'s unscoped path treats as visible
        # to nobody's org-scoped query, silently hiding the leak).
        _run(self.kernel.run("echo test", organization_id="org-xyz"))
        record = self.kernel._memory.recent(1)[0]
        assert record.organization_id == "org-xyz"

    def test_run_without_organization_id_records_none(self):
        # Backward compatibility: legacy/single-tenant callers that never
        # pass organization_id (e.g. a local, no-org deployment) must
        # keep working exactly as before — the record is just tagged
        # None, not rejected or defaulted to some other tenant's id.
        _run(self.kernel.run("echo test"))
        record = self.kernel._memory.recent(1)[0]
        assert record.organization_id is None

    def test_sequential_runs_each_tagged_with_their_own_org(self):
        # Proves org tagging isn't accidentally sticky/cached across
        # calls on the same kernel instance — each run's record must
        # carry exactly the org_id that call was made with.
        _run(self.kernel.run("echo one", organization_id="org-a"))
        _run(self.kernel.run("echo two", organization_id="org-b"))
        _run(self.kernel.run("echo three", organization_id="org-a"))
        records = self.kernel._memory.recent(3)
        assert [r.organization_id for r in records] == ["org-a", "org-b", "org-a"]

    def test_collaborate_parallel_tags_every_task_with_caller_org(self):
        # collaborate(parallel=True) is this kernel's concurrent/async
        # execution path (asyncio.gather over kernel.run()) — verify org
        # tagging survives it and no task's record leaks a different or
        # missing org_id under concurrency.
        _run(self.kernel.collaborate(
            ["echo one", "echo two", "echo three"],
            parallel=True, organization_id="org-concurrent",
        ))
        records = self.kernel._memory.for_agent("echo")
        assert len(records) == 3
        assert all(r.organization_id == "org-concurrent" for r in records)

    def test_collaborate_sequential_stops_on_failure(self):
        results = _run(self.kernel.collaborate(["fail", "echo after"], parallel=False))
        # Stops after first failure
        assert len(results) == 1
        assert results[0].success is False

    def test_collaborate_sequential_continues_on_success(self):
        results = _run(self.kernel.collaborate(["echo a", "echo b"], parallel=False))
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_collaborate_parallel(self):
        results = _run(self.kernel.collaborate(["echo x", "echo y", "echo z"], parallel=True))
        assert len(results) == 3

    def test_status_dict(self):
        s = self.kernel.status()
        assert "agents" in s
        assert "memory_count" in s
        assert s["agents"] >= 3

    def test_timing_captured(self):
        result = _run(self.kernel.run("slow"))
        assert result.duration_ms >= 40     # slow agent sleeps 50ms


# ──────────────────────────────────────────────────────────────────────────────
# Agent Execution Isolation — AgentKernel._agents is a single, process-wide
# dict shared by every tenant's plugin-installed and self-generated agents.
# These verify the visibility/execution gate (AgentKernel.visible_agent_names
# + the ownership check inside run()) actually blocks cross-tenant use, not
# just cross-tenant *registration* collisions (already covered separately in
# tests/test_plugins.py's TestAgentRegistrationOwnership).
# ──────────────────────────────────────────────────────────────────────────────

class _OwnedAgent(EvolvableAgent):
    name        = "owned_agent"
    description = "belongs to whichever org registered it"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, f"ran for org={ctx.organization_id}")


class TestAgentExecutionIsolation:
    def setup_method(self):
        self.kernel = _make_kernel()
        self.kernel.register_agent(EchoAgent())          # owner=None: built-in
        self.kernel.register_agent(SlowAgent())           # owner=None: built-in
        self.kernel.register_agent(_OwnedAgent(), owner="org-a")
        self.kernel._parser.update_agents(list(self.kernel._agents.keys()))

    def test_owner_can_invoke_its_own_agent(self):
        result = _run(self.kernel.run("owned_agent", organization_id="org-a"))
        assert result.success
        assert "org=org-a" in result.output

    def test_other_org_cannot_invoke_it_by_name(self):
        # Org B running a tool/agent against a resource belonging to org A:
        # intent-parsing still resolves the real registered name, but the
        # execution gate must treat it exactly like "no agent for this
        # intent" — same error shape as a genuinely unknown name, so org B
        # gets no signal that org-a's agent even exists.
        result = _run(self.kernel.run("owned_agent", organization_id="org-b"))
        assert result.success is False
        assert result.error == "agent_not_found"
        assert "owned_agent" not in result.data.get("agents", [])

    def test_forged_or_missing_org_id_is_not_a_wildcard(self):
        # optional_org_id() never raises — an unauthenticated caller or one
        # with a garbage header value still reaches kernel.run() with some
        # organization_id. Neither None nor a made-up value may act as a
        # skeleton key that unlocks every tenant's agents.
        for org in (None, "totally-made-up-org", ""):
            result = _run(self.kernel.run("owned_agent", organization_id=org))
            assert result.success is False
            assert result.error == "agent_not_found"

    def test_builtin_stays_invocable_by_everyone(self):
        for org in (None, "org-a", "org-b", "anything"):
            result = _run(self.kernel.run("echo hi", organization_id=org))
            assert result.success

    def test_visible_agent_names_scoped_per_org(self):
        assert "owned_agent" in self.kernel.visible_agent_names("org-a")
        assert "owned_agent" not in self.kernel.visible_agent_names("org-b")
        assert "owned_agent" not in self.kernel.visible_agent_names(None)
        assert "echo" in self.kernel.visible_agent_names("org-b")  # built-in

    def test_status_agent_names_scoped_per_org(self):
        s_a = self.kernel.status(organization_id="org-a")
        s_b = self.kernel.status(organization_id="org-b")
        assert "owned_agent" in s_a["agent_names"]
        assert "owned_agent" not in s_b["agent_names"]

    def test_concurrent_execution_from_two_orgs_stays_isolated(self):
        # Two orgs hitting the kernel at the same time via asyncio.gather —
        # org-b's call must fail exactly as it would alone, unaffected by
        # org-a's concurrent, legitimate call to the same agent name.
        async def scenario():
            return await asyncio.gather(
                self.kernel.run("owned_agent", organization_id="org-a"),
                self.kernel.run("owned_agent", organization_id="org-b"),
            )

        a_result, b_result = _run(scenario())
        assert a_result.success is True
        assert b_result.success is False
        assert b_result.error == "agent_not_found"

    def test_cancelling_one_orgs_task_does_not_cancel_anothers(self):
        async def scenario():
            t_a = asyncio.ensure_future(self.kernel.run("slow", organization_id="org-a"))
            t_b = asyncio.ensure_future(self.kernel.run("echo still-fine", organization_id="org-b"))
            await asyncio.sleep(0.01)
            t_a.cancel()
            b_result = await t_b
            try:
                await t_a
            except asyncio.CancelledError:
                pass
            return b_result

        b_result = _run(scenario())
        assert b_result.success
        assert "still-fine" in b_result.output

    def test_deliberation_only_bids_from_visible_agents(self):
        # Deliberation.vote() used to call kernel.all_agents() — another
        # org's agent could bid on (and win) a request it should never
        # even see, let alone execute.
        from app.agents.deliberation import Deliberation
        delib = Deliberation()
        result = _run(delib.vote("owned_agent", self.kernel, org_id="org-b"))
        assert result.winner != "owned_agent"


# ──────────────────────────────────────────────────────────────────────────────
# EvolutionEngine
# ──────────────────────────────────────────────────────────────────────────────

class TestEvolutionEngine:
    def _engine(self, mem):
        modifier = MagicMock()
        reloader = MagicMock()
        return EvolutionEngine(mem, modifier, reloader)

    def test_analyze_empty_memory(self):
        mem    = _make_memory()
        engine = self._engine(mem)
        report = engine.analyze()
        assert report.status == "stable"
        assert report.candidates == []

    def test_analyze_detects_underperformer(self, tmp_path):
        mem = _make_memory()
        # Need 5+ calls for min_calls threshold; 20% success rate
        for _ in range(4):
            mem._records.append(ExecutionRecord(
                agent="analyze", input="x", args="", success=False, duration_ms=10))
        mem._records.append(ExecutionRecord(
            agent="analyze", input="x", args="", success=True, duration_ms=10))

        engine = self._engine(mem)
        # analyze_agent.py exists in builtin dir, so _agent_file will find it
        report = engine.analyze()
        # analyze has success rate 20% < threshold 70%
        # It should appear in candidates since the file exists
        candidate_names = [c.name for c in report.candidates]
        assert "analyze" in candidate_names

    def test_cooldown_prevents_double_evolve(self):
        mem    = _make_memory()
        engine = self._engine(mem)
        engine._last_run = time.time()   # simulate recent run

        report = _run(engine.evolve())
        assert report.status == "cooldown"
        assert report.errors

    def test_evolve_stable_when_no_candidates(self):
        mem    = _make_memory()
        engine = self._engine(mem)
        engine._last_run = 0.0           # cooldown cleared

        report = _run(engine.evolve())
        assert report.status == "stable"
        assert report.evolved == []

    def test_last_report_initially_none(self):
        mem    = _make_memory()
        engine = self._engine(mem)
        assert engine.last_report() is None

    def test_report_to_dict(self):
        report = EvolutionReport(status="stable")
        d = report.to_dict()
        assert d["status"] == "stable"
        assert "candidates" in d
        assert "evolved" in d

    def _underperformer_records(self):
        # "analyze" maps to a real file (app/agents/builtin/analyze_agent.py)
        # so it survives the _agent_file() existence check downstream of
        # the owner_of filter — same name test_analyze_detects_underperformer
        # above relies on.
        return [
            ExecutionRecord(agent="analyze", input="x", args="", success=False, duration_ms=10)
            for _ in range(4)
        ] + [ExecutionRecord(agent="analyze", input="x", args="", success=True, duration_ms=10)]

    def test_owner_of_filters_out_other_orgs_underperformer(self):
        # Agent Execution Isolation: self-generated agents live in the same
        # app/agents/builtin/ directory as real built-ins (see
        # AutonomyEngine.generate_agent), so without an ownership check
        # here, org-b calling evolve() could get org-a's underperforming
        # agent rewritten by the LLM using org-b's token budget, without
        # org-a's knowledge.
        mem = _make_memory()
        mem._records += self._underperformer_records()
        modifier = MagicMock()
        reloader = MagicMock()
        engine = EvolutionEngine(mem, modifier, reloader, owner_of=lambda name: "org-a")

        other_org_report = engine.analyze(org_id="org-b")
        assert "analyze" not in [c.name for c in other_org_report.candidates]

        owner_report = engine.analyze(org_id="org-a")
        assert "analyze" in [c.name for c in owner_report.candidates]

    def test_owner_of_never_blocks_builtin_underperformer(self):
        # owner_of returning None means "built-in" — shared self-improvement
        # target regardless of which org (or no org at all) triggered the
        # cycle. That's existing, intended behavior, not a regression.
        mem = _make_memory()
        mem._records += self._underperformer_records()
        modifier = MagicMock()
        reloader = MagicMock()
        engine = EvolutionEngine(mem, modifier, reloader, owner_of=lambda name: None)

        for org in (None, "org-a", "org-b"):
            report = engine.analyze(org_id=org)
            assert "analyze" in [c.name for c in report.candidates]


# ──────────────────────────────────────────────────────────────────────────────
# Integration: plan_and_run
# ──────────────────────────────────────────────────────────────────────────────

class TestPlanAndRun:
    def setup_method(self):
        self.kernel = _make_kernel()
        self.kernel.register_agent(EchoAgent())
        self.kernel._parser.update_agents(["echo", "plan"])

    def test_plan_and_run_no_plan_agent(self):
        # Without a plan agent, plan_and_run should still return a result dict
        result = _run(self.kernel.plan_and_run("echo something"))
        assert "results" in result
        assert "success" in result

    def test_plan_and_run_with_tasks(self):
        # Inject a mock plan agent that returns tasks
        class MockPlan(EvolvableAgent):
            name = "plan"
            description = "test"
            group = "test"
            async def execute(self, ctx):
                return AgentResult.ok("plan", "planned",
                                      data={"tasks": ["echo step1", "echo step2"]})

        self.kernel.register_agent(MockPlan())
        result = _run(self.kernel.plan_and_run("do something"))
        assert "plan" in result
        assert "results" in result
        assert len(result["results"]) == 2


# ──────────────────────────────────────────────────────────────────────────────
# AutonomyEngine — self._suggestions is a single kernel-wide list shared by
# every org's suggest_improvements() calls; generate_agent() writes into the
# same app/agents/builtin/ directory used by real built-ins.
# ──────────────────────────────────────────────────────────────────────────────

class TestAutonomyEngineOrgScoping:
    def _engine(self, api_key="fake-key-for-test"):
        from app.agents.autonomy import AutonomyEngine
        engine = AutonomyEngine.__new__(AutonomyEngine)
        engine._kernel      = None
        engine._suggestions = []
        engine._api_key     = api_key
        return engine

    def test_generate_agent_without_org_id_is_rejected_before_any_write(self):
        # Guards against the pre-fix behavior: a caller with no verified
        # org membership had its generated agent registered as owner=None
        # (a protected built-in, invocable by every tenant). Checked before
        # any file I/O or LLM call — engine._kernel is None here on purpose,
        # so a bug that reached that code would crash the test loudly.
        engine = self._engine()
        result = _run(engine.generate_agent("does anything", org_id=None))
        assert result["status"] == "error"
        assert "organization" in result["error"]

    def test_generate_agent_with_no_api_key_fails_before_org_check(self):
        # Existing precedence preserved: missing API key is still reported
        # as its own distinct error, not masked by the new org check.
        engine = self._engine(api_key="")
        result = _run(engine.generate_agent("does anything", org_id="org-a"))
        assert result["status"] == "error"
        assert "ANTHROPIC_API_KEY" in result["error"]

    def test_implement_suggestion_blocks_cross_org_index_reference(self):
        # self._suggestions is shared kernel-wide — index alone must not be
        # enough to implement (and consume) another org's suggestion.
        from app.agents.autonomy import Suggestion
        engine = self._engine()
        engine._suggestions = [Suggestion(
            index=0, title="t", description="d", agent_name="x", file="f",
            priority=0.5, organization_id="org-a",
        )]
        result = _run(engine.implement_suggestion(0, org_id="org-b"))
        assert result["status"] == "error"
        assert "No suggestion" in result["error"]

    def test_owner_can_reference_its_own_suggestion_index(self):
        from app.agents.autonomy import Suggestion
        engine = self._engine(api_key="")   # force the API-key error path,
        engine._suggestions = [Suggestion(  # so this stays a safe no-write test
            index=0, title="t", description="d", agent_name="x", file="f",
            priority=0.5, organization_id="org-a",
        )]
        result = _run(engine.implement_suggestion(0, org_id="org-a"))
        # Reaches generate_agent() (proving the org match found the
        # suggestion) and fails there on the missing API key, not on
        # "No suggestion at index".
        assert result["status"] == "error"
        assert "ANTHROPIC_API_KEY" in result["error"]

    def test_all_suggestions_scoped_to_org(self):
        from app.agents.autonomy import Suggestion
        engine = self._engine()
        engine._suggestions = [
            Suggestion(index=0, title="a", description="d", agent_name="a",
                      file="f", priority=0.5, organization_id="org-a"),
            Suggestion(index=1, title="b", description="d", agent_name="b",
                      file="f", priority=0.5, organization_id="org-b"),
        ]
        org_a_view = engine.all_suggestions(org_id="org-a")
        assert len(org_a_view) == 1
        assert org_a_view[0]["agent_name"] == "a"

    def test_pending_suggestions_scoped_to_org(self):
        from app.agents.autonomy import Suggestion
        engine = self._engine()
        engine._suggestions = [
            Suggestion(index=0, title="a", description="d", agent_name="a",
                      file="f", priority=0.5, organization_id="org-a"),
            Suggestion(index=1, title="b", description="d", agent_name="b",
                      file="f", priority=0.5, organization_id="org-b"),
        ]
        pending = engine.pending_suggestions(org_id="org-a")
        assert [s.agent_name for s in pending] == ["a"]
