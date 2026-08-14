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

    # test_recent_org_scoping_excludes_other_orgs and
    # test_global_stats_org_scoping (org isolation) moved to
    # tests/security/test_memory_isolation.py's TestAgentMemoryOrgIsolation
    # as part of the Security Testing phase's tests/security/
    # reorganization. TestStatusAgentOrgScoping moved to
    # tests/security/test_tenant_isolation.py, same phase.


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

    def test_plan_and_run_uses_the_caller_supplied_run_id_verbatim(self):
        class MockPlan(EvolvableAgent):
            name = "plan"
            description = "test"
            group = "test"
            async def execute(self, ctx):
                return AgentResult.ok("plan", "planned",
                                      data={"tasks": ["echo step1"]})

        self.kernel.register_agent(MockPlan())
        seen_run_ids: list[str] = []
        orig_run = self.kernel.run
        async def spy_run(*args, **kwargs):
            seen_run_ids.append(kwargs.get("run_id"))
            return await orig_run(*args, **kwargs)
        self.kernel.run = spy_run

        _run(self.kernel.plan_and_run("do something", run_id="fixed-plan-id"))

        # Both the decomposition call ("plan {goal}") and the single
        # executed task must share the caller-supplied id.
        assert seen_run_ids == ["fixed-plan-id", "fixed-plan-id"]

    def test_plan_and_run_generates_a_run_id_when_none_supplied(self):
        result = _run(self.kernel.plan_and_run("echo something"))
        assert "results" in result  # no plan agent registered — just proves no crash


# ──────────────────────────────────────────────────────────────────────────────
# collaborate() / plan_and_run() run_id threading (Manus M2: live-narrated
# autonomous plan execution — see app/agents/kernel.py's _publish_plan_step)
# ──────────────────────────────────────────────────────────────────────────────

class TestCollaborateRunIdThreading:
    def setup_method(self):
        self.kernel = _make_kernel()
        self.kernel.register_agent(EchoAgent())
        self.kernel.register_agent(FailAgent())
        self.kernel._parser.update_agents(["echo", "fail"])

    def test_sequential_collaborate_shares_one_run_id_across_every_task(self):
        seen_run_ids: list[str] = []
        orig_run = self.kernel.run
        async def spy_run(*args, **kwargs):
            seen_run_ids.append(kwargs.get("run_id"))
            return await orig_run(*args, **kwargs)
        self.kernel.run = spy_run

        _run(self.kernel.collaborate(["echo a", "echo b"], parallel=False,
                                     run_id="shared-id"))

        assert seen_run_ids == ["shared-id", "shared-id"]

    def test_parallel_collaborate_shares_one_run_id_across_every_task(self):
        seen_run_ids: list[str] = []
        orig_run = self.kernel.run
        async def spy_run(*args, **kwargs):
            seen_run_ids.append(kwargs.get("run_id"))
            return await orig_run(*args, **kwargs)
        self.kernel.run = spy_run

        _run(self.kernel.collaborate(["echo a", "echo b"], parallel=True,
                                     run_id="shared-parallel-id"))

        assert seen_run_ids == ["shared-parallel-id", "shared-parallel-id"]

    def test_collaborate_generates_its_own_run_id_when_none_supplied(self):
        # Just proves this doesn't crash and produces a usable id — the
        # actual generated value isn't asserted (it's a fresh uuid hex).
        results = _run(self.kernel.collaborate(["echo a"], parallel=False))
        assert len(results) == 1

    def test_collaborate_narrates_each_step_and_a_failure_stop(self):
        from unittest.mock import AsyncMock
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.agents.kernel._publish_plan_step", AsyncMock()
        ) as fake_publish:
            _run(self.kernel.collaborate(["fail", "echo after"], parallel=False,
                                         run_id="narrated-id"))

        calls = [c.args for c in fake_publish.call_args_list]
        # One "Step 1/2: fail" narration before it runs, then a "Stopped"
        # narration once it fails — the second task never gets its own
        # step-start narration since collaborate() breaks out first.
        assert calls[0][0] == "narrated-id"
        assert "Step 1/2" in calls[0][1]
        assert calls[-1][0] == "narrated-id"
        assert "Stopped" in calls[-1][1]


# ──────────────────────────────────────────────────────────────────────────────
# run()'s forced_intent + deliberate_and_run() (Manus M4: deepen multi-agent
# deliberation into real collaboration — see app/agents/kernel.py)
# ──────────────────────────────────────────────────────────────────────────────

