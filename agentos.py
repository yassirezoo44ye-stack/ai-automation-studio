#!/usr/bin/env python3
"""
AgentOS — Production CLI

Commands:
  run        <input>               Execute a natural-language command
  plan       <goal>                Build an execution plan (analyze-only)
  analyze    <target>              Analyze agents / project / performance
  reflect                          Trigger a self-reflection cycle
  generate   <description>         Write a new agent via AI
  validate   <agent|all>           Run health checks for one or all agents
  repair                           Run the self-healing build system
  doctor                           Full environment + dependency diagnostics
  status                           System overview (agents, memory, services)
  memory     [search <query>]      Show or search layered memory
  agents     [list|health]         List agents or run health checks
  logs       [n=50]                Tail the AgentOS execution log
  metrics                          Print current metrics snapshot
  rollback   <plan_id>             Execute rollback plan for a given plan
  evolve     [run|analyze]         Trigger or analyze agent evolution
  collaborate <task1> <task2>...   Run multiple tasks in sequence
  deliberate <input>               Run with explicit multi-agent voting
  suggest    [n=3]                 Propose new agent ideas
  implement  <index>               Implement a suggestion by index
  loop       [--cycles=3]          Run autonomous improvement cycles
  help                             Show this help

Usage examples:
  python agentos.py status
  python agentos.py plan "build and deploy the API"
  python agentos.py generate "an agent that checks port availability"
  python agentos.py doctor
  python agentos.py memory search "deploy errors"
  python agentos.py agents health
  python agentos.py metrics
"""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap

# ── Force UTF-8 on Windows cp1252 terminals ────────────────────────────────────
if hasattr(sys.stdout, "buffer") and (
    not sys.stdout.encoding or sys.stdout.encoding.lower() not in ("utf-8", "utf8")
):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ── Colour helpers (no external dep) ─────────────────────────────────────────

_USE_COLOR = sys.stdout.isatty()
C = {
    "reset" : "\x1b[0m" if _USE_COLOR else "",
    "bold"  : "\x1b[1m" if _USE_COLOR else "",
    "green" : "\x1b[32m" if _USE_COLOR else "",
    "yellow": "\x1b[33m" if _USE_COLOR else "",
    "red"   : "\x1b[31m" if _USE_COLOR else "",
    "cyan"  : "\x1b[36m" if _USE_COLOR else "",
    "grey"  : "\x1b[90m" if _USE_COLOR else "",
}

def clr(code: str, text: str) -> str:
    return f"{C[code]}{text}{C['reset']}"

def h(text: str) -> str:
    return clr("cyan", clr("bold", f"\n── {text} "))

def ok(text: str) -> str:
    return f"  {clr('green', '✅')} {text}"

def warn(text: str) -> str:
    return f"  {clr('yellow', '⚠️ ')} {text}"

def err(text: str) -> str:
    return f"  {clr('red', '❌')} {text}"

def _print_json(data) -> None:
    print(json.dumps(data, indent=2, default=str))


# ── Kernel bootstrap ──────────────────────────────────────────────────────────

def _get_kernel():
    from app.agents.kernel import get_agent_kernel
    return get_agent_kernel()


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_run(args: list[str]) -> None:
    if not args:
        print(err("Usage: agentos.py run <natural language input>"))
        return
    inp    = " ".join(args)
    kernel = _get_kernel()
    print(f"  {clr('grey', 'Running:')} {inp}")
    result = await kernel.run(inp, caller="cli")
    icon   = ok("") if result.success else err("")
    print(f"{icon.strip()} {result.output}")
    if result.data:
        _print_json(result.data)


async def cmd_plan(args: list[str]) -> None:
    goal = " ".join(args)
    if not goal:
        print(err("Usage: agentos.py plan <goal>"))
        return
    from app.planning.engine import get_planning_engine
    kernel = _get_kernel()
    engine = get_planning_engine()
    plan   = engine.plan(goal, caller="cli", agents=kernel._agents)
    p      = plan.to_dict()
    print(h("EXECUTION PLAN"))
    print(f"  Plan ID:   {p['plan_id']}")
    print(f"  Risk:      {clr('yellow' if p['risk_level'] != 'low' else 'green', p['risk_level'].upper())}")
    print(f"  Tasks:     {len(p['tasks'])}")
    print(f"  Cost est.: ${p['total_cost_usd']:.6f}")
    print(f"  Approval:  {'required' if p['requires_approval'] else 'not required'}")
    for i, t in enumerate(p["tasks"], 1):
        print(f"\n  Task {i}: {clr('bold', t['description'][:80])}")
        print(f"    Agent: {t['agent_name'] or 'unassigned'}  |  Risk: {t['risk_level']}")
        if t.get("rollback_action"):
            print(f"    Rollback: {t['rollback_action']}")
    if p["warnings"]:
        print(h("WARNINGS"))
        for w in p["warnings"]:
            print(warn(w))
    if p["permission_errors"]:
        print(h("PERMISSION ERRORS"))
        for e in p["permission_errors"]:
            print(err(e))


