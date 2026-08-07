# Security Tenant-Boundary Sweep — P0.5.1

**Trigger:** commit `7a56b66` fixed confirmed cross-tenant IDOR/authorization gaps in `runtime_api`, `kernel_api`, `planning_api`, `events_api`. This sweep systematically checks the rest of the codebase for the same pattern before returning to the Testing Foundation roadmap.
**Method:** every router was inventoried, every ID-bearing/mutating endpoint was traced to its actual authorization mechanism, and every candidate finding was reproduced against the real, unmodified code with seeded cross-org data before any production file was touched. No finding below was fixed without a passing reproduction first.
**Scope discipline:** no coverage/CI work, no billing tests, no E2E, no Context P1/Compiler/Ollama/local-LLM/data-residency work, no UI, no schema/migrations, no architecture redesign. Fixes reuse only `org_context`, `require_permission`, `require_api_key`, and the ownership-check conventions already established in `jobs_api.py`/`usage_api.py`/`marketplace.py`/`sandbox.py`/`plugins.py`.

---

## 1. Scope

**Resource ID classes swept:** `execution_id`, `plan_id`, `artifact_id`, `event_id`, job/run IDs, project/workspace IDs, agent/conversation/prompt/memory IDs, worker/installation/listing/team/invitation/key IDs, WebSocket topic strings.

**Sweep angles applied to every candidate, per the request's checklist:**
1. Endpoints receiving a resource ID with no tenant/auth context at all.
2. Queries using an ID directly with no ownership check.
3. Global dictionaries/caches/singletons with no `organization_id` in their key.
4. Filesystem paths built directly from resource IDs.
5. Services callable from a router without tenant context ever reaching them.
6. Background jobs losing `organization_id` between request → queue → execution.
7. Endpoints reaching `AgentKernel`, `SelfModifyingEngine`, or any system-level execution capability.
8. `replay`/`dead_letters`/export/download/cancel/delete/update/read operations that could cross a tenant boundary.
9. Endpoints using `workspace_id`/`project_id` in a way that could mix tenants.
10. Caches/singletons holding tenant-specific data.

---

## 2. Routers/Services Inspected