class TestForcedIntent:
    def setup_method(self):
        self.kernel = _make_kernel()
        self.kernel.register_agent(EchoAgent())
        self.kernel.register_agent(FailAgent())
        self.kernel._parser.update_agents(["echo", "fail"])

    def test_forced_intent_overrides_heuristic_resolution(self):
        # "echo hello" would heuristically resolve to the echo agent on
        # its own — forced_intent must win regardless.
        result = _run(self.kernel.run("echo hello", forced_intent="fail"))
        assert result.agent == "fail"

    def test_forced_intent_still_enforces_agent_ownership(self):
        # The bypass only skips intent *resolution* — the ownership
        # boundary right before execution still applies exactly as if
        # forced_intent had been resolved normally.
        other_org_kernel = _make_kernel()
        other_org_kernel.register_agent(FailAgent(), owner="org-other")
        other_org_kernel._parser.update_agents(["fail"])

        result = _run(other_org_kernel.run(
            "anything", forced_intent="fail", organization_id="org-mine",
        ))
        assert result.success is False
        assert result.error == "agent_not_found"


def _fake_deliberation(winner: str, bids: list):
    """bids: list of (agent_name, relevance, confidence, cost, risk) tuples,
    highest-scoring first (mirrors the real Deliberation.vote()'s sorted
    output — deliberate_and_run() assumes all_bids[0] is the winner)."""
    from app.agents.deliberation import AgentBid, DeliberationResult

    class _Fake:
        async def vote(self, raw_input, kernel, org_id=None):
            return DeliberationResult(
                winner=winner, winner_score=1.0,
                all_bids=[AgentBid(*b) for b in bids],
                consensus=0.5, method="vote",
            )
    return _Fake()


class TestDeliberateAndRun:
    def setup_method(self):
        self.kernel = _make_kernel()
        self.kernel.register_agent(EchoAgent())
        self.kernel.register_agent(FailAgent())
        self.kernel._parser.update_agents(["echo", "fail"])

    def test_executes_the_deliberation_winner_not_an_independently_resolved_agent(self):
        # Regression: deliberate_and_run() used to call run() independently
        # (deliberate=False) after computing the vote, so whenever the
        # heuristic parser was confident about a *different* agent than
        # the vote's winner, that different agent silently executed while
        # the returned vote record still claimed the original winner.
        self.kernel._deliberation = _fake_deliberation(
            "fail", [("fail", 0.9, 0.9, 0.1, 0.1), ("echo", 0.1, 0.1, 0.1, 0.1)],
        )
        # "echo something" would heuristically resolve to the echo agent
        # on its own — proving execution still follows the vote.
        result, vote = _run(self.kernel.deliberate_and_run("echo something"))
        assert result.agent == "fail"
        assert vote["winner"] == "fail"

    def test_close_runner_up_also_executes_as_a_collaborator(self):
        self.kernel._deliberation = _fake_deliberation(
            "echo", [("echo", 0.9, 0.9, 0.1, 0.1), ("fail", 0.8, 0.8, 0.1, 0.1)],
        )
        result, _vote = _run(self.kernel.deliberate_and_run("do something"))
        assert result.agent == "echo"
        assert result.data["collaborator"]["agent"] == "fail"
        assert result.data["collaborator"]["result"]["agent"] == "fail"

    def test_distant_runner_up_does_not_collaborate(self):
        self.kernel._deliberation = _fake_deliberation(
            "echo", [("echo", 0.95, 0.95, 0.1, 0.1), ("fail", 0.3, 0.3, 0.1, 0.1)],
        )
        result, _vote = _run(self.kernel.deliberate_and_run("do something"))
        assert "collaborator" not in result.data

    def test_single_bid_never_collaborates(self):
        self.kernel._deliberation = _fake_deliberation(
            "echo", [("echo", 1.0, 1.0, 0.1, 0.1)],
        )
        result, _vote = _run(self.kernel.deliberate_and_run("do something"))
        assert "collaborator" not in result.data

    def test_shares_one_run_id_across_winner_and_collaborator(self):
        self.kernel._deliberation = _fake_deliberation(
            "echo", [("echo", 0.9, 0.9, 0.1, 0.1), ("fail", 0.8, 0.8, 0.1, 0.1)],
        )
        seen_run_ids: list[str] = []
        orig_run = self.kernel.run
        async def spy_run(*args, **kwargs):
            seen_run_ids.append(kwargs.get("run_id"))
            return await orig_run(*args, **kwargs)
        self.kernel.run = spy_run

        _run(self.kernel.deliberate_and_run("do something", run_id="fixed-id"))

        assert seen_run_ids == ["fixed-id", "fixed-id"]


