# Security Tenant-Boundary Audit — P0.5

**Trigger:** the Testing Foundation Audit (`docs/testing-foundation-audit.md`) flagged that `kernel_api`, `planning_api`, `runtime_api`, `events_api` have no `Depends(org_context)`. Per instruction, that observation alone was **not** treated as proof of a vulnerability — this document traces each router's actual request path in the running code, and only fixes what was empirically confirmed.
**Scope:** `app/routers/{runtime_api,kernel_api,planning_api,events_api}.py` and the middleware/dependencies they run under. No other router, no billing, no coverage/CI work.
**Baseline before this audit:** commit `3ee4ebb` (docs-only), 1427/1427 tests passing.

---

## 1. Executive Summary

Three of the four routers are **confirmed vulnerable**, verified both by static trace and by executing the real, unmodified code against seeded cross-org data (§8). The fourth (`events_api`) is confirmed vulnerable on two of its three routes; the third route is safe by design. None of the four had *any* server-side check beyond "is this any valid authenticated session, for any org, at all" — that check happens once, globally, in `app/factory.py`'s `api_auth_middleware`, and nothing downstream re-verifies who the caller is relative to the resource they're asking for.

| Router | Verdict |
|---|---|
| `runtime_api` | **CONFIRMED IDOR** — classic object-level: execution status/report/artifacts/cancel keyed only by `execution_id`, no ownership check |
| `kernel_api` | **CONFIRMED — missing authorization** (broader than IDOR: not a per-tenant object, a global privileged capability with no role/permission check at all) |
| `planning_api` | **CONFIRMED IDOR** — `_plan_cache` is a process-wide dict with no org key; `get_plan()` returns any org's cached goal/tasks given the id |
| `events_api` | **CONFIRMED (partial)** — `replay`/`dead_letters` leak cross-org billing/organization/integration events; `stats()` is safe (aggregate counts only, no event content) |

All four are fixed in this change, using only mechanisms that already exist elsewhere in the codebase (`app.tenancy.context.org_context`/`OrgContext` for the three tenant-data routers, `app.core.api_keys.require_api_key(scopes=["admin"])` for the one system-wide, non-tenant router) — no new authorization architecture was introduced. 25 new regression tests were added; the full suite (1452 tests) passes with zero regressions.

---

## 2. Runtime API Authorization Trace

**Request → authentication → org/user context → execution_id → lookup → authorization → response**, as the code actually ran (before this fix):

1. `POST /api/runtime/{execution_id}/status|report|artifacts...|DELETE` arrives.
2. `app/factory.py`'s `api_auth_middleware` (global, all `/api/*` paths not in `PUBLIC_PREFIXES`) checks: is there a valid `X-Sub-Token`/session cookie **or** a valid `Authorization: Bearer` JWT? If yes → `call_next(request)`, nothing more. This step verifies *a* user is logged in. It does not resolve, attach, or check *which organization* that user belongs to — `app/factory.py`'s own comment on the neighboring `tenant_context_middleware` states this explicitly: *"This never grants or denies anything — real membership enforcement stays entirely in OrgContext/org_context ... which does its own DB check."*
3. Request reaches `app/routers/runtime_api.py`. Confirmed by direct inspection (and by calling the functions, §8) that **none** of `get_status`, `get_report`, `list_artifacts`, `download_artifact`, `cancel_execution` had any parameter beyond the path parameters themselves — no `Request`, no `Depends(...)` of any kind.
4. Lookup: `rec = _executions.get(execution_id)` — a plain process-lifetime `dict`, keyed only by `execution_id` (`str(uuid4())[:16]`, generated in `app/execution/platform/engine.py:91`). The stored record (`{"status", "report", "workspace"}`) never carried an org/user identifier to check against.
5. Authorization: **none**. The only gate was `if not rec: 404` — existence, not ownership.
6. Response: the full `report` dict (whatever the execution produced) is returned to whoever asked, regardless of org.

Artifacts are worse in one respect: `ArtifactSystem.load(execution_id)` reads from `$TMPDIR/platform-artifacts/{execution_id}/` (`app/execution/platform/artifacts.py:36`) — a filesystem path keyed only by `execution_id`, with **no** relationship to the in-memory `_executions` dict at all. Even if `_executions` had been cleared (server restart, or the entry evicted), artifact download would still succeed for a known/leaked `execution_id`.

**Answer to the specific question asked:** access depended **only** on possessing a valid `execution_id` string. No check of `user_id`, `organization_id`, `project_id`, `workspace_id`, or any equivalent ownership boundary existed anywhere in the router, the in-memory store, or `ArtifactSystem`.

