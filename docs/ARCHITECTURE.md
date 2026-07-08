# AI Automation Studio — Architecture Guide

> **Version**: 2.0.0 · **Status**: Production  
> Autonomous Development OS — modular, fault-tolerant, observable, secure, extensible.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Layer Architecture](#2-layer-architecture)
3. [Agent System](#3-agent-system)
4. [Planning Engine](#4-planning-engine)
5. [Execution Engine](#5-execution-engine)
6. [Self-Healing](#6-self-healing)
7. [Code Generation Pipeline](#7-code-generation-pipeline)
8. [Security Model](#8-security-model)
9. [Memory System](#9-memory-system)
10. [Observability](#10-observability)
11. [Background Services](#11-background-services)
12. [REST API](#12-rest-api)
13. [CLI](#13-cli)
14. [Agent Lifecycle](#14-agent-lifecycle)
15. [Plugin Guide](#15-plugin-guide)
16. [Deployment Guide](#16-deployment-guide)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    AI Automation Studio                                 │
│                                                                         │
│  React 19 + Vite Frontend  ◄──── REST + SSE ────►  FastAPI Backend     │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Autonomous Development OS                      │  │
│  │                                                                   │  │
│  │  Planning ──► Execution ──► Reflection ──► Evolution             │  │
│  │                   ▲                                               │  │
│  │              AgentKernel                                          │  │
│  │              (10 built-in agents + hot-reload)                    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  PostgreSQL (users, tasks, usage) · Render (hosting) · Stripe (billing)│
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Properties

| Property | How |
|---|---|
| **Modular** | Every capability is an agent; every concern is a layer |
| **Fault-tolerant** | Self-healing build, agent-level retry, background health monitor |
| **Observable** | MetricsRegistry, HealthRegistry, Tracer, structured logs |
| **Secure** | PolicyEngine, CodeGen pipeline with 6 security stages, sandbox |
| **Extensible** | Plugin agents, hot-reload, AutonomyEngine generates new agents at runtime |

---

## 2. Layer Architecture

```
┌──────────────────────────────────────────────────┐
│  Presentation   React 19 / Vite / Electron        │
├──────────────────────────────────────────────────┤
│  API            FastAPI routers (/api/*)           │
├──────────────────────────────────────────────────┤
│  Application    AgentKernel orchestrator           │
├──────────────────────────────────────────────────┤
│  Planning       PlanningEngine + TaskPlanner       │
├──────────────────────────────────────────────────┤
│  Agent          EvolvableAgent + 10 built-in       │
├──────────────────────────────────────────────────┤
│  LLM            LLMRouter (Claude Haiku)           │
├──────────────────────────────────────────────────┤
│  Memory         LayeredMemory (short + long + LT)  │
├──────────────────────────────────────────────────┤
│  Execution      UnifiedExecutionEngine + drivers   │
├──────────────────────────────────────────────────┤
│  Reflection     SelfReflector + EvolutionEngine    │
├──────────────────────────────────────────────────┤
│  Evolution      AutonomyEngine + CodeGenPipeline   │
├──────────────────────────────────────────────────┤
│  Infrastructure ServiceRegistry + ObservabilityLyr │
└──────────────────────────────────────────────────┘
```

Each layer is isolated: upper layers call down; lower layers never call up.

---

## 3. Agent System

### Interface

Every agent must extend `EvolvableAgent` and implement:

```python
class MyAgent(EvolvableAgent):
    name        = "my_agent"          # unique identifier
    description = "Does something"    # shown in help
    group       = "utility"           # used for grouping
    version     = "1.0.0"

    # Required
    async def execute(self, ctx: AgentContext) -> AgentResult: ...

    # Optional (all have safe defaults)
    @property
    def metadata(self)     -> AgentMetadata: ...
    @property
    def capabilities(self) -> list[AgentCapability]: ...
    @property
    def permissions(self)  -> AgentPermissions: ...

    def validate(self, ctx)       -> ValidationResult: ...
    def estimate_cost(self, ctx)  -> CostEstimate: ...
    def health_check(self)        -> AgentHealth: ...
    def performance_hint(self)    -> dict: ...
```

### Execution flow

```
kernel.run(input)
    │
    ├─► IntentParser.parse()        heuristic, <1ms
    ├─► LLMRouter.route()           if confidence < 0.6
    ├─► Deliberation.vote()         if still ambiguous
    ├─► agent.validate(ctx)         pre-flight guard
    ├─► agent.execute(ctx)          core logic
    ├─► AgentMemory.add()           record outcome
    └─► SelfReflector.reflect()     async, non-blocking
```

### Built-in Agents

| Agent | Group | Capability |
|---|---|---|
| `run` | execution | Runs projects via UnifiedExecutionEngine |
| `build` | build | Detects and runs build system |
| `deploy` | deploy | zip / Render / Docker deploy |
| `analyze` | analysis | Code, agent, performance analysis |
| `modify` | evolution | Wraps SelfModifyingEngine |
| `evolve` | evolution | Triggers EvolutionEngine |
| `plan` | planning | Decomposes goals into subtasks |
| `status` | monitoring | System overview with ASCII bars |
| `help` | utility | Lists all agents with descriptions |
| `modify` | evolution | Creates/patches/rollbacks agents |

### Dynamic loading

```
app/agents/builtin/   — always loaded at boot
agents/               — user plugin directory, scanned at boot + hot-reload

Loader strategies:
  1. register(kernel) function
  2. agent = MyAgent()  variable
  3. class inheriting EvolvableAgent
```

---

## 4. Planning Engine

### Pipeline

```
goal
  │
  ├─► TaskPlanner.plan()          decompose into PlannedTask list
  ├─► _assign_agent()             map task_type → agent_name
  ├─► _estimate()                 call agent.estimate_cost()
  ├─► _task_risk()                LOW/MEDIUM/HIGH/CRITICAL
  ├─► _aggregate_risk()           worst-case across tasks
  ├─► _validate_permissions()     check agent.permissions vs task actions
  ├─► _build_warnings()           unassigned tasks, cost overrun
  ├─► _rollback_action()          per-task inverse action
  └─► RichPlan                    returned (never auto-executed)
```

### Risk levels

| Level | Triggers |
|---|---|
| `low` | Read-only operations |
| `medium` | Write / create / modify |
| `high` | Delete / remove / wipe |
| `critical` | "production" / "prod" / "live" |

Critical-risk plans **always** require human approval before execution.

### Parallel groups

Tasks with no unresolved dependencies are grouped for parallel execution.
The planner returns `parallel_groups: [[id1, id2], [id3]]` — each group
can be executed with `asyncio.gather()`.

---

## 5. Execution Engine

```
ExecutionPlan
  │
  ├─► [group 0] parallel: asyncio.gather(task1, task2)
  ├─► [group 1] after all of group 0: asyncio.gather(task3)
  └─► aggregate results → partial_success / full_success

Per-task:
  ├─► agent.validate(ctx)
  ├─► agent.run(ctx)             with timeout from agent.permissions.max_execution_seconds
  ├─► retry (up to 3x on transient error)
  └─► on failure: execute rollback_action, stop pipeline
```

---

## 6. Self-Healing

Automatic detection and repair:

| Problem | Detected by | Auto-repair |
|---|---|---|
| Missing packages | `DependencyMonitorService` | `repair-engine.cjs` install strategies |
| Permission error | `RepairEngine.classify()` | `repairPermissions()` + fallback cache |
| Broken environment | `tools/env-checker.cjs` | `tools/recovery-manager.cjs` pipeline |
| Agent underperforming | `PerformanceOptimizerService` | Triggers `EvolutionEngine.evolve()` |
| Unhealthy probe | `HealthMonitorService` | Logs root-cause; alerts via metrics |

**Never silent**: every repair attempt is logged to `logs/errors.log` with:
- `rootCause` — what failed
- `repairAttempted` — what was tried
- `repairResult` — success or failure
- `nextAction` — manual steps if repair failed

---

## 7. Code Generation Pipeline

Generated code passes **6 sequential gates** before it can be registered:

```
generate() — LLM writes source
    │
    ▼
format     — strip markdown fences, dedent, normalize
    │
    ▼
lint       — ast.parse() syntax check
    │
    ▼
static_analysis — banned patterns:
                  exec(), eval(), __import__(), os.system()
                  shell=True subprocesses, ctypes, requests/httpx/aiohttp
    │
    ▼
security_scan — secret literals, path traversal (../),
                core-module name shadowing (kernel, memory, base …)
    │
    ▼
unit_test  — pluggable test runner (skipped if not registered)
    │
    ▼
approval_gate — status = AWAITING_APPROVAL
                must call pipeline.approve(run_id, approver="admin")
                before the code can be registered as an agent
```

Code is **never auto-executed**. It only runs when:
1. All 6 gates pass.
2. A human calls `POST /api/diagnostics/codegen/{run_id}/approve`.
3. The approved code is registered via `AgentLoader.load_file()`.

---

## 8. Security Model

### Layers

1. **PolicyEngine** — protects: `.env`, `.git/`, `migrations/`, `alembic/`, `.pem`, `.key`, `id_rsa`, `id_ed25519`, `.github/workflows`, `Dockerfile.prod`, `render.yaml`

2. **AgentPermissions** — each agent declares what it can do:
   ```python
   AgentPermissions(
       can_read_filesystem    = False,
       can_write_filesystem   = False,
       can_execute_subprocess = False,
       can_call_llm           = True,
       can_access_network     = False,
       can_modify_agents      = False,
       max_execution_seconds  = 30.0,
   )
   ```

3. **CodeGen security_scan** — blocks: secrets, path traversal, banned imports.

4. **BackupManager** — ALLOWED_BACKUP allowlist; PROTECTED_PATTERNS denylist prevents modification of any source file.

5. **SecurityMonitorService** — background scanner for accidentally committed secrets.

6. **HTTP middleware** — CSP, HSTS, X-Frame-Options, global rate limiting (300 req/60s per IP).

### Secrets storage

| Secret | Location |
|---|---|
| `SESSION_SECRET` | Render env var only |
| `ANTHROPIC_API_KEY` | Render env var only |
| `STRIPE_SECRET_KEY` | Render env var only |
| `DATABASE_URL` | Render env var only |
| OAuth client secrets | Render env var only |

Never commit secrets to Git. The `SecurityMonitorService` will detect and alert.

---

## 9. Memory System

### Three layers

```
ShortTermMemory  — in-process deque (max 200 items, TTL 30 min)
     │
     └──► LayeredMemory.add() ──►  LongTermMemory  — JSON-persisted (max 5 000 items)
                                        │
                                        └──► TF-IDF semantic search
```

### Memory kinds

| Kind | Written by |
|---|---|
| `execution` | AgentKernel after every run |
| `reflection` | SelfReflector |
| `error` | Execution failures |
| `learning` | ImprovementLoop |
| `task` | TaskPlanner |

### Semantic search

```python
mem = get_layered_memory()
results = mem.search("deploy failed production", limit=10, kind="error")
```

TF-IDF scoring — no external vector DB required. Replace `_score()` with
an embedding call (e.g. `anthropic.embeddings`) for production-grade semantic recall.

---

## 10. Observability

### MetricsRegistry

```python
m = get_metrics()
m.counter("my_counter", "desc").inc()
m.gauge("active_agents").set(10)
m.histogram("request_ms").observe(42.5)
snap = m.snapshot()           # JSON
text = m.prometheus_text()    # Prometheus scrape format
```

**Pre-wired metrics:**

| Metric | Type | Description |
|---|---|---|
| `agentos_runs_total` | counter | Total kernel.run() calls |
| `agentos_runs_success` | counter | Successful executions |
| `agentos_runs_failed` | counter | Failed executions |
| `agentos_duration_ms` | histogram | Execution latency |
| `agentos_plans_total` | counter | Planning engine invocations |
| `agentos_evolution_cycles` | counter | Evolution cycles |
| `agentos_codegen_total` | counter | Code gen pipeline runs |
| `agentos_agents_active` | gauge | Registered agents |
| `agentos_services_running` | gauge | Running background services |
| `http_requests_total` | counter | HTTP requests |
| `http_request_duration_ms` | histogram | HTTP latency |

### HealthRegistry

```python
hr = get_health_registry()
hr.register("my_service", probe_fn, critical=True, timeout_s=5.0)
report = await hr.check_all()  # { status, probes[] }
```

Aggregate rules:
- ≥ 2 critical probes UNHEALTHY → overall `unhealthy`
- 1 critical probe UNHEALTHY → overall `degraded`
- Any non-critical UNHEALTHY → overall `degraded`
- All passing → `healthy`

### Tracer

```python
tracer = get_tracer()
with tracer.start_span("agent.run", service="agentos") as span:
    span.set_tag("agent", "build")
    span.add_event("started")
    result = await agent.run(ctx)

recent = tracer.recent(100)   # last 100 finished spans
active = tracer.active()      # in-flight spans
```

---

## 11. Background Services

| Service | Interval | Purpose |
|---|---|---|
| `health_monitor` | 30s | Run all health probes, update metrics |
| `dependency_monitor` | 5m | Check packages and env vars |
| `security_monitor` | 10m | Scan for leaked secrets |
| `performance_optimizer` | 2m | Flag slow/error-prone agents |
| `memory_compactor` | 1h | Prune old execution records |

### Start/stop

```python
# Programmatic
reg = get_service_registry()
reg.start("security_monitor")
reg.stop("security_monitor")
reg.start_all()
reg.stop_all()

# REST
POST /api/diagnostics/services/security_monitor/start
POST /api/diagnostics/services/security_monitor/stop
GET  /api/diagnostics/services
```

### Writing a new service

```python
from app.services.registry import BaseService

class MyService(BaseService):
    name        = "my_service"
    description = "Does something periodically"
    interval_s  = 60.0

    async def tick(self) -> None:
        # Your logic here
        pass

    async def on_start(self) -> None: ...  # optional setup
    async def on_stop(self)  -> None: ...  # optional teardown
```

Register in `app/services/registry.py` → `_register_defaults()`.

---

## 12. REST API

### AgentOS core (`/api/agentos/*`)

| Method | Path | Description |
|---|---|---|
| POST | `/run` | NL → agent execution |
| POST | `/collaborate` | Multi-task pipeline |
| POST | `/plan` | Goal decomposition + execute |
| POST | `/deliberate` | Multi-agent voting + execute |
| GET | `/status` | System overview |
| GET | `/agents` | Agent list + stats |
| GET | `/memory` | Execution history |
| GET | `/performance` | Error rates + underperformers |
| POST | `/evolve` | Trigger evolution |
| GET | `/reflections` | Reflection history |
| POST | `/generate` | Write a new agent |
| POST | `/suggest` | Propose features |
| POST | `/implement` | Implement a suggestion |
| POST | `/loop` | Autonomous improvement cycles |
| GET | `/loop/stats` | Background loop status |

### Planning (`/api/plan/*`)

| Method | Path | Description |
|---|---|---|
| POST | `/analyze` | Build plan only (no execution) |
| POST | `/execute` | Build plan + execute |
| GET | `/{plan_id}` | Retrieve a cached plan |

### Diagnostics (`/api/diagnostics/*`)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Full health probe report |
| GET | `/metrics` | Metrics JSON snapshot |
| GET | `/metrics/text` | Prometheus text format |
| GET | `/traces` | Recent distributed traces |
| GET | `/traces/active` | Active (in-flight) spans |
| GET | `/traces/{trace_id}` | Trace by ID |
| GET | `/services` | Background service status |
| POST | `/services/{name}/start` | Start a service |
| POST | `/services/{name}/stop` | Stop a service |
| GET | `/memory` | Layered memory stats + records |
| POST | `/memory/search` | Semantic search |
| GET | `/codegen` | Pending code-gen approvals |
| POST | `/codegen/{run_id}/approve` | Approve generated code |
| POST | `/codegen/{run_id}/reject` | Reject generated code |

---

## 13. CLI

```bash
python agentos.py <command> [args]
```

| Command | Description |
|---|---|
| `run <input>` | Execute a natural-language command |
| `plan <goal>` | Build and display an execution plan |
| `analyze <target>` | Analyze agents / project / performance |
| `reflect` | Trigger a self-reflection cycle |
| `generate <desc>` | Write a new agent via AI |
| `validate [agent\|all]` | Health-check one or all agents |
| `repair` | Run the self-healing build system |
| `doctor` | Full environment diagnostics |
| `status` | System overview |
| `memory [search <q>]` | Browse or search layered memory |
| `agents [list\|health]` | List agents or run health checks |
| `logs [n]` | Tail execution log |
| `metrics` | Print metrics snapshot |
| `rollback <plan_id>` | Execute rollback plan |
| `evolve [run\|analyze]` | Trigger or dry-run evolution |
| `collaborate <t1> <t2>…` | Sequential multi-task pipeline |
| `deliberate <input>` | Multi-agent voted execution |
| `suggest [n]` | Propose n new agent ideas |
| `implement <index>` | Implement a suggestion |
| `loop [--cycles=N]` | Autonomous improvement cycles |
| `help` | Show help |

---

## 14. Agent Lifecycle

```
CREATED ──► ACTIVE ──► SUSPENDED ──► DEPRECATED ──► REMOVED
               │                          │
               └──► evolution rewrites ───┘
                    (backup → rewrite → hot-reload)
```

| State | Description |
|---|---|
| `created` | Loaded but not yet activated |
| `active` | Running and accepting requests |
| `suspended` | Temporarily disabled (e.g., high error rate) |
| `deprecated` | Will be removed in next cleanup |
| `removed` | Unregistered from kernel |

Hot-reload flow:
1. `EvolutionEngine` rewrites `agents/{name}_agent.py`
2. `BackupManager.create()` saves the original
3. `HotReloader.reload_plugin()` re-imports the module
4. `AgentKernel.register_agent()` replaces the old instance

---

## 15. Plugin Guide

### Create a plugin agent

```python
# agents/my_plugin_agent.py
from app.agents.base import (
    EvolvableAgent, AgentContext, AgentResult,
    AgentCapability, AgentPermissions, CapabilityKind,
)

class MyPluginAgent(EvolvableAgent):
    name        = "my_plugin"
    description = "Does something useful"
    group       = "utility"
    version     = "1.0.0"

    @property
    def capabilities(self):
        return [
            AgentCapability(CapabilityKind.READ, "Reads project files"),
        ]

    @property
    def permissions(self):
        return AgentPermissions(can_read_filesystem=True)

    def validate(self, ctx):
        if "forbidden" in ctx.input:
            return ValidationResult.fail("Input contains forbidden word")
        return ValidationResult.ok()

    def estimate_cost(self, ctx):
        return CostEstimate(estimated_tokens=300, estimated_cost_usd=0.001)

    def health_check(self):
        return AgentHealth(status=HealthStatus.HEALTHY, message="OK")

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, f"Processed: {ctx.input}")
```

Drop the file in `agents/` — it will be picked up at next boot or hot-reload.

### Trigger hot-reload via API

```
POST /api/agentos/generate
{ "description": "An agent that ...", "agent_name": "my_new_agent" }
```

Generated code goes through the full CodeGenPipeline and requires approval.

---

## 16. Deployment Guide

### Render (recommended)

```yaml
# render.yaml
services:
  - type: web
    name: axon
    env: python
    buildCommand: pip install -r requirements.txt && npm run build
    startCommand: uvicorn app_main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: axon-db
          property: connectionString
      - key: SESSION_SECRET
        generateValue: true
      - key: ANTHROPIC_API_KEY
        sync: false   # set manually
      - key: STRIPE_SECRET_KEY
        sync: false
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `SESSION_SECRET` | ✅ | JWT signing secret |
| `ANTHROPIC_API_KEY` | ✅ | Claude access (AgentOS AI features) |
| `STRIPE_SECRET_KEY` | optional | Subscription billing |
| `GOOGLE_CLIENT_ID` | optional | OAuth |
| `GITHUB_CLIENT_ID` | optional | OAuth |

### Health endpoint

```
GET /api/health
GET /api/diagnostics/health
```

Use `/api/diagnostics/health` for detailed probe-level status.

---

## 17. Troubleshooting

### Agent not found

```
Error: No agent for intent: 'deploy'
```
→ Check `python agentos.py agents list` — is `deploy` registered?  
→ Boot the kernel: `get_agent_kernel()` in Python or hit `GET /api/agentos/status`.

### Build fails

```bash
npm run doctor    # full environment report
npm run heal      # self-healing installer
```

### Dependency missing

The `DependencyMonitorService` logs to `logs/runtime.log`:
```
WARN  Service 'dependency_monitor': missing packages: ['anthropic']
```
→ Run `pip install -r requirements.txt`.

### Health probe UNHEALTHY

```bash
python agentos.py status    # shows service state
curl /api/diagnostics/health  # detailed probe report
```

### Memory growing unbounded

The `MemoryCompactorService` runs hourly. To compact manually:
```bash
python agentos.py status   # check memory_compactor uptime
curl -X POST /api/diagnostics/services/memory_compactor/start
```

### Generated code rejected

Check the pipeline stages:
```bash
curl /api/diagnostics/codegen   # list pending + rejected
```
The `stages` array in the response shows which stage failed and why.

### Secret accidentally committed

The `SecurityMonitorService` will log:
```
CRITICAL  SECURITY: possible secret found in config/settings.json
```
→ Remove the secret, rotate it immediately, then run `git filter-repo` to purge history.
→ Update the Render env var with the new value.

---

## Sequence Diagrams

### Agent execution (happy path)

```
Client          API            Kernel        Agent      Memory    Reflector
  │              │               │              │           │          │
  │ POST /run    │               │              │           │          │
  │─────────────►│               │              │           │          │
  │              │  kernel.run() │              │           │          │
  │              │──────────────►│              │           │          │
  │              │               │ parse intent │           │          │
  │              │               │─────────────►│           │          │
  │              │               │◄─────────────│           │          │
  │              │               │  agent.run() │           │          │
  │              │               │─────────────►│           │          │
  │              │               │◄─────────────│           │          │
  │              │               │           memory.add()   │          │
  │              │               │─────────────────────────►│          │
  │              │               │         reflector.reflect()         │
  │              │               │────────────────────────────────────►│
  │              │  AgentResult  │              │           │          │
  │              │◄──────────────│              │           │          │
  │  JSON        │               │              │           │          │
  │◄─────────────│               │              │           │          │
```

### Code generation (approval flow)

```
Client       CodeGenPipeline     SecurityScan   ApprovalGate  AgentLoader
  │                │                  │               │              │
  │ generate()     │                  │               │              │
  │───────────────►│                  │               │              │
  │                │ format→lint→SA   │               │              │
  │                │─────────────────►│               │              │
  │                │◄─────────────────│               │              │
  │                │           status=AWAITING         │              │
  │◄───────────────│                  │               │              │
  │                │                  │               │              │
  │ approve(run_id)│                  │               │              │
  │───────────────────────────────────────────────────►              │
  │                │                  │               │ load_file()  │
  │                │                  │               │─────────────►│
  │                │                  │               │◄─────────────│
  │ REGISTERED     │                  │               │              │
  │◄───────────────────────────────────────────────────              │
```
