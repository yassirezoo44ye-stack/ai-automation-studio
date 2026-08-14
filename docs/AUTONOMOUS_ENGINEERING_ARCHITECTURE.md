# Autonomous Engineering Architecture
## Flow — AI Engineering Control Plane

**Document Status:** Phase 0 — Discovery Complete  
**Date:** 2026-08-14  
**Branch:** feat/app-builder-async-engine  

---

## 1. Current Architecture (Discovery Results)

### 1.1 Integration Framework — EXISTS ✅

Location: `app/integrations/`

A complete, production-ready integration SDK with:

| Component | File | Status |
|---|---|---|
| `IntegrationProvider` ABC | `provider.py` | ✅ Complete |
| `IntegrationRegistry` | `registry.py` | ✅ Complete |
| `CredentialStore` (Fernet-encrypted, Postgres) | `credential_store.py` | ✅ Complete |
| `IntegrationService` (orchestration facade) | `service.py` | ✅ Complete |
| Scope validation | `permissions.py` | ✅ Complete |
| OAuth2 (PKCE, token refresh) | `oauth.py` | ✅ Complete |
| Webhook verify + dedup | `webhooks.py` | ✅ Complete |
| Sync engine (job-queue backed) | `sync_engine.py` | ✅ Complete |
| Circuit breaker per org+provider | `retry.py` | ✅ Complete |
| Health probes | `health.py` | ✅ Complete |
| Metrics | `metrics.py` | ✅ Complete |
| Events | `events.py` | ✅ Complete |
| REST API (`/api/orgs/{org_id}/integrations/...`) | `app/routers/integrations.py` | ✅ Complete |

**Critical gap:** No real providers registered. Only `WebhookRelayProvider` (example).  
**Needed:** GitHub, Render, Vercel, Sentry, Anthropic providers.

---

### 1.2 Job Queue — EXISTS ✅

Location: `app/core/jobs/queue.py`

- Redis-backed (in-memory fallback for dev)
- `pending → running → completed | failed | cancelled`
- Priority dispatch: `high | normal | low`
- Retry with exponential backoff + dead-letter queue
- org_id scoping (`submit(..., org_id=org_id)`)
- Idempotency deduplication
- Handler registry + scheduler loop (delayed jobs)
- Singleton: `get_job_queue()`

---

### 1.3 Workflow Engine — EXISTS ✅

Location: `app/core/workflow/engine.py`