---

## 3. Kernel API Authorization Trace

1. Global `api_auth_middleware` — same as above: confirms *a* session exists, nothing about role or org.
2. Router (`app/routers/kernel_api.py`): confirmed **zero** `Depends(...)` on any of the six routes (`kernel_execute`, `kernel_status`, `kernel_state`, `kernel_modifications`, `kernel_rollback`, `kernel_agents`).
3. `kernel_execute` passes `caller`/`user_id` straight from the **client-supplied request body** (`KernelExecuteRequest.caller: str = "api"`, `.user_id: Optional[str]`) into `AIKernel.execute(raw, caller=..., user_id=...)` (`app/kernel/kernel.py:126`). These fields are metadata carried through logging/rate-limiting only — never checked against the actual authenticated identity from step 1.
4. Middleware pipeline (`app/kernel/middleware.py`): `trim_input`, `logging_mw`, `timing_mw`, `state_tracker_mw`, `rate_limit_mw` (keyed by the client-supplied `caller` string, not identity), `alias_resolver_mw`. **No** middleware checks role, permission, or org.
5. Command execution reaches `SelfModifyingEngine` (`app/kernel/self_modify.py`) via the `modify` command family. Its only gate is `PolicyEngine.check_write()` (`app/kernel/policy.py`), which is a **path/content** policy — it decides *which files* may be written (blocks `.env`, `.git/`, `migrations/`, secrets, CI config; allows `app/`, `src/`, `plugins/`, `commands/`, `tests/`) and caps file size at 512 KB. It never inspects *who* the caller is.

**Answer:** this is not a tenant-boundary gap (the kernel is a single process-wide singleton — there is no "org's kernel" to leak between orgs), it is a **complete absence of authorization** for a capability that can rewrite the running application's own source files, reachable by any authenticated user of any org and any role. This is more severe than an object-level IDOR: it is unrestricted access to a system-wide privileged action.

---

## 4. Planning API Authorization Trace

1. Global middleware — same pattern, authentication only.
2. Router (`app/routers/planning_api.py`): confirmed zero `Depends(...)` on `plan_analyze`, `plan_execute`, `get_plan`, `plan_validate`.
3. `_plan_cache: dict[str, dict] = {}` is process-wide, keyed by `plan_id = str(uuid.uuid4())` (`app/planning/engine.py:179`) with **no** org field anywhere on `RichPlan` or in the cache entry.
4. `GET /api/plan/{plan_id}` does `plan = _plan_cache.get(plan_id); if not plan: 404; return plan` — again, existence, not ownership.
5. One layer down, `AgentKernel.plan_and_run()` (`app/agents/kernel.py:424`) **does** accept and thread through an `organization_id` parameter — the underlying execution primitive already supports tenant scoping. The router simply never passed it: `kernel.plan_and_run(req.goal, caller=req.caller, workspace=req.workspace)` — `organization_id` silently defaulted to `None` on every call. This is a router-level omission of a mechanism that already existed one layer down, not evidence that no isolation mechanism exists in the project at all.