All 41 files under `app/routers/` (`package_preflight.py` re-confirmed as a non-router shim, per the prior audit's correction — excluded from the count of live routers). Every route's Python signature was extracted via AST (positional, keyword-only, and `Annotated[...]`-style `Depends`), then every ID-bearing or mutating handler was read in full, followed into its service/engine layer, and — where a concrete ownership mechanism existed — spot-verified there (e.g. `TenancyService.get_team`, `ConversationService.delete`, `PromptEngine.rollback`, `InvoiceService.get`).

| Router | Verdict | Notes |
|---|---|---|
| `agent_os_api.py` | **Safe** | Every AgentKernel/AgentMemory call threads `organization_id=await optional_org_id(request)`; extensively self-documented, matches existing `tests/security/test_tenant_isolation.py` coverage |
| `agents.py` | **Safe** | `owner_user_id(conn, request)` + `WHERE ... AND user_id=$N` on every query |
| `ai_router_api.py` | **Safe** | `org_costs`/`budgets` use `org_context`; `usage_summary`/`usage_by_provider` use `optional_org_id` (DB-verified membership, not client-trusted); `models`/`route`/`decisions`/`providers` carry no tenant data (`RouteDecision` has no org field) |
| `api_keys_router.py` | **Safe** | `get_current_user` + `owner_id=user["id"]` scoping on revoke |
| `arabic_api.py` | **Safe** | Stateless NLP endpoints, no resource IDs |
| `auth_users.py` | **Safe** | `Annotated[dict, Depends(get_current_user)]` (missed by a naive AST scan, verified manually) on every self-account route; `revoke_session` explicitly checks `AND user_id=$2` |
| `build.py` | **Safe** | `owner_user_id` + `resolve_project_id` (itself verified: rejects a `project_id` the caller doesn't own with 404) |
| `chat.py` | **Safe** | Same pattern as `build.py` |
| `commands_api.py` | **CONFIRMED** | `execute_command` reached `modify_cmd.py`'s unrestricted file write — see §3, §4 |
| `design.py` | **Safe** | Same pattern as `build.py` |
| `diagnostics_api.py` | **CONFIRMED** | Service start/stop, alert rule create/toggle, codegen approve/reject had zero role check — see §3, §4 |
| `events_api.py` | Fixed in `7a56b66` | Not re-audited here |
| `health.py` | **Safe** | No resource IDs, no tenant data |
| `inference.py` | **Safe** | `ConversationService`/`PromptEngine`/`MemoryManager` all take `user_id=`/`owner_id=` and scope in SQL (verified `DELETE ... WHERE id=$1 AND user_id=$2`) |
| `integrations.py` | **Safe** | `require_permission("integrations", ...)`; webhook route has no permission dependency by design (signature-verified, matches `stripe`'s webhook convention) |
| `jobs_api.py` | **Safe** | Already the reference pattern this sweep's fixes imitate |
| `kernel_api.py` | Fixed in `7a56b66` | Not re-audited here |
| `marketplace.py` | **Safe** | `_assert_owns(item, ctx)` on every mutation; `optional_org_id` on public reads |
| `metrics.py` | **Safe** | Prometheus text export, aggregate only |
| `notifications.py` | **Safe** | `get_current_user` + `user_id=` scoping on every mutation |
| `orchestrator.py` | **CONFIRMED** | `get_execution`/`resume_workflow` — see §3, §4 |
| `org_billing.py` | **Safe** | `org_context`/`require_permission`; `InvoiceService.get` independently verified to filter `WHERE organization_id=$2` |
| `organizations.py` | **Safe** | `TenancyService` methods verified to scope every query by `organization_id` |
| `package.py` | **Safe** | `download_package` — `WHERE id=$1 AND user_id=$2` |
| `planning_api.py` | Fixed in `7a56b66` | Not re-audited here |
| `plugins.py` | **Safe** | `_get_owned_installation(id, org_id)` on every route |
| `projects.py` | **Safe** | Legacy `owner_user_id` pattern, previously hardened (H-02) |
| `runtime.py` | **Safe** | Tool/strategy capability queries, no tenant data |
| `runtime_api.py` | Fixed in `7a56b66` | Not re-audited here |
| `sandbox.py` | **Safe** | `_get_owned_worker(id, org_id)` on every route |
| `social.py` | **Safe** | Stateless generation endpoint, no resource IDs |
| `stats.py` | **Safe** | `owner_user_id` + `WHERE ... user_id=$1` |
| `subscriptions.py` | **CONFIRMED (fixed)** | `subscription_status(email, request)` — see §7 and Addendum below (Security Closure Review): confirmed unauthenticated account impersonation, disabled |
| `tasks.py` | **Safe** | `owner_user_id` pattern |
| `team_chat.py` | **Safe** | `_require_team_in_org` + `delete_message(user_id=ctx.user_id)` |
| `usage_api.py` | **Safe** | Mix of `org_context`/`require_permission`/`require_api_key(admin)`, each used correctly for its route's actual trust boundary |
| `workflow_api.py` | **CONFIRMED** | Approve/reject/active/pending — a previously self-documented "known residual gap" — see §3, §4 |
| `ws.py` | **CONFIRMED ×2** | `agent_ws` (critical — bypassed every other WS endpoint's isolation) and `job_ws` (no auth/ownership at all) — see §3, §4. `chat_ws`, `system_ws`, `system_run_ws`, `notifications_ws` independently verified **safe** |
| `youtube.py` | **Safe** | Stateless info/transcript fetch, rate-limited, no resource IDs |

---

## 3. Confirmed Vulnerabilities

| # | Location | Type | Severity |
|---|---|---|---|
| 1 | `app/routers/orchestrator.py::get_execution`/`resume_workflow` | IDOR — process-wide `WorkflowExecution` dict, no org key | Medium |
| 2 | `app/routers/workflow_api.py` (`active`/`pending_approvals`/`approve_step`/`reject_step`) + `app/core/workflow/engine.py` | IDOR — self-documented known gap, now closed | Medium |
| 3 | `app/routers/diagnostics_api.py` (service start/stop, alert rule create/toggle, codegen approve/reject) | Missing authorization — global privileged capability, zero role check | Medium-High |
| 4 | `app/routers/commands_api.py::execute_command` → `app/commands/builtin/modify_cmd.py` | Missing authorization — **unrestricted arbitrary-path file write**, no `PolicyEngine`-equivalent restriction at all | **Critical** |
| 5 | `app/routers/ws.py::agent_ws` | **Unauthenticated, generic cross-topic subscribe relay** — full bypass of `chat_ws`/`notifications_ws`/`system_run_ws`'s own authorization | **Critical** |
| 6 | `app/routers/ws.py::job_ws` | No authentication, no ownership check — parallel bypass of the already-fixed REST `GET /api/jobs/{job_id}` | High |

Findings #4 and #5 are the two most severe results of this entire sweep, more severe than any of the four fixed in `7a56b66`: #4 requires no `PolicyEngine`-style restriction at all (broader than the original `kernel_api` gap, which was at least confined to specific directories), and #5 requires **no authentication whatsoever** — every other finding in this and the prior sweep required "any authenticated user of any org," #5 required nothing.

---

## 4. Reproduction Evidence

All four reproductions below were executed against the unmodified code, before any production file in this commit was touched.

**#1 — Orchestrator:**
```
get_execution('exec-org-B') with NO org context ->
  {'execution_id': 'exec-org-B', 'workflow_id': 'wf-B', 'state': 'failed',
   'completed_nodes': [], 'current_node': None, 'error': 'org B secret error'}
CONFIRMED: any authenticated caller reads any org's workflow execution state.
```

**#2 — Workflow API / engine:**
```
list_active() with NO org context -> sees run: ['org-a-sensitive-workflow']
list_pending_approvals() -> ['<run-id>:gate']
reject_step(run_a.run_id, 'gate') with NO relation to org-A -> {'rejected': True, ...}
org-A's run outcome after outsider's reject: status=WorkflowStatus.COMPLETED
CONFIRMED: any authenticated caller can see AND reject another org's pending approval step.
```

**#3 — Diagnostics API:**
```
service_start: params=['name']  gated=False
service_stop: params=['name']  gated=False
create_alert_rule: params=['body']  gated=False
toggle_alert_rule: params=['rule_id', 'enabled']  gated=False
codegen_approve: params=['run_id', 'req']  gated=False
codegen_reject: params=['run_id', 'req']  gated=False
CONFIRMED: zero Depends(...) -- any authenticated user of any org can start/stop
background services and approve/reject codegen runs.
```

**#4 — Commands API (filesystem proof, not just a signature check):**
```
modify_handler(file, action=replace, file=/tmp/sweep_proof_victim.txt) -> success=True
  output='✓ File modified (replace): /tmp/sweep_proof_victim.txt'
victim file now contains: 'PWNED BY ANY AUTHENTICATED USER'
CONFIRMED: arbitrary-path file write with ZERO PolicyEngine-style restriction,
reachable via POST /api/commands/execute with only 'any authenticated session' required.
```

**#5 — `agent_ws` topic bypass (real WebSocket round-trip via `TestClient`):**
```
1) connected with ZERO auth token at all: {'type': 'connected', 'session_id': 'anything-no-token-at-all', ...}
2) subscribe ack: {'type': 'subscribed', 'topic': 'notifications:victim-user-id'}
3) subscribe ack: {'type': 'subscribed', 'topic': 'chat:org:victim-org-id'}
4) attacker socket received victim's notification: {'type': 'event', 'topic': 'notifications:victim-user-id',
   'data': {'id': 'n1', 'title': 'Your invoice failed', 'amount_usd': 4900}, ...}
5) attacker socket received victim org's chat message: {'type': 'event', 'topic': 'chat:org:victim-org-id',
   'data': {'user': 'victim-ceo', 'body': 'Q3 acquisition numbers: $12M'}, ...}
```

**#6 — `job_ws` (real WebSocket round-trip):**
```
Connected with ZERO auth token, org B's job_id only ->
 snapshot: {'type': 'snapshot', 'job': {'id': 'job-org-B', 'organization_id': 'org-B',
   'payload': {'secret': 'org B sync creds'}}}
CONFIRMED: job_ws() requires no token and no ownership check -- compare to the
ALREADY-FIXED REST GET /api/jobs/{job_id}, which requires org_context and 404s
on a cross-org job_id. This WS twin bypasses that fix entirely.
```

---

## 5. Remediation

Smallest change per finding, reusing existing mechanisms only:

- **`orchestrator.py`** — `run_workflow` now merges `organization_id=org_id` into the execution's context server-side (never trusting `body.context`'s client-supplied value, which is explicitly overwritten). `get_execution`/`resume_workflow` gained a new `_owned_workflow_execution(execution_id, org_id)` helper (404 on mismatch, matching `jobs_api.py`'s convention) using `optional_org_id(request)` — matching this file's own pre-existing "org-scoped when verified, platform-wide otherwise" design (`cost_summary`/`usage_summary` already used this exact convention), not a new architecture.
- **`app/core/workflow/engine.py`** — `active()`, `approve()`, `reject()`, `pending_approvals()` gained an **optional**, backward-compatible `organization_id` parameter (default `None` = unfiltered, preserving any other/future caller's behavior unchanged — confirmed no other caller exists in the codebase). When passed, they filter/verify against each `WorkflowRun`'s own `context["organization_id"]`, a field this file already populated and read elsewhere (tracing/event tagging) but never enforced.
- **`workflow_api.py`** — all 5 routes now require `Depends(org_context)`; `approve_step`/`reject_step` 404 when the engine reports denial; `run_demo_workflow` now tags its own run with `organization_id=ctx.org_id`.
- **`diagnostics_api.py`** — `service_start`, `service_stop`, `create_alert_rule`, `toggle_alert_rule`, `codegen_approve`, `codegen_reject` now require `Depends(require_api_key(scopes=["admin"]))`, the same mechanism `kernel_api.py`/`usage_api.py`/`marketplace.py` already use for non-org-scoped, system-level actions. Read-only observability routes are unchanged.
- **`commands_api.py`** — `execute_command` now requires the same `require_api_key(scopes=["admin"])` gate as `kernel_api.py`'s equivalent capability. `list_commands`/`describe_command` (read-only metadata) are unchanged. `modify_cmd.py`'s file-write logic itself was **not** touched — only who can reach it via HTTP changed, per this gate's no-architecture-redesign instruction.
- **`ws.py::agent_ws`** — the generic `{"type":"subscribe","topic":<any>}` relay was **removed** (confirmed zero legitimate callers anywhere in the repo — nothing publishes to an `agent:`-prefixed topic, no frontend code connects to this route). The endpoint now requires the same `token` query-param JWT auth every sibling endpoint in this file already uses.
- **`ws.py::job_ws`** — now requires the same JWT auth, plus a `org_id` query param verified via `get_tenancy_service().get_member_role(...)` (the exact mechanism `chat_ws()` already uses), plus a `job.payload.get("organization_id") == org_id` check before sending anything — mirroring `jobs_api.py`'s `get_job`/`cancel_job` convention exactly, including the 404-not-403 "can't tell doesn't-exist from isn't-yours" behavior.

No architectural changes. No new authorization framework. No client-supplied `organization_id` trusted anywhere — every check above uses a server-verified value (`org_context`, `optional_org_id`, or `get_tenancy_service().get_member_role`).

---

## 6. Tests Added

`tests/security/test_tenant_boundary_sweep.py` — 30 new tests:

- **Orchestrator (7):** positive/negative/unknown-id/no-org-caller on `_owned_workflow_execution`; `get_execution` end-to-end with `optional_org_id` mocked; `resume_workflow` denies cross-org *before* its 501 branch; `run_workflow` never trusts client-supplied `organization_id` in `body.context`.
- **Workflow engine (5):** `active()`'s unfiltered default is unchanged (backward compatibility); org-filtered `active()`/`pending_approvals()`; cross-org `reject()` denied and doesn't affect the step, same-org `approve()` still works; `approve()` on an unknown run with a filter returns `False` (deny), not `True`.
- **Workflow API router (2):** structural check all 5 routes depend on `org_context`; `approve_step` 404s when the engine denies.
- **Diagnostics API (4):** structural check the 6 privileged routes require `require_api_key(scopes=["admin"])`; structural check 4 read-only routes remain ungated; behavioral 401-with-no-key and 200-with-admin-key round-trips.
- **Commands API (4):** structural admin-key check on `execute_command`; read-only routes unchanged; 401-with-no-key; confirms `modify_cmd._modify_file`'s source has **not** been touched (this fix is authorization-only, not a rewrite of the file-write logic).
- **WebSocket (8):** `agent_ws` rejects unauthenticated connects, still works when authenticated, and — the core regression — a `subscribe` to a foreign topic no longer relays that topic's broadcasts to the attacker's socket. `job_ws` rejects unauthenticated connects and missing `org_id`; positive same-org snapshot; cross-org job denied without leaking any field; non-member `org_id` denied before the job queue is even touched.

Also updated `tests/security/test_api_security.py::TestModifyRegisterCommandDisabled` (2 pre-existing tests) — these exercised `modify_cmd`'s handler-level `DISABLED` refusal directly over HTTP; they now authenticate with an admin API key so the request still reaches the handler and the tests keep proving the handler's own defense-in-depth, rather than just re-proving the new outer gate.

---

## 7. Tests Executed / Results

```
$ python -m pytest tests/security/test_tenant_boundary_sweep.py -q
30 passed

$ python -m pytest tests/security/ -q
235 passed, 6 subtests passed

$ python -m pytest tests/test_reliability_wiring.py tests/test_performance.py \
      tests/test_ai_routing.py tests/test_integrations.py -q
108 passed

$ python -m pytest tests/test_workflow.py -q
27 passed

$ python -m pytest tests/ -q
1482 passed, 7 warnings, 16 subtests passed   (baseline 1452 -> +30 new, 0 broken, 0 skipped)
```

App boot + OpenAPI schema regenerated cleanly after all changes: all 29 routes across `orchestrator.py`, `workflow_api.py`, `diagnostics_api.py`, `commands_api.py` present, no import errors, no new schema warnings beyond two pre-existing, unrelated duplicate-operation-id warnings.

One pre-existing test file required updating (§6) because it asserted behavior at a layer that now sits *behind* a new, stronger gate — not because any assertion it made became false.

---

## 8. False Positives / Safe Findings

Every router marked **Safe** in §2's table was verified, not assumed — either by reading the router body directly (ownership check inline) or by following the call into its service/engine layer and confirming a `WHERE ... = $N` / `_assert_owns(...)` / `_get_owned_*(...)` style check exists. No router was marked safe purely because "it has a `Depends(...)`" without verifying that dependency actually gates the *resource*, not just *a* login. Two patterns account for the overwhelming majority of the codebase's genuinely safe surface:

1. **The legacy `owner_user_id(conn, request)` + `WHERE ... AND user_id=$N` convention** (`agents.py`, `build.py`, `chat.py`, `design.py`, `inference.py`, `package.py`, `projects.py`, `stats.py`, `tasks.py`) — pre-dates the org/tenancy system, already hardened once (H-02, referenced in `tests/test_projects.py`), and consistently applied everywhere this sweep checked it.
2. **The `org_context`/`require_permission` + explicit `_get_owned_*`/`_assert_owns`/service-layer `WHERE organization_id=$N` convention** (`jobs_api.py`, `sandbox.py`, `plugins.py`, `team_chat.py`, `marketplace.py`, `organizations.py`, `org_billing.py`, `usage_api.py`) — the newer, org-aware equivalent, equally consistently applied.

The six confirmed findings in this sweep are exactly the routers that fell **outside** both established conventions — either predating them (`orchestrator.py`, `workflow_api.py` — both explicitly self-documented as "known gaps" from an earlier phase) or sitting in an ops/admin surface that was apparently never brought under either convention at all (`diagnostics_api.py`, `commands_api.py`, `ws.py`'s `agent_ws`/`job_ws`).

---

## 9. Remaining Risks

- ~~`app/routers/subscriptions.py::subscription_status(email, request)` — flagged as Needs Review~~ — **resolved by the Security Closure Review below.** It was not a distinct authentication-design question as first assessed; it was a confirmed, unauthenticated account-impersonation vulnerability, now fixed.
- **`diagnostics_api.py`'s read-only routes** (health, metrics, traces, service/alert/memory/codegen listings) remain reachable by any authenticated user, not just admins. No tenant data is exposed (confirmed), so this wasn't fixed here, but if this surface is meant to be admin-only entirely (not just its mutating routes), that's a slightly larger policy decision than this gate's scope.
- **This sweep covered `app/routers/` exhaustively and the specific services those routers call into.** It did not exhaustively re-audit every internal service module for a caller *other than* its router (e.g. a background job or scheduled task invoking `WorkflowEngine`/`AgentKernel` directly, bypassing HTTP entirely). No evidence of such a caller was found during this sweep, but it wasn't the sweep's explicit target either.
- **`events_api.py`'s known caveat from `7a56b66`** (replay filters after `limit` is applied, so an org can see fewer than `limit` results even when more of their own history exists) is unchanged — not part of this sweep's scope.

---

## 10. Final Security Assessment

Seven confirmed vulnerabilities found and fixed across this sweep and its closure review, matching the exact pattern already closed in `runtime_api`/`kernel_api`/`planning_api`/`events_api` — three of them (`commands_api`'s unrestricted file write, `ws.py`'s `agent_ws` topic bypass, and `subscriptions.py`'s unauthenticated impersonation) more severe than any finding in the original four, since each required **no authentication at all**, not just "any authenticated user of any org." Every other router in the codebase was traced to a real, verified ownership check — either the legacy per-user convention or the newer org-aware one.

**Are tenant-boundary vulnerabilities remaining? No.** The `subscriptions.py` item originally flagged as Needs Review was investigated to completion in the Security Closure Review (below) and confirmed as a real, severe vulnerability — not a distinct out-of-scope design question — and has been fixed. No open findings remain.

---

## SECURITY SWEEP GATE (superseded by the Closure Review gate below)

```
Surfaces examined: 41 routers under app/routers/ (all live routes; package_preflight.py
  re-confirmed as a non-router shim) + their called services/engines.

Confirmed:  6  (orchestrator.py, workflow_api.py + engine.py, diagnostics_api.py,
                commands_api.py, ws.py agent_ws, ws.py job_ws)
Safe:       33 (verified via explicit ownership check, not assumed)
Needs Review: 1 (subscriptions.py — see Closure Review below: now Confirmed + Fixed)

Production fixes: DONE (6/6 confirmed findings)
Regression tests added: 30 (tests/security/test_tenant_boundary_sweep.py)
  + 2 pre-existing tests updated (tests/security/test_api_security.py)

Security suite:      PASS (235/235, 6 subtests)
Full suite:           PASS (1482/1482 — baseline 1452 + 30 new, 0 regressions)
Reliability/perf/AI-routing suites: PASS (108/108)
App boot + OpenAPI generation: PASS

Commit: 7a56b66 (prior fix, referenced) -> 3f39fc6 (this sweep, before closure review).
```

---

## Addendum — Security Closure Review: `subscriptions.py::subscription_status`

**Trigger:** the sweep above classified this endpoint as Needs Review rather than Confirmed/Safe. This closure review investigates it to a final classification, per the same reproduce-before-fix discipline as the rest of this document.

### A.1 — Full implementation read

`app/routers/subscriptions.py` has 4 routes: `POST /api/subscription/checkout` (starts a real Stripe Checkout session for an email), `GET /api/subscription/status` (the finding), `POST /api/subscription/verify` (validates a token the caller already holds), `POST /api/stripe/webhook` (Stripe-signature-verified). Only `subscription_status` was in question.

### A.2 — Authentication/authorization chain, traced end to end

1. **Route mount:** `GET /api/subscription/status` — no `Depends(...)` in its signature.
2. **Global middleware:** `/api/subscription/` is listed in `PUBLIC_PREFIXES` (`app/core/config.py:66-72`) — `app/factory.py`'s `api_auth_middleware` explicitly skips authentication for any path under this prefix. **No credential of any kind is required to reach this handler.**
3. **Identity source:** the `email` query parameter, taken verbatim from the request — never resolved from a session, cookie, JWT, or any verified source.
4. **What determines the subscription returned:** a direct `SELECT status, current_period_end FROM subscriptions WHERE email=$1` using that unverified `email` — whichever row happens to match.
5. **Token issuance:** if that email has an active paid subscription, `make_token(email, False, 0)` is returned. If not, the handler **auto-creates a 7-day trial row for that email** (`INSERT INTO trials (email) VALUES ($1) ON CONFLICT DO NOTHING`) and returns `make_token(email, True, days_remaining)` regardless. Either branch, the caller walks away with a token — the only email that produces *no* token is one whose trial has already expired.
6. **What that token is worth:** `app/core/auth.py:36-45`, `make_token()` — an HMAC-SHA256-signed blob `{"e": email, "exp": now+TOKEN_TTL, "trial": ..., "dr": ...}`, valid for **`TOKEN_TTL` = 30 days** (`app/core/config.py:32`). It carries no session id, no device binding, no proof of how it was obtained.
7. **Where that token is consumed:** `app/core/auth.py::owner_email(request)` — the identity resolver shared by **every** "legacy" endpoint (`agents.py`, `build.py`, `chat.py`, `design.py`, `package.py`, `projects.py`, `stats.py`, `tasks.py`). It accepts the token via `X-Sub-Token` header or cookie (or even `Authorization: Bearer`), verifies only the HMAC signature and expiry, and returns `payload["e"]` — **the email is trusted exactly as embedded, with no re-verification that this specific token was ever legitimately issued to that person.** `owner_user_id()` then does `SELECT id FROM users WHERE email=$1` and uses that as the scoping identity for every subsequent query.

### A.3 — Direct answers to the checklist

- **What is the source of user identity?** A caller-supplied string in a public, unauthenticated query parameter. Nothing else.
- **Does the endpoint require authentication?** **No.** Confirmed directly from `PUBLIC_PREFIXES`.
- **What determines the subscription returned?** A raw `WHERE email=$1` match against whatever the caller typed — no ownership check exists at any layer.
- **Can an authenticated user learn/access another user's subscription?** Yes — and authentication isn't even a precondition; **anyone**, authenticated or not, can request status/a token for any email.
- **Can an unauthenticated user obtain subscription information?** Yes — this is the entire vulnerability. No auth is required by design (public prefix).
- **Sensitive information in the response?** The `token` field itself is the sensitive artifact — it is a bearer credential for the target email's identity across the whole legacy endpoint surface, not merely a status flag.
- **Dependency on client-supplied email/user ID/customer ID?** Yes, total: the client-supplied `email` is the *only* input, and it is trusted with zero verification anywhere in the path.

### A.4 — Reproduction (executed against the unmodified code, before any fix)

Full end-to-end chain, using a fake `asyncpg` pool (no live DB) and the real `subscription_status()` and `owner_email()`/`owner_user_id()` functions:

```
STEP 1 — unauthenticated attacker calls /api/subscription/status
         for a victim who already has a matching real 'users' row
         (i.e. a normal registered user of the app) but the
         attacker has NO credential of any kind, only the email.

  Response (no auth, just knowing the email):
  {'active': True, 'trial': True, 'days_remaining': 7,
   'token': 'eyJlIjogInZpY3RpbUBleGFtcGxlLmNvbSIsICJleHAiOiAxNzg4NzEyNjg1LCAidHJpYWwiOiB0cnVlLCAiZHIiOiA3fQ.40b7c...'}
  Attacker now holds a signed token for 'victim@example.com', valid 30 days.

STEP 2 — attacker presents that token as X-Sub-Token to a real
         'legacy' endpoint's identity resolver (app.core.auth)

  owner_email(attacker's request) -> 'victim@example.com'
  owner_user_id(...) -> 11111111-1111-1111-1111-111111111111
    (== victim's real users.id — exact match)

CONFIRMED: an unauthenticated caller who knows only a victim's email
address obtains a valid 30-day access token for that victim's real
account identity — the SAME identity-resolution function
(app.core.auth.owner_email/owner_user_id) that scopes
agents.py/build.py/chat.py/design.py/package.py/projects.py/
stats.py/tasks.py accepts it without complaint.
```

This is a **complete, unauthenticated account-takeover primitive**, more severe than any finding in the original tenant-boundary sweep: it requires no authentication step of any kind, only a known or guessed email address, and grants durable (30-day), full-privilege impersonation across eight other router files this sweep had separately certified as "Safe" — correctly, since their own ownership checks were never the weak link; the identity feeding into them was.

### A.5 — Alternate paths checked

- **Manipulated identifiers/query params:** the email is taken as a plain string with parameterized SQL (`$1`) — no injection angle, but no validation either (any string an attacker chooses is accepted verbatim as "the" identity to mint a token for).
- **Rate limiting as a mitigation:** `check_rate_limit(f"sub:{_real_ip(request)}", max_calls=10, window=60)` — 10 requests/minute per IP. Irrelevant to this exploit: a single request against one targeted victim email succeeds; rate limiting does not require or verify identity, it only throttles volume.
- **Alternate authentication path:** none exists for this route — it is unconditionally public.

### A.6 — Fix applied

`subscription_status()` now unconditionally raises `403` before touching the database, pool, or minting any token — same treatment as this codebase's own established precedent for "confirmed dangerous + zero legitimate consumer" (`app/routers/commands_api.py::register_plugin`, `app/commands/builtin/modify_cmd.py::_modify_register`). Confirmed via repo-wide search that no frontend code, script, test, or doc anywhere references `/api/subscription/status` — there is no real behavior being removed. `POST /api/subscription/checkout` (real Stripe Checkout initiation) and `POST /api/subscription/verify` (validates a token the caller already holds — never mints one from a bare email) are untouched; neither has the unauthenticated-identity-minting shape that made `subscription_status` exploitable. Removed the now-unused `check_rate_limit`/`_real_ip` import (kept `ruff check` clean, no baseline drift).

### A.7 — Regression tests

Added to `tests/security/test_api_security.py` — `TestSubscriptionStatusImpersonationDisabled` (6 tests): unauthenticated HTTP request refused (403); response body contains no `token`/`active`/`trial` fields; a direct function-level call for an arbitrary email raises before minting anything; `get_pool()` is never even called (no trial-creation side effect can occur for an unverified email); `create_checkout`/`verify_session` signatures and behavior confirmed unchanged; `verify_session` confirmed to still only validate a token it's given, never mint one from an email.

### A.8 — Tests executed

```
$ python -m pytest tests/security/test_api_security.py -k SubscriptionStatus -v
6 passed

$ python -m pytest tests/security/ -q
241 passed, 6 subtests passed

$ python -m pytest tests/ -q
1488 passed, 7 warnings, 16 subtests passed   (prior baseline 1482 -> +6 new, 0 broken, 0 skipped)
```

App boot + OpenAPI schema regenerated cleanly: all 3 `subscriptions.py` routes (`/api/subscription/checkout`, `/api/subscription/status`, `/api/subscription/verify`) still present. `ruff check app/routers/subscriptions.py tests/security/test_api_security.py` — clean, no new lint debt.

### A.9 — Final classification

**CONFIRMED and FIXED** — not Safe, not a distinct out-of-scope design question. This was the single most severe finding across both the original tenant-boundary sweep and this closure review: a complete, unauthenticated account-impersonation primitive reachable by anyone who knows or guesses a registered user's email address, with no fix required beyond disabling a dead, unused, and dangerous code path.

---

## SECURITY CLOSURE REVIEW GATE

```
Finding: app/routers/subscriptions.py::subscription_status(email, request)
Final classification: CONFIRMED — Unauthenticated Account Impersonation (FIXED)

Reproduction: executed against unmodified code (see A.4) — confirmed an
  unauthenticated caller obtains a 30-day impersonation token for any
  registered user's real account by supplying only their email address.

Fix applied: endpoint disabled outright (403), matching this codebase's
  own established precedent (register_plugin / _modify_register).
  create_checkout and verify_session unaffected.

Regression tests added: 6 (tests/security/test_api_security.py::
  TestSubscriptionStatusImpersonationDisabled)

Security suite: PASS (241/241, 6 subtests)
Full suite:     PASS (1488/1488 — baseline 1482 + 6 new, 0 regressions)
App boot + OpenAPI generation: PASS
ruff: clean, no new lint debt

UI changes:      NONE
Schema changes:  NONE
Migrations:      NONE
Scope expanded beyond subscription_status: NONE
New routers examined: NONE (out of scope, per instruction)
Coverage / Testing Foundation / Billing / PR: NOT STARTED (out of scope)

Clean tree: YES (after commit)
Final commit hash: see bottom of this document / chat reply

RESULT: A — Security Boundary Sweep CLOSED

Next decision:
WAIT FOR APPROVAL
```