- DAG execution (Kahn's topological sort)
- Parallel branches via `asyncio.TaskGroup`
- Human Approval Gates (in-memory `asyncio.Event`)
- Retry + backoff per step (`RetryPolicy`)
- Timeout per step and workflow
- Saga compensation (LIFO rollback)
- `WorkflowBuilder` fluent API
- **Critical gap:** Approvals are in-memory only — lost on restart.

---

### 1.4 Organizations / Teams / RBAC — EXISTS ✅

Location: `app/tenancy/`

Roles (hierarchy): `owner → admin → manager → developer → operator → viewer`

Permission check: `require_permission("resource", "action")` FastAPI dependency.  
`OrgContext`: `{org_id, user_id, user_email, role}` — resolved from verified DB membership.

Tables:
- `organizations` — org metadata, plan, settings
- `organization_members` — role per user per org
- `teams` — sub-groups within org
- `invitations` — invite tokens
- `activity_logs` — audit trail (used by IntegrationService)

RLS (`app/tenancy/rls.py`): 16 tables with `FORCE ROW LEVEL SECURITY` + `org_scoped` policy.

---

### 1.5 AI Gateway — EXISTS ✅

- `app/ai/gateway.py` — `AIGateway.complete()` / `AIGateway.stream()` with caching, cost tracking, memory enrichment
- `app/core/ai/inference/engine.py` — `InferenceEngine` (authoritative executor, used by routers)
- `app/core/ai/tools/executor.py` — `ToolExecutor` with allowlist enforcement, sandbox, event emission
- `app/ai/tools.py` — decorator-based tool registry (`_REGISTRY`)

ToolExecutor already enforces: if `allowed_tools` is given, a model cannot invoke any tool not in that set.

---

### 1.6 Observability — EXISTS ✅

Location: `app/core/observability/`

- `health.py` — `HealthRegistry` (parallel probes, HEALTHY/DEGRADED/UNHEALTHY)
- `metrics.py` — `MetricsRegistry` (Prometheus-compatible counters/gauges/histograms)
- `tracer.py` — span-based tracing (OpenTelemetry-compatible)
- `context.py` — request tag propagation
- `bridges.py` — wires event bus → metrics/tracer

---

### 1.7 Memory — EXISTS ✅

- `app/memory/layered.py` — layered memory (working → session → long-term)
- `app/memory/semantic.py` — semantic search
- `app/agents/memory.py` — agent execution history (JSON-persisted, org-scoped)
- `app/core/ai/memory/manager.py` — MemoryManager (conversation + knowledge)

---

### 1.8 Audit Logs — PARTIAL ⚠️

`activity_logs` table exists and is written by:
- `IntegrationService.connect()` → `integration.connected`
- `IntegrationService.disconnect()` → `integration.disconnected`
- `TenancyService` methods

**Gap:** No structured engineering events (mission_started, tool_called, deployment_verified, etc.).

---

### 1.9 Frontend Pages — EXISTS (partial)

137 TSX files. Relevant pages:
- `OrganizationsPage.tsx`
- `ObservabilityPage.tsx` (system metrics, workflow analytics, security audit)
- `SettingsPage.tsx`
- `BillingPage.tsx`
- `TeamsPage.tsx`
- `AIRoutingPage.tsx`

**Gap:** No Engineering Control Plane pages (`/engineering`, `/missions`, `/approvals`, `/evidence`, `/releases`).

---

## 2. Gap Analysis

| Requirement | Status | Location |
|---|---|---|
| Integration Framework SDK | ✅ EXISTS | `app/integrations/` |
| GitHub Provider | ❌ MISSING | Create `app/integrations/providers/github.py` |
| Render Provider | ❌ MISSING | Create `app/integrations/providers/render.py` |
| Vercel Provider | ❌ MISSING | Create `app/integrations/providers/vercel.py` |
| Sentry Provider | ❌ MISSING | Create `app/integrations/providers/sentry.py` |
| Anthropic Provider (status check) | ❌ MISSING | Create `app/integrations/providers/anthropic_provider.py` |
| Job Queue | ✅ EXISTS | `app/core/jobs/queue.py` |
| Workflow Engine (DAG + approvals) | ✅ EXISTS | `app/core/workflow/engine.py` |
| Persistent Approvals | ❌ MISSING | Needs `eng_approvals` table + service |
| Organizations / RBAC | ✅ EXISTS | `app/tenancy/` |
| RLS | ✅ EXISTS | `app/tenancy/rls.py` |
| Audit Logs (basic) | ✅ EXISTS | `activity_logs` table |
| Engineering Audit Events | ❌ MISSING | Extend event bus with engineering event types |
| AI Gateway | ✅ EXISTS | `app/ai/gateway.py` |
| Tool Executor + Allowlist | ✅ EXISTS | `app/core/ai/tools/executor.py` |
| Engineering Tool Gateway | ❌ MISSING | `app/engineering/tools/gateway.py` |
| Mission Engine (DB-persistent) | ❌ MISSING | `app/engineering/missions.py` |
| Mission State Machine | ❌ MISSING | PENDING→PLANNING→RUNNING→WAITING_APPROVAL→VERIFYING→SUCCEEDED→FAILED→CANCELLED→ROLLED_BACK |
| Evidence System | ❌ MISSING | `app/engineering/evidence.py` |
| Approval Center (persistent) | ❌ MISSING | `app/engineering/approvals.py` |
| Permission levels for engineering | ❌ MISSING | Map OBSERVER/ANALYST/OPERATOR/AUTONOMOUS → existing roles |
| Release Autopilot template | ❌ MISSING | `app/engineering/templates/release_pipeline.py` |
| Production Verification (SHA check) | ❌ MISSING | `app/engineering/verify.py` |
| Rollback Policy | ❌ MISSING | `app/engineering/rollback.py` |
| Engineering Project Memory | ⚠️ PARTIAL | Extend `app/memory/` |
| Cost limits for missions | ❌ MISSING | Extend mission with budget fields |
| Engineering UI (6 pages) | ❌ MISSING | `src/renderer/features/engineering/` |
| Observability Events (engineering) | ⚠️ PARTIAL | Extend event types |
| Security: tool result sanitization | ❌ MISSING | Add to tool gateway |
| Tests for Control Plane | ❌ MISSING | `tests/test_engineering_*.py` |

---

## 3. Proposed Architecture

### 3.1 Layered View

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Flow Frontend                                │
│  /engineering  /missions  /integrations  /approvals  /evidence       │
│  /releases                                                           │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ REST/WebSocket
┌──────────────────────────▼──────────────────────────────────────────┐
│                    Engineering API Layer                             │
│  app/routers/engineering_api.py                                      │
│  app/routers/missions_api.py                                         │
│  app/routers/approvals_api.py                                        │
│  app/routers/evidence_api.py                                         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                   Engineering Control Plane                          │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ MissionEngine│  │ToolGateway   │  │EvidenceStore │               │
│  │ (missions.py)│  │ (gateway.py) │  │ (evidence.py)│               │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘               │
│         │                 │                                          │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────────────┐               │
│  │ ApprovalSvc  │  │ VerifyEngine │  │ RollbackSvc  │               │
│  │ (approvals)  │  │ (verify.py)  │  │ (rollback.py)│               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ uses (never duplicates)
┌──────────────────────────▼──────────────────────────────────────────┐
│                   Existing Platform Infrastructure                   │
│                                                                      │
│  IntegrationService    JobQueue         WorkflowEngine               │
│  CredentialStore       InferenceEngine  ToolExecutor                 │
│  TenancyService        HealthRegistry   MetricsRegistry              │
│  ActivityLogs          EventBus         Tracer                       │
│  RLS                   OrgContext       require_permission            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ API calls (typed, org-scoped)
┌──────────────────────────▼──────────────────────────────────────────┐
│                   External Providers (read-only credentials)         │
│                                                                      │
│  GitHubProvider   RenderProvider   VercelProvider   SentryProvider   │
│  (IntegrationProvider ABC — credentials always encrypted)            │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 3.2 Data Flow: Mission Execution

```
User → POST /api/orgs/{org_id}/missions
         │
         ▼
  OrgContext (verified membership + role)
         │
         ▼
  MissionEngine.create_mission()
  → INSERT eng_missions (status=PENDING)
         │
         ▼
  JobQueue.submit("mission_run", org_id=org_id)
         │
         ▼
  MissionRunner (registered handler)
  → UPDATE eng_missions (status=PLANNING)
  → Claude: InferenceEngine.complete(tools=allowed_tool_names)
         │
         ▼
  ToolGateway.execute(tool_name, args, org_id=ctx.org_id)
  → Permission check: require_permission("engineering", action_tier)
  → Provider.call(credential_from_store)      ← never exposes secrets
  → EvidenceStore.record(tool, inputs, output)
  → ActivityLog: INSERT activity_logs(action=tool_called)
         │
         ▼
  Result: UNTRUSTED DATA (from external API)
  → Sanitized before inclusion in LLM context
  → Never modifies org_id, permission, or mission state directly
         │
         ▼
  If action requires approval:
  → ApprovalService.create(mission_id, action, risk_level)
  → UPDATE eng_missions (status=WAITING_APPROVAL)
  → Notify user → User clicks Approve/Reject
  → ApprovalService.resolve() → resume mission
         │
         ▼
  VerifyEngine.verify_deployment()
  → Check health endpoint
  → Check running SHA vs expected SHA
  → Check database connectivity
  → EvidenceStore.record(verification_result)
         │
         ▼
  UPDATE eng_missions (status=SUCCEEDED|FAILED)
```

---

### 3.3 Tool Categories and Permission Mapping

| Tool Category | Example Tools | Minimum Role | Requires Approval |
|---|---|---|---|
| READ | `github.list_repos`, `render.get_logs`, `sentry.list_errors` | viewer (OBSERVER) | No |
| ANALYZE | `github.diff`, `sentry.analyze_error`, `database.inspect_schema` | developer (ANALYST) | No |
| WRITE | `github.create_branch`, `github.create_pr`, `github.commit_file` | operator (OPERATOR) | No for non-default branches |
| DEPLOY | `render.deploy`, `vercel.deploy` | admin (OPERATOR) | Yes in production |
| DESTRUCTIVE | `render.rollback`, `github.merge_pr`, `render.delete_service` | owner (AUTONOMOUS) | Always |

Engineering Permission Levels → Existing Roles mapping:
```
OBSERVER   → viewer
ANALYST    → developer
OPERATOR   → operator / admin
AUTONOMOUS → owner (+ explicit org policy)
```

---

### 3.4 Mission State Machine

```
                    create()
                       │
                       ▼
                    PENDING
                       │
               start_planning()
                       │
                       ▼
                   PLANNING ──────────────────────┐
                       │                          │ plan_failed()
                  plan_ready()                    ▼
                       │                       FAILED ←──────────┐
                       ▼                                          │
                   RUNNING ─────────────────────────────┐        │
                       │                                │        │
              needs_approval()                    step_failed()  │
                       │                                │        │
                       ▼                                └────────┘
               WAITING_APPROVAL
               │           │
         approved()     rejected()
               │           │
               ▼           ▼
           RUNNING       FAILED
               │
          all_done()
               │
               ▼
           VERIFYING
           │       │
    verified()  verify_failed()
           │       │
           ▼       ▼
       SUCCEEDED  FAILED
                   │
            rollback_requested()
                   │
                   ▼
            ROLLED_BACK

  cancel() → CANCELLED  (from any non-terminal state)
```

Transitions stored in `eng_task_transitions` (persistent, audited, idempotent via state check).

---

### 3.5 Evidence Model

```sql
eng_evidence (
    id              UUID PRIMARY KEY,
    mission_id      UUID NOT NULL REFERENCES eng_missions(id),
    task_id         UUID REFERENCES eng_tasks(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    provider        TEXT NOT NULL,          -- 'render', 'github', etc.
    operation       TEXT NOT NULL,          -- 'deploy', 'create_pr', etc.
    tool_name       TEXT NOT NULL,          -- 'render.deploy'
    inputs_hash     TEXT NOT NULL,          -- SHA-256 of sanitized inputs (no secrets)
    outputs_summary JSONB NOT NULL,         -- sanitized result summary
    verification_status TEXT NOT NULL
        CHECK (verification_status IN ('unverified','pending','verified','failed')),
    verified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- No raw credentials. No LLM chain-of-thought. Summary only.
```

---

### 3.6 Approval Model

```sql
eng_approvals (
    id              UUID PRIMARY KEY,
    mission_id      UUID NOT NULL REFERENCES eng_missions(id),
    task_id         UUID REFERENCES eng_tasks(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    action          TEXT NOT NULL,           -- 'render.deploy', 'github.merge_pr'
    resource        TEXT,                    -- deployment id, repo name, etc.
    risk_level      TEXT NOT NULL
        CHECK (risk_level IN ('low','medium','high','critical')),
    requested_by    UUID NOT NULL REFERENCES users(id),
    decided_by      UUID REFERENCES users(id),
    decision        TEXT CHECK (decision IN ('approved','rejected')),
    reason          TEXT,                    -- agent's reason for requesting
    evidence_id     UUID REFERENCES eng_evidence(id),
    expires_at      TIMESTAMPTZ NOT NULL,    -- auto-expire → FAILED if not decided
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at      TIMESTAMPTZ
);
```

Required permissions to approve:
- `risk_level=low|medium` → `operator` or higher
- `risk_level=high|critical` → `admin` or `owner`

---

### 3.7 Security Boundaries

```
┌─────────────────────────────────────────────────────────────────────┐
│  RULE 1: org_id is ALWAYS sourced from OrgContext (verified DB)     │
│  Never from LLM output. Never from request body alone.              │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  RULE 2: Credentials NEVER leave the CredentialStore               │
│  LLM receives tool names + typed schemas, never raw tokens          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  RULE 3: Tool results from external APIs = UNTRUSTED DATA          │
│  Sanitized before inclusion in LLM context                          │
│  Cannot modify: org_id, permissions, mission state, approval status │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  RULE 4: Every tool call passes through ToolGateway                │
│  Enforces: auth → org scope → permission → allowlist → execute      │
│  → audit → evidence                                                 │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  RULE 5: Production-destructive operations are approval-gated       │
│  merge, deploy, rollback, delete, credential rotation               │
└─────────────────────────────────────────────────────────────────────┘

Prevented threats:
- IDOR: org_id from OrgContext, project ownership verified server-side
- SSRF: existing ssrf_guard.py + allowlisted provider domains only
- SQL injection: parameterized asyncpg queries throughout
- Command injection: no shell execution in tool gateway
- Credential leakage: Fernet-encrypted at rest, never in logs/LLM context
- Prompt injection through tool results: result sanitization layer
- Cross-tenant access: RLS + org_id in every query
- Claude tool misuse: ToolGateway allowlist enforced per-mission
```

---

## 4. Components: Reused vs. New

### REUSED (zero modification)

| Component | File |
|---|---|
| IntegrationProvider ABC | `app/integrations/provider.py` |
| IntegrationRegistry | `app/integrations/registry.py` |
| CredentialStore (Fernet+Postgres) | `app/integrations/credential_store.py` |
| IntegrationService | `app/integrations/service.py` |
| JobQueue (Redis-backed) | `app/core/jobs/queue.py` |
| WorkflowEngine + WorkflowBuilder | `app/core/workflow/engine.py` |
| OrgContext + require_permission | `app/tenancy/context.py` |
| TenancyService + RBAC | `app/tenancy/service.py` |
| RLS (16 tables) | `app/tenancy/rls.py` |
| InferenceEngine | `app/core/ai/inference/engine.py` |
| ToolExecutor + allowlist | `app/core/ai/tools/executor.py` |
| HealthRegistry | `app/core/observability/health.py` |
| MetricsRegistry | `app/core/observability/metrics.py` |
| Tracer | `app/core/observability/tracer.py` |
| EventBus | `app/core/events/bus.py` |
| IdempotencyGuard | `app/core/idempotency.py` |
| CircuitBreaker | `app/core/reliability.py` |
| SSRF guard | `app/core/ssrf_guard.py` |
| activity_logs table | `app/tenancy/schema.py` |

### EXTENDED (minimal changes)

| Component | Change |
|---|---|
| `app/tenancy/schema.py` | Add `eng_missions`, `eng_tasks`, `eng_task_transitions`, `eng_evidence`, `eng_approvals` tables |
| `app/tenancy/rls.py` | Add RLS policies for the 5 new engineering tables |
| `app/factory.py` | Register new providers + engineering routers |
| `app/core/events/bus.py` | Add engineering event types (mission_*, tool_*, deployment_*) |
| `src/renderer/App.tsx` | Add /engineering route |
| `src/renderer/components/layout/Sidebar.tsx` | Add Engineering nav item |

### NEW (net-new files, backward-compatible)

```
app/integrations/providers/
├── github.py              GitHub IntegrationProvider
├── render.py              Render IntegrationProvider
├── vercel.py              Vercel IntegrationProvider
├── sentry.py              Sentry IntegrationProvider
└── anthropic_provider.py  Anthropic status/quota check

app/engineering/
├── __init__.py
├── missions.py            MissionEngine + MissionService
├── tools/
│   ├── __init__.py
│   ├── gateway.py         EngineeringToolGateway
│   ├── github_tools.py    github.* typed tools
│   ├── render_tools.py    render.* typed tools
│   ├── vercel_tools.py    vercel.* typed tools
│   ├── sentry_tools.py    sentry.* typed tools
│   └── database_tools.py  database.* typed tools
├── evidence.py            EvidenceStore
├── approvals.py           ApprovalService (persistent)
├── verify.py              ProductionVerifier (SHA, health, smoke tests)
├── rollback.py            RollbackService
├── memory.py              EngineeringMemory (reuses app/memory/)
└── templates/
    ├── __init__.py
    └── release_pipeline.py  "Prepare Release" WorkflowBuilder template

app/routers/
├── missions_api.py        /api/orgs/{org_id}/missions
├── approvals_api.py       /api/orgs/{org_id}/approvals
└── evidence_api.py        /api/orgs/{org_id}/evidence

tests/
├── test_engineering_providers.py
├── test_engineering_tool_gateway.py
├── test_engineering_missions.py
├── test_engineering_evidence.py
├── test_engineering_approvals.py
├── test_engineering_verify.py
└── test_engineering_security.py

src/renderer/features/engineering/
├── EngineeringPage.tsx          /engineering dashboard
├── MissionsPage.tsx             /missions list
├── MissionDetail.tsx            /missions/{id}
├── ApprovalsPage.tsx            /approvals
├── EvidencePage.tsx             /evidence
└── ReleasesPage.tsx             /releases
```

---

## 5. Permission Matrix

| Permission Level | Maps To | Can Do |
|---|---|---|
| OBSERVER | `viewer` | Read missions, evidence, deployments, errors |
| ANALYST | `developer` | Above + analyze code, create plans, inspect schema |
| OPERATOR | `operator`, `admin` | Above + create branches, PRs, trigger non-prod deploys |
| AUTONOMOUS | `owner` + org policy | Above + merge, deploy prod, credential rotation (approval-gated) |

---

## 6. Mission State Table

```sql
CREATE TABLE eng_missions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id      UUID,
    objective       TEXT NOT NULL,
    template        TEXT,                  -- 'release', 'incident', 'custom', etc.
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending','planning','running','waiting_approval',
            'verifying','succeeded','failed','cancelled','rolled_back'
        )),
    created_by      UUID NOT NULL REFERENCES users(id),
    agent_id        TEXT,                  -- which agent instance is running this
    current_phase   TEXT,
    budget_tokens   INTEGER,               -- max tokens for this mission
    budget_steps    INTEGER DEFAULT 50,    -- max tool calls
    tokens_used     INTEGER DEFAULT 0,
    steps_used      INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 7. Rollout Plan

### Phase A — Discovery (✅ DONE)
- [x] Inspect existing architecture
- [x] Identify reusable components
- [x] Identify gaps
- [x] Write this document

### Phase B — Integration Providers
- [ ] `app/integrations/providers/github.py` (API key auth, typed HTTP calls)
- [ ] `app/integrations/providers/render.py`
- [ ] `app/integrations/providers/vercel.py`
- [ ] `app/integrations/providers/sentry.py`
- [ ] `app/integrations/providers/anthropic_provider.py`
- [ ] Register providers in `app/factory.py`
- [ ] Tests: `tests/test_engineering_providers.py`
- [ ] Verify: all tests pass, lint clean

### Phase C — Engineering Tool Gateway
- [ ] `app/engineering/tools/gateway.py` — `EngineeringToolGateway`
- [ ] Tool definitions per provider (typed, allowlisted, categorized)
- [ ] Permission enforcement per tool category
- [ ] Tool result sanitization (UNTRUSTED DATA → sanitized summary)
- [ ] Tests: `tests/test_engineering_tool_gateway.py`

### Phase D — Mission Engine
- [ ] DB tables: `eng_missions`, `eng_tasks`, `eng_task_transitions`
- [ ] RLS policies for new tables
- [ ] `app/engineering/missions.py` — `MissionService`
- [ ] Mission state machine (all 9 states + transitions)
- [ ] Integration with JobQueue (handler registration)
- [ ] Cost budget enforcement (token + step limits)
- [ ] Tests: `tests/test_engineering_missions.py`

### Phase E — Evidence System
- [ ] DB table: `eng_evidence`
- [ ] `app/engineering/evidence.py` — `EvidenceStore`
- [ ] Auto-record on every tool call (via ToolGateway hook)
- [ ] Router: `GET /api/orgs/{org_id}/evidence`
- [ ] Tests: `tests/test_engineering_evidence.py`

### Phase F — Approval Center (Persistent)
- [ ] DB table: `eng_approvals`
- [ ] `app/engineering/approvals.py` — `ApprovalService`
- [ ] Expiry enforcement (background checker)
- [ ] Router: `app/routers/approvals_api.py`
- [ ] Tests: `tests/test_engineering_approvals.py`

### Phase G — Release Autopilot
- [ ] `app/engineering/verify.py` — `ProductionVerifier` (SHA, health, smoke)
- [ ] `app/engineering/rollback.py` — `RollbackService`
- [ ] `app/engineering/templates/release_pipeline.py` — 13-step pipeline
- [ ] Tests: `tests/test_engineering_verify.py`

### Phase H — UI
- [ ] Engineering dashboard page
- [ ] Missions list + detail
- [ ] Approvals center
- [ ] Evidence trail
- [ ] Releases page
- [ ] Sidebar + routing

### Phase I — Security Hardening
- [ ] Penetration tests: IDOR, SSRF, credential leakage, prompt injection
- [ ] Cross-org access tests
- [ ] Claude tool misuse tests
- [ ] Tests: `tests/test_engineering_security.py`

### Phase J — Full Regression
- [ ] All backend tests pass
- [ ] TypeScript pass
- [ ] ESLint: 0 errors
- [ ] Ruff: no regression
- [ ] Production build passes
- [ ] Docker passes

---

## 8. Design Principles

1. **No new auth system** — use `OrgContext + require_permission()`
2. **No new queue** — use `JobQueue.register_handler()`
3. **No new RLS layer** — extend `_RLS_TABLES` in `rls.py`
4. **No new secret store** — use `CredentialStore` (Fernet-encrypted)
5. **No new audit system** — extend `activity_logs` + new engineering event types
6. **No duplicate abstraction** — `WorkflowEngine` + `JobQueue` are the execution primitives
7. **Smallest safe change per phase** — never a big-bang commit
8. **Backward-compatible migrations** — new tables don't alter existing ones
9. **Every external result is UNTRUSTED DATA** — sanitized before LLM context
10. **Evidence is mandatory** — no claiming success without `EvidenceStore.record()`

---

## 9. Operational Runbook (stub — to be expanded in Phase J)

### Monitoring
- `GET /api/health/detailed` — overall platform health (includes engineering subsystem probes)
- Prometheus metrics: `eng_missions_total{status}`, `eng_tool_calls_total{provider,action}`
- Activity log: `GET /api/orgs/{org_id}/activity?resource=mission`

### Recovery after crash
1. JobQueue scheduler restarts automatically (Redis-backed state survives)
2. `MissionService.recover_stale_missions()` called at startup — re-queues any `running` missions that lost their job
3. Approvals: check `eng_approvals` for expired rows → auto-FAIL those tasks
4. Evidence: write-ahead; any tool call without evidence is flagged on next probe

### Rotating credentials
1. `POST /api/orgs/{org_id}/integrations/{provider_id}/rotate` → creates approval request (risk_level=high)
2. After approval: `CredentialStore.save()` with new secrets (atomic upsert)
3. Old token revoked via `provider.disconnect()` if provider supports it

---

*End of Phase 0 — Discovery. Awaiting user approval before Phase B begins.*