async def cmd_analyze(args: list[str]) -> None:
    target = " ".join(args) if args else "performance"
    kernel = _get_kernel()
    result = await kernel.run(f"analyze {target}", caller="cli")
    print(f"{ok('') if result.success else err('')} {result.output}")


async def cmd_reflect(_: list[str]) -> None:
    from app.agents.reflection import get_reflector
    from app.agents.memory     import get_memory
    from app.agents.evolution  import EvolutionEngine

    memory = get_memory()
    # Fire a manual reflection
    ref = get_reflector()
    # Access the last recorded result from memory
    records = memory.recent(1)
    if records:
        from app.agents.base import AgentResult
        last = records[-1]
        dummy = AgentResult(agent=last.agent, success=last.success, output="manual-reflect")
        ref.reflect(dummy, memory, None)
        print(ok("Reflection queued (check /api/agentos/reflections for output)"))
    else:
        print(warn("No execution history to reflect on"))


async def cmd_generate(args: list[str]) -> None:
    desc = " ".join(args)
    if not desc:
        print(err("Usage: agentos.py generate <description>"))
        return
    kernel = _get_kernel()
    result = await kernel.generate_agent(desc)
    _print_json(result)


async def cmd_validate(args: list[str]) -> None:
    target = args[0] if args else "all"
    kernel = _get_kernel()
    agents = kernel.all_agents() if target == "all" else [
        a for a in kernel.all_agents() if a.name == target
    ]
    print(h("AGENT VALIDATION"))
    for agent in agents:
        h_result = agent.health_check()
        icon     = ok("") if h_result.status.value == "healthy" else warn("")
        print(f"{icon.strip()} {clr('bold', agent.name)}: {h_result.status.value}  {h_result.message}")