**Answer:** classic IDOR on `get_plan()` (goal text and task breakdown of any org's plan, retrievable by id with no ownership check), plus a related but distinct bug — the router dropping an org parameter that `plan_and_run()` was already built to accept.

---

## 5. Events API Authorization Trace

1. Global middleware — authentication only, as above.
2. Router (`app/routers/events_api.py`): confirmed zero `Depends(...)` on any of `stats`, `replay`, `dead_letters`.
3. `Event` (`app/core/events/bus.py:48`) **does** carry an `organization_id: str | None` field, set by publishers for tenant-scoped event types — `EVENT_TYPES` includes `billing.updated`, `billing.payment_failed`, `billing.invoice_paid`, `organization.created`, `organization.member_added`, `integration.connected/disconnected/sync_*`, i.e. real cross-tenant business data.
4. `replay()` (`EventBus.replay`, `bus.py:168`) filters only by `since_ts`/`type_prefix`/`limit` — no org filter exists in the bus itself, and the router passed none either. Same for `dead_letters()`.
5. `stats()` returns `{"backend", "subscriptions": {...}, "history_size", "dead_letters"}` — aggregate counts and subscription-pattern names only. **No event content, no organization_id, no per-tenant data of any kind.** This route is safe as-is.

**Answer:** `replay`/`dead_letters` are confirmed cross-tenant information disclosure (any authenticated user of any org sees every org's billing/org/integration event history); `stats` is safe by design and needed no change.

---

## 6. Confirmed Vulnerabilities

| # | Router | Route(s) | Type | Fix applied |
|---|---|---|---|---|
| 1 | `runtime_api` | `GET .../status`, `.../report`, `.../artifacts`, `.../artifacts/{id}`, `DELETE .../{id}` | IDOR (object-level, cross-org) | `org_context` + ownership check, 404 on mismatch |
| 2 | `kernel_api` | all 6 routes | Missing authorization (privilege escalation — no tenant boundary to speak of) | `require_api_key(scopes=["admin"])` on all 6 routes |
| 3 | `planning_api` | `GET /{plan_id}` (+ `analyze`/`execute`/`validate` never scoping what they cache) | IDOR (object-level, cross-org) | `org_context`, org-keyed `_plan_cache`, org_id forwarded into `plan_and_run()` |
| 4 | `events_api` | `GET /replay`, `GET /dlq` | Cross-tenant information disclosure | `org_context` + filter to `organization_id == ctx.org_id` |

---

## 7. False Positives / Safe Paths

- `events_api`'s `GET /stats` — aggregate counts only (backend name, subscription pattern counts, history/dlq sizes). No event content is returned, so there is nothing to scope by org. **Left unchanged.**
- `runtime_api`'s `GET /cache/stats`, `DELETE /cache`, `GET /runtimes` — process-wide cache statistics and the list of registered runtime adapters (`node`, `python`, `docker`, etc.). None of this is tenant data — it describes the server itself, identically for every caller. **Left unchanged.** (Whether these three should require *any* elevated privilege — as opposed to just "any authenticated user" — is a separate, smaller question than tenant isolation; noted in §12, not acted on here since no data crosses a tenant boundary.)

No router in this audit was found safe *because* of an authorization mechanism operating in a layer this document didn't originally expect (service/repository/model-level enforcement, etc.) — every gap traced cleanly to "the router never asked," confirmed by directly executing the pre-fix code in §8.

---

## 8. Cross-Tenant Attack Scenarios

Executed directly against the **unmodified** pre-fix code (not simulated, not assumed) before any production file was edited. Full transcript:

```
==============================================================================
1) RUNTIME API — no auth/org parameter exists on any handler at all
==============================================================================
  get_status: params=['execution_id']  <-- no ctx/user/org param possible
  get_report: params=['execution_id']  <-- no ctx/user/org param possible
  list_artifacts: params=['execution_id']  <-- no ctx/user/org param possible
  download_artifact: params=['execution_id', 'artifact_id']  <-- no ctx/user/org param possible
  cancel_execution: params=['execution_id']  <-- no ctx/user/org param possible
  get_status('exec-org-B') -> {'execution_id': 'exec-org-B', 'status': 'done'}
  get_report('exec-org-B') -> {'secret': 'org-B-data'}
  CONFIRMED: any authenticated caller retrieves org B's execution report
  with zero way to prove/require they belong to org B.

==============================================================================
2) KERNEL API — no permission/role dependency on any handler
==============================================================================
  kernel_execute: params=['req']  gated_dependency=False
  kernel_status: params=[]  gated_dependency=False
  kernel_state: params=[]  gated_dependency=False
  kernel_modifications: params=[]  gated_dependency=False
  kernel_rollback: params=['index']  gated_dependency=False
  kernel_agents: params=[]  gated_dependency=False
  CONFIRMED: zero FastAPI Depends(...) anywhere in this router --
  any authenticated user of any org can call POST /api/kernel/execute
  including 'modify patch ...' commands (self_modify.py).

==============================================================================
3) PLANNING API — process-wide plan cache has no org key
==============================================================================
  get_plan('plan-org-B') -> {'goal': "org B's confidential goal text"}
  CONFIRMED: no org parameter exists on get_plan/plan_analyze/plan_execute either.

==============================================================================
4) EVENTS API — replay/dlq have no org filter, events carry organization_id
==============================================================================
  replay() called with NO org parameter -> organizations visible: ['org-A', 'org-B']
  CONFIRMED: a caller authenticated only for org-A sees org-B's billing
  and organization-membership events too -- replay()/dead_letters() have
  no ctx/org parameter to filter on.
```

This matches the requested scenario shape (Org A ↔ Execution A, Org B ↔ Execution B, authenticated caller from A supplies B's id) as closely as the endpoints' real signatures allow: `/status`, `/report`, `/artifacts/{id}` (proven via `download_artifact`'s param signature + the identical lookup path as `get_status`/`get_report`), and `DELETE /{execution_id}` were all confirmed to accept only a bare id with no identity parameter — there was no "supply a wrong org header" step to test because there was no org parameter to supply one against; the absence itself is the proof. `/api/plan/{plan_id}` and `/api/events/replay` were exercised the same way, with real seeded cross-org data (`org-A`/`org-B` executions, plans, and published events).

**Post-fix confirmation (§10/§11):** the same attack shape, re-run as proper positive/negative regression tests against the fixed code, now returns `404` for every cross-org attempt and `200` with the correct data for same-org access. See `tests/security/test_runtime_kernel_planning_events_tenant_boundary.py`.

---

## 9. Fix Applied

Smallest change per router, reusing existing project mechanisms only — no new authorization architecture, no client-supplied org id ever trusted.

**`app/routers/runtime_api.py`** — `execute()` now requires `Depends(org_context)` and stores the verified `ctx.org_id` alongside each execution record. A new `_owned_execution(execution_id, ctx)` helper (mirrors `jobs_api.py`'s inline pattern) looks up the record and 404s — not 403 — if it's missing *or* belongs to a different org, before any of `get_status`, `get_report`, `list_artifacts`, `download_artifact`, `cancel_execution` do anything else. `cache/stats`, `cache` (DELETE), `runtimes` are untouched (§7).

**`app/routers/kernel_api.py`** — every route now requires `Depends(require_api_key(scopes=["admin"]))`, the same mechanism `app/routers/usage_api.py`'s `/api/admin/plans/{id}` and `app/routers/marketplace.py`'s admin routes already use for non-org-scoped, system-level actions. This makes the kernel API reachable only with a provisioned admin API key (`Authorization: ApiKey axon_...`), never by an ordinary logged-in user regardless of org.

**`app/routers/planning_api.py`** — `plan_analyze`, `plan_execute`, `get_plan`, `plan_validate` now require `Depends(org_context)`. `_plan_cache` entries are now `{"org_id": ctx.org_id, "plan": serialised}`; `get_plan()` 404s on org mismatch, same convention as above. `plan_execute()` additionally now forwards `organization_id=ctx.org_id` into `AgentKernel.plan_and_run(...)`, a parameter that function already accepted but the router had never supplied.

**`app/routers/events_api.py`** — `replay()` and `dead_letters()` now require `Depends(org_context)` and filter their results to `organization_id == ctx.org_id`, excluding events with no `organization_id` at all (deny-by-default: an untagged event isn't provably safe to show a given tenant, so it's hidden rather than shown to everyone). `stats()` is unchanged (§7).

All four fixes are server-side, deny-by-default (missing/mismatched org → 404, not a degraded response), ownership-scoped using the already-verified `OrgContext` (never a client-supplied `X-Organization-Id` value taken at face value — `org_context` itself re-verifies membership against the DB, per `app/tenancy/context.py`), and consistent with the existing `jobs_api.py`/`workflow_api.py` conventions already in the codebase.

No architectural changes: no new dependency, no new isolation mechanism, no schema/migration, no UI change.

---

## 10. Regression Tests

Added: `tests/security/test_runtime_kernel_planning_events_tenant_boundary.py` (25 tests).

- **Runtime API** (11 tests): positive access to own execution (`status`/`report`/`cancel`/`list_artifacts`), negative 404 on cross-org `status`/`report`/`cancel`/`list_artifacts`/`download_artifact` (with an explicit assertion that `cancel` on org B's execution does **not** delete it, and that artifact routes 404 *before* touching `ArtifactSystem`/disk), unknown-id also 404 (no oracle between "wrong org" and "doesn't exist"), and a structural check that every id-based route depends on `org_context`.
- **Kernel API** (4 tests): every route requires `require_api_key(scopes=["admin"])` (structural); a request with no API key gets 401; a key present but lacking the `admin` scope gets 403; a key with the `admin` scope succeeds (200).
- **Planning API** (5 tests): positive/negative/unknown-id on `get_plan` (same 404-only convention), structural check all four routes depend on `org_context`, and a behavioral test confirming `plan_execute` now forwards `ctx.org_id` into `plan_and_run(organization_id=...)`.
- **Events API** (5 tests): `replay` filtered to the caller's org and excludes untagged events; `dead_letters` filtered the same way; `stats` confirmed to still take no `ctx` (intentionally unscoped); structural check `replay`/`dead_letters` depend on `org_context`.

---

## 11. Security Test Results

All commands run against this branch after the fix, from repo root, with `pytest`/`pytest-asyncio`/`httpx`/`fastapi` and the full `requirements.txt` set installed locally for this audit (not a CI change — see §14).

```
$ python -m pytest tests/security/test_runtime_kernel_planning_events_tenant_boundary.py -q
25 passed

$ python -m pytest tests/security/ -q
205 passed, 6 subtests passed

$ python -m pytest tests/test_runtime.py tests/test_reliability_wiring.py tests/test_platform.py \
      tests/test_config_startup.py tests/test_agentos_run_dedup.py tests/test_agent_os.py -q
169 passed

$ python -m pytest tests/test_ai_routing.py tests/test_integrations.py tests/test_performance.py -q
85 passed

$ python -m pytest tests/ -q
1452 passed, 7 warnings, 16 subtests passed   (baseline was 1427 — +25 new, 0 broken, 0 skipped)
```

`tests/test_reliability_wiring.py`, `tests/test_performance.py`, `tests/test_ai_routing.py`, `tests/test_integrations.py` (circuit breaker / bulkhead / cost-router coverage) and `tests/test_runtime.py`/`tests/test_agent_os.py`/`tests/test_agentos_run_dedup.py` (streaming / execution lifecycle / dedup) all pass unchanged — the fix touches only the four router files and adds one test file; nothing in the execution engine, streaming path, or resilience primitives was modified.

Additionally confirmed the app still boots and its OpenAPI schema still generates cleanly with all 29 routes across the four routers present (`/api/runtime/*`, `/api/kernel/*`, `/api/plan/*`, `/api/events/*`) — no import cycle or route-registration regression from the new `app.tenancy.context` / `app.core.api_keys` imports.

---

## 12. Remaining Risks

- **`events_api.replay()` filters after `limit` is applied**, not before — an org with a lot of history mixed with other orgs' events in the ring buffer could see fewer than `limit` results even when more of their own events exist further back. Not a security issue (nothing leaks), a completeness/UX one; flagged, not fixed, per "smallest possible fix."
- **`kernel_api` now requires a provisioned admin API key** — if no such key currently exists in this deployment, the kernel API becomes unreachable by anyone until one is issued (`app/core/api_keys.py` has the issuance path already; out of scope here). This is the intended, deny-by-default outcome, but it is a behavior change worth the team's explicit awareness before deploy, not just a test-suite concern.
- **`runtime_api`'s `cache/stats`, `cache` (DELETE), `runtimes`** remain reachable by any authenticated user (§7) — safe today because they carry no tenant data, but `DELETE /api/runtime/cache` is a shared-resource action (evicts cache for every org at once) gated only by "logged in." Not a tenant-isolation bug, but worth a future look if abuse/DoS-via-cache-eviction becomes a concern — explicitly not addressed here (out of scope: no redesign, no new gate beyond what a confirmed vulnerability required).
- **This audit covered exactly the four named routers.** The Testing Foundation Audit's original grep (`docs/testing-foundation-audit.md` §5) found these were the routers missing `org_context` among the 8 mounted-but-untested ones; it did not claim to have swept every router in `app/routers/` for the same pattern. A broader sweep for "any route with no `Depends(...)` at all" was not performed and is a reasonable candidate for a future, explicitly-scoped pass — not started here per this gate's instructions.

---

## 13. Recommended Next Step

Two independent tracks are now both at a clean stopping point:

1. **This security fix** is complete, tested, and isolated to the four files named in the trigger. Ready to merge as-is.
2. **The Testing Foundation roadmap** (`docs/testing-foundation-audit.md`) remains exactly where it was left — P-Test-0 (informational coverage wiring) was the recommended first step there and still is; nothing in this audit changes that recommendation, it only removed the two routers' worth of "will this test surface an auth gap" uncertainty flagged in that document's §10, since the gap is now closed rather than merely flagged.

No further action recommended without explicit direction on which track (or both) to resume.

---

## SECURITY GATE

```
runtime_api:
IDOR CONFIRMED (fixed)

kernel_api:
IDOR CONFIRMED (fixed) — note: technically missing-authorization / privilege
escalation rather than object-level IDOR (kernel state is a single
process-wide singleton, not per-tenant data); flagged as such in §3/§6.

planning_api:
IDOR CONFIRMED (fixed)

events_api:
IDOR CONFIRMED (fixed) — partial: replay/dlq only; stats was already SAFE.

Production fix:
DONE

Security regression tests:
PASS (25/25 new, tests/security/test_runtime_kernel_planning_events_tenant_boundary.py)

Full suite:
PASS (1452/1452, +25 vs. 1427 baseline, 0 failures, 0 skipped)

UI changes:
NONE

Schema changes:
NONE

Migrations:
NONE

Coverage implementation:
NOT STARTED

Billing tests:
NOT STARTED

Context P1:
NOT STARTED

Next decision:
WAIT FOR APPROVAL
```