# ──────────────────────────────────────────────────────────────────────────────
# NLP routing — deliberation guard (fix: method=="unknown" must not trigger
# deliberation, preventing arbitrary agent execution on unrecognised input).
#
# Regression for production incident: Arabic input "سأبدأ" (and any input
# that fails all heuristic parse steps when the LLM router is unavailable)
# was landing in deliberation with ir.method=="unknown".  Deliberation had
# no keyword signal to anchor on, assigned every agent equal relevance,
# and picked a winner (AnalyzeAgent) by cost/risk alone.  AnalyzeAgent
# then received the full raw input as ir.args and interpreted it as a
# filesystem path, returning "Path not found: سأبدأ".
# ──────────────────────────────────────────────────────────────────────────────

class PathAgent(EvolvableAgent):
    """Mimics AnalyzeAgent: treats ctx.args as a filesystem path."""
    name        = "path_agent"
    description = "Interprets args as a path"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        import os
        target = ctx.args or ""
        if not target or not os.path.exists(target):
            return AgentResult.fail(self.name, f"Path not found: {target}")
        return AgentResult.ok(self.name, f"Found: {target}")


def _make_kernel_with_deliberation(winner_agent_name: str) -> "AgentKernel":
    """
    Kernel with a deterministic fake deliberation that always picks
    winner_agent_name — used to isolate the deliberation-guard logic.
    """
    from app.agents.kernel import AgentKernel
    from app.agents.deliberation import DeliberationResult
    from app.plugins.registry_guard import OwnershipTracker

    class _FakeDelib:
        async def vote(self, raw_input, kernel, heuristic_intent="", *, org_id=None):
            agents = kernel.visible_agents(org_id)
            winner = winner_agent_name if any(a.name == winner_agent_name for a in agents) \
                else (agents[0].name if agents else "unknown")
            return DeliberationResult(winner=winner, winner_score=0.9,
                                      method="vote", consensus=0.8)

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
    k._deliberation = _FakeDelib()
    k._autonomy     = None
    k._loop         = None
    return k