async def cmd_repair(_: list[str]) -> None:
    import subprocess
    r = subprocess.run(["node", "tools/repair-engine.cjs"], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print(err(r.stderr))


async def cmd_doctor(_: list[str]) -> None:
    import subprocess
    r = subprocess.run(["node", "tools/doctor.cjs"], text=True)
    sys.exit(r.returncode)


async def cmd_status(_: list[str]) -> None:
    from app.services.registry  import get_service_registry
    from app.core.observability.metrics import get_metrics

    kernel   = _get_kernel()
    status   = kernel.status()
    metrics  = get_metrics().snapshot()
    services = get_service_registry().status()

    print(h("AGENTOS STATUS"))
    print(f"  Agents:   {status['agents']} registered")
    print(f"  Memory:   {status['memory_count']} execution records")
    print(f"  LLM:      {'available' if status['llm_available'] else 'not configured'}")
    print(f"  Booted:   {status['booted']}")

    print(h("BACKGROUND SERVICES"))
    for svc in services:
        icon  = ok("") if svc["state"] == "running" else warn("")
        print(f"{icon.strip()} {svc['name']}: {svc['state']}  (uptime {svc['uptime_s']:.0f}s)")

    print(h("METRICS"))
    for k, v in metrics.get("counters", {}).items():
        if v > 0:
            print(f"  {k}: {v}")


async def cmd_memory(args: list[str]) -> None:
    from app.memory.layered import get_layered_memory
    mem = get_layered_memory()
    if args and args[0] == "search":
        query   = " ".join(args[1:])
        results = mem.search(query, limit=20)
        print(h(f"MEMORY SEARCH: {query}"))
        for r in results:
            print(f"  [{r.kind}] {r.content[:100]}  {clr('grey', r.agent or '')}")
    else:
        n       = int(args[0]) if args and args[0].isdigit() else 20
        records = mem.recent(n)
        print(h("RECENT MEMORY"))
        for r in records:
            icon = ok("") if r.success else err("")
            print(f"{icon.strip()} [{r.kind}] {r.content[:80]}  {clr('grey', r.agent or '')}")
    print(f"\n  {clr('grey', f'Short-term: {mem.stats[\"short_term\"]}  Long-term: {mem.stats[\"long_term\"]}')}")


async def cmd_agents(args: list[str]) -> None:
    kernel = _get_kernel()
    mode   = args[0] if args else "list"
    print(h("AGENTS"))
    for agent in kernel.all_agents():
        if mode == "health":
            h_result = agent.health_check()
            icon     = ok("") if h_result.status.value == "healthy" else warn("")
            print(f"{icon.strip()} {clr('bold', agent.name):<20} {agent.description[:50]}")
        else:
            print(f"  {clr('bold', agent.name):<20} [{agent.group}]  {agent.description[:50]}")


async def cmd_logs(args: list[str]) -> None:
    import os
    n        = int(args[0]) if args and args[0].isdigit() else 50
    log_file = os.path.join(os.path.dirname(__file__), "logs", "runtime.log")
    if not os.path.exists(log_file):
        print(warn("No runtime log found — run the server first"))
        return
    with open(log_file) as f:
        lines = f.readlines()
    print(h(f"LAST {n} LOG LINES"))
    for line in lines[-n:]:
        line = line.rstrip()
        if '"level":"ERROR"' in line or '"level":"CRITICAL"' in line:
            print(f"  {clr('red', line[:160])}")
        elif '"level":"WARN"' in line:
            print(f"  {clr('yellow', line[:160])}")
        else:
            print(f"  {clr('grey', line[:160])}")


async def cmd_metrics(_: list[str]) -> None:
    from app.core.observability.metrics import get_metrics
    snap = get_metrics().snapshot()
    print(h("METRICS SNAPSHOT"))
    print(f"  Uptime: {snap['uptime_s']}s")
    print(h("Counters"))
    for k, v in snap["counters"].items():
        print(f"  {k}: {v}")
    print(h("Gauges"))
    for k, v in snap["gauges"].items():
        print(f"  {k}: {v}")
    print(h("Histograms"))
    for k, v in snap["histograms"].items():
        print(f"  {k}: avg={v['avg']}ms p95={v['p95']}ms count={v['count']}")


async def cmd_rollback(args: list[str]) -> None:
    if not args:
        print(err("Usage: agentos.py rollback <plan_id>"))
        return
    # Rollback is plan-specific; look up the plan_id and execute rollback steps
    plan_id = args[0]
    print(h(f"ROLLBACK PLAN: {plan_id}"))
    print(warn("Rollback execution: this triggers 'modify rollback <plan_id>' via AgentKernel"))
    kernel = _get_kernel()
    result = await kernel.run(f"modify rollback {plan_id}", caller="cli-rollback")
    print(ok("Done") if result.success else err(result.output))


async def cmd_evolve(args: list[str]) -> None:
    mode   = args[0] if args else "run"
    kernel = _get_kernel()
    if mode == "analyze":
        _print_json(kernel.evolution_analysis())
    else:
        _print_json(await kernel.evolve())


async def cmd_collaborate(args: list[str]) -> None:
    if not args:
        print(err("Usage: agentos.py collaborate <task1> <task2> ..."))
        return
    kernel  = _get_kernel()
    results = await kernel.collaborate(args, caller="cli")
    for r in results:
        icon = ok("") if r.success else err("")
        print(f"{icon.strip()} {r.agent}: {r.output[:80]}")


async def cmd_deliberate(args: list[str]) -> None:
    if not args:
        print(err("Usage: agentos.py deliberate <input>"))
        return
    kernel = _get_kernel()
    result, vote = await kernel.deliberate_and_run(" ".join(args), caller="cli")
    icon = ok("") if result.success else err("")
    print(f"{icon.strip()} {result.output}")
    print(h("DELIBERATION"))
    _print_json(vote)


async def cmd_suggest(args: list[str]) -> None:
    n = int(args[0]) if args and args[0].isdigit() else 3
    kernel = _get_kernel()
    suggestions = await kernel.suggest(n)
    print(h("SUGGESTIONS"))
    for s in suggestions:
        print(f"  [{s.get('index', '?')}] {clr('bold', s.get('title', '?'))}: {s.get('description', '')[:80]}")


async def cmd_implement(args: list[str]) -> None:
    if not args:
        print(err("Usage: agentos.py implement <index>"))
        return
    kernel = _get_kernel()
    _print_json(await kernel.implement(int(args[0])))


async def cmd_loop(args: list[str]) -> None:
    cycles = 3
    for a in args:
        if a.startswith("--cycles="):
            try:
                cycles = int(a.split("=")[1])
            except ValueError:
                pass
    kernel  = _get_kernel()
    results = await kernel.autonomous_loop(cycles)
    _print_json(results)


def cmd_help(_: list[str]) -> None:
    print(__doc__)


# ── Dispatch ──────────────────────────────────────────────────────────────────

_COMMANDS: dict[str, any] = {
    "run"        : cmd_run,
    "plan"       : cmd_plan,
    "analyze"    : cmd_analyze,
    "reflect"    : cmd_reflect,
    "generate"   : cmd_generate,
    "validate"   : cmd_validate,
    "repair"     : cmd_repair,
    "doctor"     : cmd_doctor,
    "status"     : cmd_status,
    "memory"     : cmd_memory,
    "agents"     : cmd_agents,
    "logs"       : cmd_logs,
    "metrics"    : cmd_metrics,
    "rollback"   : cmd_rollback,
    "evolve"     : cmd_evolve,
    "collaborate": cmd_collaborate,
    "deliberate" : cmd_deliberate,
    "suggest"    : cmd_suggest,
    "implement"  : cmd_implement,
    "loop"       : cmd_loop,
    "help"       : cmd_help,
    "--help"     : cmd_help,
    "-h"         : cmd_help,
}


async def _main() -> None:
    argv = sys.argv[1:]
    if not argv:
        cmd_help([])
        return

    cmd  = argv[0].lower()
    rest = argv[1:]

    handler = _COMMANDS.get(cmd)

    if handler is None:
        # Fall back to natural-language run
        await cmd_run(argv)
        return

    if asyncio.iscoroutinefunction(handler):
        await handler(rest)
    else:
        handler(rest)


if __name__ == "__main__":
    asyncio.run(_main())