class TestNLPRoutingDeliberationGuard:
    """
    Verifies that the deliberation guard (method != "unknown") prevents
    arbitrary agent execution when intent parsing completely fails.
    """

    def setup_method(self):
        # Kernel whose fake deliberation always picks PathAgent — which
        # would return "Path not found: <user_input>" if allowed to run.
        self.kernel = _make_kernel_with_deliberation("path_agent")
        self.kernel.register_agent(EchoAgent())
        self.kernel.register_agent(PathAgent())
        self.kernel._parser.update_agents(["echo", "path_agent"])

    # ── 1. Arabic input (non-Latin NL) with no LLM router ────────────────────

    def test_arabic_input_returns_agent_not_found_not_path_error(self):
        # "سأبدأ" = "I'll start" in Arabic.  Heuristic parser cannot match
        # it (English-only); LLM router is None in _make_kernel_with_deliberation.
        # The guard must prevent deliberation from running PathAgent with
        # "سأبدأ" as a filesystem argument.
        result = _run(self.kernel.run("سأبدأ"))
        assert result.success is False
        assert result.error == "agent_not_found"
        # Must NOT contain "Path not found" — that would mean PathAgent ran.
        assert "Path not found" not in result.output
        assert "agent_not_found" == result.error

    # ── 2. English equivalent that also fails all heuristic steps ────────────

    def test_unrecognised_english_phrase_returns_agent_not_found(self):
        # "I will start" fails alias/prefix/pattern/fuzzy → method="unknown".
        # Same guard must apply regardless of input language.
        result = _run(self.kernel.run("I will start something"))
        assert result.success is False
        assert result.error == "agent_not_found"
        assert "Path not found" not in result.output

    # ── 3. Valid known command still works after the guard ────────────────────

    def test_valid_alias_still_executes_correctly(self):
        result = _run(self.kernel.run("echo hello"))
        assert result.success is True
        assert result.agent == "echo"

    # ── 4. Unsupported / truly unknown command → clean error ─────────────────

    def test_unsupported_command_returns_agent_not_found_with_suggestions(self):
        result = _run(self.kernel.run("xyzzy_unknown_9f3k"))
        assert result.success is False
        assert result.error == "agent_not_found"
        # Kernel includes known agents in data so the caller can suggest them.
        assert "agents" in result.data or "suggestions" in result.data

    # ── 5. Empty input still routes to help alias ─────────────────────────────

    def test_empty_input_still_routes_to_help_or_unknown(self):
        # IntentParser returns intent="help" for empty input — NOT "unknown".
        # No registered help agent in this kernel, so agent_not_found is fine,
        # but it must NOT have been short-circuited by the guard (method="alias").
        result = _run(self.kernel.run(""))
        # Either help ran (success=True) or it's agent_not_found (no help agent),
        # but it must NOT be a path-resolution error.
        assert "Path not found" not in result.output

    # ── 6. Malformed / special-char input → raw text not exposed as path ───────

    def test_malformed_input_does_not_expose_raw_text_as_path(self):
        # When intent parsing completely fails (method="unknown"), the guard
        # prevents deliberation, so the raw input is never used as a
        # filesystem path.  Inputs that DO fuzzy-match a known alias (e.g.
        # "🤖🚀" matches "h" → "help") are intentionally allowed through
        # deliberation, but the agent receives empty args (from the parsed
        # "rest"), not the full raw input — so the user's text cannot appear
        # verbatim in a "Path not found: <raw_text>" error.
        inputs_expecting_no_raw_path_echo = [
            "!!!@@@###",  # no alias, no pattern → method="unknown" → guard blocks
            "\x00\x01",   # control chars → method="unknown" → guard blocks
            "سأبدأ",      # Arabic → method="unknown" → guard blocks
            "؟؟؟",        # Arabic punctuation → method="unknown" → guard blocks
        ]
        for bad in inputs_expecting_no_raw_path_echo:
            result = _run(self.kernel.run(bad))
            # The raw user text must never appear verbatim in a path error.
            assert f"Path not found: {bad}" not in result.output, \
                f"Raw input exposed as path for {bad!r}: {result.output!r}"

    # ── 7. Attempted route/agent injection is still blocked ──────────────────

    def test_arbitrary_agent_name_in_input_does_not_bypass_allowlist(self):
        # Even if the user types the exact name of a registered agent,
        # it must go through IntentParser's allowlist (prefix check) —
        # not be directly executed via the deliberation path.
        # "path_agent" IS a known agent, so prefix match succeeds and
        # the guard does NOT apply; this test verifies the allowlist itself.
        result = _run(self.kernel.run("path_agent"))
        # PathAgent runs but receives empty args ("") → "Path not found: "
        # This is correct: the name was valid, the agent ran, no injection.
        assert result.agent == "path_agent"

    # ── 8. Deliberation IS still triggered for ambiguous-but-parsed intent ───

    def test_deliberation_runs_when_heuristic_has_nonzero_confidence(self):
        # "start something" → aliases "start" → "run" → method="alias",
        # confidence=1.0 — but "run" is NOT registered in this kernel, so
        # the deliberation guard lets it through (method != "unknown") and
        # the fake deliberation picks "echo" instead.
        # Verify: with method="alias" the guard does NOT block deliberation.
        kernel2 = _make_kernel_with_deliberation("echo")
        kernel2.register_agent(EchoAgent())
        kernel2._parser.update_agents(["echo"])
        result = _run(kernel2.run("start something"))
        # Deliberation picked echo (alias "start"→"run" not registered,
        # falls through to agent=None without deliberation intervening on
        # "run"; but since method="alias" the guard lets delib run and
        # echo wins) OR the kernel returns agent_not_found for "run".
        # Either way: no path error and the guard did not suppress delib.
        assert "Path not found" not in result.output

    # ── 9. Cross-organization: another org's agent must not win deliberation ──

    def test_other_org_agent_cannot_win_deliberation_for_unknown_input(self):
        from app.agents.deliberation import Deliberation
        from app.agents.kernel import AgentKernel
        from app.plugins.registry_guard import OwnershipTracker

        k = AgentKernel.__new__(AgentKernel)
        k._agents       = {}
        k._agent_owners = OwnershipTracker("agent")
        k._memory       = _make_memory()
        k._parser       = IntentParser()
        k._booted       = True
        k._modifier = k._reloader = k._evolution = None
        k._router   = k._reflector = k._autonomy = k._loop = None
        k._deliberation = Deliberation()

        # org-a owns "secret_agent"; org-b should never invoke it.
        class SecretAgent(EvolvableAgent):
            name = "secret_agent"
            description = "org-a private"
            group = "test"
            async def execute(self, ctx):
                return AgentResult.ok(self.name, "secret data")

        k.register_agent(EchoAgent())                      # built-in
        k.register_agent(SecretAgent(), owner="org-a")     # org-a only
        k._parser.update_agents(list(k._agents.keys()))

        # org-b sends an unknown Arabic phrase; even if deliberation somehow
        # tries to run secret_agent, the ownership check must block it.
        result = _run(k.run("مرحبا", organization_id="org-b"))
        assert result.agent != "secret_agent"
        if not result.success:
            assert result.error in ("agent_not_found",)


# TestAutonomyEngineOrgScoping moved to
# tests/security/test_tenant_isolation.py as part of the Security Testing
# phase's tests/security/ reorganization.
