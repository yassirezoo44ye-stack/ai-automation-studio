# Testing Foundation Audit

**Status:** Audit only. No code, CI, test, or configuration changes were made while producing this document.
**Scope:** Verification of the prior Testing Coverage Audit's claims against current source, plus a prioritized decision matrix.
**Baseline at time of audit:** P0 Context Budgeting merged (commit `12ddf3c`), 1452/1452 tests passing, no P1 implementation started.

---

## 1. Executive Summary

The repo has real, structured tests in specific areas (security suite, architecture layer, several routers) but **no working coverage measurement anywhere** — the number "how much is tested" is currently unknowable, not just low. Three findings matter most:

1. **Coverage tooling is installed but never invoked.** `pytest-cov` sits unused in CI; the frontend's `vitest` coverage config actively excludes `src/renderer/features/**` — the majority of the app — from the one place coverage numbers could come from.
2. **Billing has structural tests, not behavioral tests.** Every existing "billing test" for `stripe_plans`, `invoices`, and `coupons` checks a dict shape or greps a function's source text (`inspect.getsource(...)`) — none of them call the async methods that actually talk to Stripe or Postgres. `credits.py`, `payment_methods.py`, `portal.py` have no test references at all.
3. **Four mounted routers have no per-route authorization**, not just no tests. `kernel_api`, `planning_api`, `runtime_api`, and `events_api` rely entirely on the global `/api/`-prefix auth middleware for authentication, with zero org-scoping in the handlers themselves. `runtime_api` in particular has an unverified-ownership IDOR shape: execution status/report/artifacts/cancel are all keyed only by `execution_id`, with no check that the caller's org owns that execution.

One correction to the prior audit: `app/routers/package_preflight.py` is **not** a live router — it's a 10-line backward-compat re-export shim with no `@router` decorators and no `include_router()` call in `app/factory.py`. The real 9th "untested router" candidate doesn't exist; the mounted, untested count is **8 routers**, and the module actually worth testing is `app/runtime/preflight.py` (308 lines, imported by one test file for two class names only — not behaviorally tested either).

---

## 2. Coverage Infrastructure Audit

### Backend

| Question | Answer | Evidence |
|---|---|---|
| Is `pytest-cov` installed? | Yes | `requirements-dev.txt:4` — `pytest-cov>=5.0 # coverage measurement (pytest --cov=app)` |
| Does CI run it with `--cov`? | **No** | `.github/workflows/ci.yml`'s "Unit tests" step runs `python -m pytest tests/ -v --tb=short` — no `--cov` flag anywhere in the file |
| Is there a threshold? | No | No `--cov-fail-under`, no `.coveragerc`, no `pyproject.toml` coverage config in the repo |
| Is there a coverage artifact? | No | No `coverage.xml`/`.coverage`/HTML report is generated or uploaded by any workflow step |

The comment on `pytest-cov`'s line (`# coverage measurement (pytest --cov=app)`) documents the intended usage — it was never wired in. This is a one-line CI gap, not a missing-dependency gap.

### Frontend

| Question | Answer | Evidence |
|---|---|---|
| Is Vitest coverage installed? | Yes | `package.json` devDependencies: `"@vitest/coverage-v8": "^4.1.9"` |
| Is there an npm script to run it? | **No** | `package.json` scripts only define `"test": "vitest run"` and `"test:watch": "vitest"` — no `"coverage"` or `"test:coverage"` script exists. `--coverage` is not passed anywhere, including in `ci.yml`'s `Vitest unit tests` step (`npm test`, i.e. plain `vitest run`) |
| What is `coverage.include` set to? | `["src/renderer/shared/**", "src/renderer/contexts/**"]` | `vite.config.ts:36-40` |
| Is `src/renderer/features/**` excluded? | **Yes, explicitly** | Not present in the `include` array. `features/` holds 17 feature areas and the large majority of `.tsx`/`.ts` source (billing, ai-routing, design-studio, sandbox, marketplace, etc.) |
| False confidence risk? | **Yes, on both sides** | Backend: a developer could believe "we have pytest-cov" means coverage is tracked — it isn't run. Frontend: even if someone manually ran `vitest run --coverage` today, the report would show high-looking percentages while silently measuring only `shared/` and `contexts/` (which do have decent test density) and ignoring `features/` (which mostly doesn't) — a partial number that reads as a whole-app number. |

**Conclusion:** both "coverage %" numbers this project could currently produce are not trustworthy — one because it's never generated, the other because it's scoped to a fraction of the codebase without saying so anywhere visible.

---

## 3. Backend Coverage Gaps

Re-verified by grepping module stems against all of `tests/`. Confirmed zero textual reference for (selection relevant to this gate — full list available on request):

- `app/agents/builtin/{build,evolve,help,modify}_agent.py`
- `app/ai/arabic_nlu.py`
- `app/commands/builtin/{deploy,help,inspect}_cmd.py`, `app/commands/plugins/example_greet.py`
- `app/core/ai/orchestrator/coordinator.py`
- `app/core/cache/{invalidation,redis_adapter}.py`
- `app/core/maintenance.py`
- `app/execution/drivers/{python_script,python_server}.py`
- `app/kernel/agents/command_agent.py`, `app/kernel/self_modify.py`
- `app/marketplace/changelog.py`
- `app/plugins/provider_types.py`
- `app/routers/{ai_router_api,events_api,jobs_api,kernel_api,planning_api,runtime_api,usage_api,workflow_api}.py`
- `app/runtime/control_plane.py`
- `app/services/system_metrics.py`

This is a textual-reference check (module stem appears somewhere in `tests/`), not a line-coverage measurement — see §2 for why an actual number isn't available yet. It's a reasonable proxy for "nothing exercises this file at all" but can't distinguish "well tested" from "imported once, asserted nothing."

---

## 4. Billing Risk Assessment

Reviewed every file in `app/billing/` directly (not just grep counts).

| Module | Lines | Real behavioral test? | What exists instead | Sensitive operations |
|---|---|---|---|---|
| `credits.py` | 113 | **None** | Nothing | `grant()` calls live `stripe.Customer.create_balance_transaction` (mutates real Stripe balance) then writes a ledger row; `get_balance_cents()` reads live Stripe balance with a silent fallback to summing the local ledger on any exception |
| `payment_methods.py` | 131 | **None** | Nothing | `sync_for_org()` calls `stripe.PaymentMethod.list` + `stripe.Customer.retrieve`, then does an INSERT/ON CONFLICT + soft-delete pass keyed on which Stripe IDs it saw; `mark_default()` does a two-statement (not single-statement) default-flag flip — a crash between the two `UPDATE`s leaves zero or two default methods |
| `portal.py` | 25 | **None** | Nothing | `create_portal_session()` calls live `stripe.billing_portal.Session.create` — one branch (`NoStripeCustomer`) is the only error path, untested |
| `coupons.py` | 94 | Structural only | `test_enterprise.py:631-635` — `inspect.getsource(CouponService.record_stripe_coupon)` string-checks that a guard clause literal is present; `test_enterprise.py:787-796` — asserts `coupons` is *absent* from the RLS-scoped table list (a schema-policy check, not a coupon-logic check) | `get_by_code()`, `list_active()`, `deactivate()` — none exercised against a fake pool |
| `invoices.py` | 238 | Structural only | `test_enterprise.py:596-606` — asserts the `_STATUS_TO_PAYMENT_STATUS` dict covers 5 known Stripe statuses and maps only into 4 allowed values; `test_enterprise.py:608-618` — `inspect.getsource(...)` checks the literal string `"DELETE FROM payments WHERE invoice_id=$1"` is present in `upsert_from_stripe_invoice`'s source, as a regression guard against a specific past duplicate-row bug | The actual transactional upsert (invoice + line-item replace + derived-payment row, 3 statements in one `conn.transaction()`) is never run against even a fake pool; `backfill_from_stripe()` (live `stripe.Invoice.list` pagination) is untested |
| `stripe_plans.py` | 31 | Real, but trivial | `test_enterprise.py:580-590` — `test_price_lookup_symmetry` and `test_enterprise_not_purchasable` actually call `price_id_for`/`plan_for_price`-adjacent dicts | Lowest risk of the six — pure dict lookups, no I/O |
| `plan_service.py` | 163 | Partial | `test_feature_gate.py` patches `get_plan_service`; `test_enterprise.py:620-629` tests `_row_to_plan`'s cents→USD conversion | Reasonable coverage already |
| `webhooks.py` | 129 | Good | 5 test files reference it, including a dedicated `tests/security/test_webhook_security.py` | Reasonable coverage already |
| `usage.py` | 315 | Good | 8 test files reference it | Reasonable coverage already |

**Highest-risk functions, ranked:**
1. `credits.CreditService.grant()` — the only function in the billing module that both mutates a live Stripe customer balance *and* writes a local audit row, with no test verifying the two stay consistent, that negative amounts (consumption) work, or that the try/except around the Stripe call actually degrades as documented.
2. `payment_methods.PaymentMethodService.mark_default()` — the two-statement default-flip has an interrupted-write failure mode (no default, or two defaults) that's straightforward to catch with a fake-pool test but isn't caught today.
3. `invoices.InvoiceService.upsert_from_stripe_invoice()` — the most complex single operation in the billing module (3 statements, 1 transaction, idempotency depends on delete-then-insert ordering per its own code comment) and the *only* thing guarding its correctness today is a string-search over the function's source, which would still pass if the DELETE were present but in the wrong place relative to the INSERT.

**External dependencies requiring mocks (none currently mocked for these paths):**
- `stripe.Customer.create_balance_transaction`, `stripe.Customer.retrieve` (`credits.py`)
- `stripe.PaymentMethod.list`, `stripe.Customer.retrieve` (`payment_methods.py`)
- `stripe.billing_portal.Session.create` (`portal.py`)
- `stripe.Invoice.list` (`invoices.py`, backfill path)
- `asyncpg.Pool`/`asyncpg.Connection` for all five (INSERT/UPDATE/transaction calls)

**Existing reusable pattern (not a shared fixture, but a proven idiom to copy):** `tests/test_idempotency.py`'s `FakeIdempotencyPool` and `tests/test_integration_webhook_recovery.py`'s `FakeWebhookPool`/`FakeWebhookConn` — both hand-roll an in-memory stand-in for `asyncpg.Pool`/`Connection` that pattern-matches on normalized query text (`_norm(query)` strips whitespace, then `.startswith(...)` checks). No project-wide `conftest.py` fixture exists for this — each test file defines its own Fake*Pool class. A billing test suite would either follow this per-file convention or be the first to promote it into a shared `tests/conftest.py` fixture (a small design decision that itself belongs to implementation, not this audit).

**Stripe test-mode note:** `stripe` package usage throughout billing always uses whatever `stripe.api_key` is configured; `tests/test_config_startup.py` already establishes the pattern of `patch("stripe.api_key", "", create=True)` to keep tests from touching a real key. Any future billing test must mock the `stripe.*` call sites directly (per above) rather than relying on an empty API key to fail closed — an empty key can still attempt a network call depending on the `stripe` SDK version's behavior, which is not something to leave to chance for a suite that must never cause a real charge.

---

## 5. Mounted Router Coverage

Verified against `app/factory.py`'s actual `include_router(...)` calls (line refs below), not against the file's existence alone.

| Router | Mounted at (factory.py) | Endpoints | Per-route auth/org-scope | Highest-risk endpoint |
|---|---|---|---|---|
| `ai_router_api` | `:541` | 7 GET + 1 POST under `/api/ai/*`, `/api/orgs/{org_id}/ai/costs` | **Yes** — `Depends(org_context)` on the org-costs route | `GET /api/orgs/{org_id}/ai/costs` — the file's own docstring/comment flags this as the route where "any authenticated caller read another org's spend" was a real past concern; it's the one route in this set with an explicit fix already in place, worth a regression test to keep it that way |
| `events_api` | `:542` | `GET /stats`, `/replay`, `/dlq` under `/api/events` | **None** — no `Depends(...)` at all in the file | `GET /replay` — replays internal event-bus history (`since_ts`, `type_prefix`, `limit`) to any authenticated caller regardless of org; no tenant filter on event contents |
| `jobs_api` | `:534` | POST/GET/DELETE under `/api/jobs` | Yes — `Depends(org_context)` on every route, per the file's own header comment documenting a prior unauthenticated-access bug that this fixed | `DELETE /{job_id}` — already org-scoped; lowest residual risk of this set precisely because it was already hardened |
| `kernel_api` | `:526` | `POST /execute`, `GET /status`, `/state`, `/modifications`, `POST /rollback/{index}`, `GET /agents` under `/api/kernel/*` | **None** — no per-route `Depends(...)` | `POST /api/kernel/execute` — accepts a free-text `input` string routed into the AI Kernel's command pipeline (which reaches `SelfModifyingEngine`, §6); any authenticated caller, any org, can issue kernel commands with no org partition visible in the router itself |
| `planning_api` | `:528` | `POST /analyze`, `/execute`, `GET /{plan_id}`, `POST /validate` under `/api/plan` | **None** | `POST /execute` — analyzes *and executes* a goal via `AgentKernel`; `_plan_cache` is a single process-wide `dict[str, dict]` with no org key, so `GET /api/plan/{plan_id}` can retrieve any org's cached plan if the (non-namespaced) `plan_id` is known or guessed |
| `runtime_api` | `:524` | 9 routes under `/api/runtime/*` (execute, status, report, artifacts, cancel, cache, runtimes) | **None** | `GET /api/runtime/{execution_id}/status`, `/report`, `/artifacts/{artifact_id}`, and `DELETE /{execution_id}` — all four look up `_executions[execution_id]` (a process-wide dict) or `ArtifactSystem.load(execution_id)` with **no ownership check against the caller's org at all**. This is the clearest IDOR shape found in this audit: possession of an `execution_id` is sufficient to read another org's execution report, download its artifacts, or cancel its run. |
| `usage_api` | `:539` | 5 routes under `/api/*` (plans, admin/plans, orgs usage) | **Yes** — mixes `require_api_key(scopes=["admin"])` and `require_permission("billing", "manage")` per route | Already the best-guarded router of the 8; a smoke test here is about regression-locking the auth mix, not closing a gap |
| `workflow_api` | `:533` | 5 routes under `/api/workflows/*` | Partial — file's own header comment documents that authentication exists but "WorkflowRun/the approval [flow] never verify the run belongs to the caller's org," tracked as a separate known issue | `POST /approvals/{run_id}/{step_id}/approve` and `/reject` — per the code's own comment, any authenticated user can approve/reject any org's workflow step today; this is a pre-existing, self-documented gap, not new to this audit |

**Correction to prior audit:** `app/routers/package_preflight.py` (10 lines) is a backward-compat shim re-exporting from `app.runtime.preflight` — it has no `@router` object and is not imported or mounted in `app/factory.py`. It should be dropped from the "untested mounted router" list. The module actually worth attention is `app/runtime/preflight.py` (308 lines; only referenced for two class-name imports in `tests/test_runtime.py`, not behaviorally tested), which backs `runtime_api`'s execute-time tool checks.

**Existing reusable fixture:** `TestClient` (FastAPI) is already used in 9 test files; `tests/test_api_medium.py` and `tests/test_api_auth.py` are the closest models for a router smoke-test file (12 and 15 `client.get/post/...` calls respectively). No dedicated pytest fixture wraps `TestClient` construction — each file instantiates it directly against the app from `app.factory` or `main`.

---

## 6. Infrastructure-Critical Gaps

Classified by business/security/runtime blast radius if the module silently breaks, not by line count.

| Module | Lines | Classification | Why |
|---|---|---|---|
| `app/kernel/self_modify.py` | ~200+ (read: patch/append/prepend/replace/create ops) | **Critical** | This is the mechanism that lets the running system rewrite its own source files on disk (find/replace, full overwrite, file creation), gated by a `PolicyEngine.check_write()` call and a SHA-256/backup safety net. It is reachable today from `kernel_api`'s `POST /api/kernel/execute`, which (§5) has no org-scoping. A bug here — or a policy-check bypass — doesn't corrupt one org's data, it corrupts the running application for everyone. Zero test references. |
| `app/execution/drivers/python_script.py` / `python_server.py` | 70 / 203 | **Critical** | These are the drivers that actually spawn and stream user/generated project code (`python_server.py` additionally does `pip install -r requirements.txt` unattended and allocates a network port before the process is proven safe). Runtime correctness here directly gates whether the core product function ("run the thing I built") works at all; the port-allocation/cleanup and process-liveness (`_wait_ready`) paths have several early-return branches that are easy to regress silently. Zero test references. |
| `app/core/cache/redis_adapter.py` | 400 | **High** | Every cache read/write in the app funnels through this — including `invalidation.py`'s cross-instance pub/sub. A backend-selection bug (Redis vs. in-process fallback) or a serialization bug here doesn't crash loudly; it produces stale reads across every feature that uses `cached()`. Silent-failure risk is high precisely because the fallback path is designed to degrade quietly. Zero test references. |
| `app/core/cache/invalidation.py` | 99 | **High** | Directly depends on `redis_adapter.py`; its entire purpose (cross-instance cache coherency via pub/sub) is invisible in a single-process dev/test run, meaning a regression here would likely only surface in a multi-instance production deploy — exactly the scenario this project's tests can't currently reach without a mock. Zero test references. |
| `app/runtime/control_plane.py` | ~150 | **Medium** | A stateless facade (`can`/`require`/`getCapabilities`) over `app.runtime.registry`, which itself runs `discover()` at startup. Correctness bugs here produce misleading "tool available" answers rather than data loss or security exposure — annoying, not dangerous. Its `_FIX_HINTS` dict is static content, low regression risk. Zero test references, but also the lowest-consequence module in this set. |
| `app/core/ai/orchestrator/coordinator.py` | 136 | **Medium** | Connects scheduled tasks to the agent/inference pipeline and emits lifecycle events + cost records. A bug here means a task silently runs through the wrong pipeline or a `CostRecorded` event is missed (billing-adjacent, but downstream of `app/billing/usage.py`, which *is* tested) — real but bounded impact. Zero test references. |
| `app/core/maintenance.py` | 167 | **Medium** | Self-healing: rolling error-window alerting (`record_error`) and a `with_retry` backoff wrapper for transient DB errors. If this silently breaks, the system doesn't fail — it just stops alerting/retrying, which delays detection of *other* problems rather than causing one directly. Straightforward to unit test (pure function + a fake failing coroutine) whenever it's picked up. Zero test references. |

---

## 7. Frontend Coverage Gaps

Re-verified `src/renderer/features/` directly rather than trusting file counts alone.

- **17 feature directories total; 2 have any test file** (`design-studio`: 5 test files covering tokens/eventBus/exportPipeline/commands/componentLibrary; `auth`: 1 test file for `AuthPage`). The other 15 — including `billing` and `ai-routing` — have zero.
- **`billing/`** (6 tab components + `BillingPage.tsx`): `PaymentMethodsTab.tsx` and `SubscriptionTab.tsx` both reference Stripe client-side (confirmed by grep) — meaning the frontend half of the exact backend gap identified in §4 (`payment_methods.py`, `portal.py`) is also untested. This is the single largest compounding risk in the whole audit: neither side of "change a payment method" or "switch plans" is covered anywhere in the stack.
- **`ai-routing/`** (5 tabs — Budgets, Models, CostAnalytics, Providers, UsageReports + `AIRoutingPage.tsx`): zero tests, and it's the UI surface for `ai_router_api` (§5), which is one of the two better-guarded routers on the backend — so this is UI-only risk, not a compounded gap like billing.
- **Context providers:** `AppContext`, `AuthContext`, `OrgContext`, `LangContext`, `ToastContext` have no tests; `CopilotContext` and `NotificationContext` do. `AuthContext`/`OrgContext` are the two with the clearest security/business relevance (session and tenant identity respectively) and are worth flagging even though they weren't explicitly named in the prior audit's context list.
- **Highest business/security impact ranking:** `billing` (compounds with backend gap, real money) > `ai-routing` (cost-control UI, no compounding backend gap) > `sandbox`/`plugins` (executes/loads less-trusted content, worth a future look but out of today's scope) > the rest.

---

## 8. E2E Gap

Confirmed: no Playwright, Cypress, or any other E2E framework exists in the repo. `playwright>=1.61.0` in `requirements.txt` is a backend runtime dependency for `app/agents/builtin/browser_agent.py` (an agent capability), not a test tool — it has no test-side usage. All frontend tests are Vitest + Testing Library component/hook-level tests; nothing boots the app end-to-end.

**Is a Login → Create Project → Run Agent → View Result smoke flow worth being a future release gate?** Yes, on the evidence gathered in this audit specifically: §5 and §6 both surface gaps that are *integration*-shaped, not unit-shaped — the `runtime_api` IDOR issue only exists at the seam between "who's logged in" and "whose execution is this," and the `python_server`/`python_script` driver risk only manifests when a real project is actually run end-to-end. A unit test suite, however complete, structurally cannot catch either class of bug. This makes the case for a thin E2E smoke test stronger than a generic "more E2E coverage is good practice" argument would. That said, per this gate's scope, this is a recommendation to weigh later (§10), not an action taken now.

---

## 9. Risk Matrix

| Area | Risk | Current Tests | Business Impact | Security Impact | Recommended Priority |
|---|---|---|---|---|---|
| Billing: `credits.py`, `payment_methods.py`, `portal.py` | High | None | High — real money, real payment data sync | Medium — Stripe is source of truth, but local ledger/cache drift is a customer-facing trust issue | **P1** |
| Billing: `coupons.py`, `invoices.py` | Medium | Structural only (source-grep / dict-shape) | High (invoices) / Medium (coupons) | Low | **P1** (bundled with above) |
| `runtime_api` cross-org IDOR shape | High | None | Medium — leaks execution reports/artifacts | **High** — direct tenant-isolation bypass on a mounted, reachable endpoint | **P0-adjacent** (see below) |
| `kernel_api` unscoped self-modify access | High | None | Low (single-tenant-ish blast, since it affects the whole running app) | **High** — reaches `SelfModifyingEngine` with no org gate | **P0-adjacent** |
| `events_api`, `planning_api` (no org-scoping) | Medium | None | Low–Medium | Medium — cross-org data visibility (`replay`), cross-org plan-cache read | P2 |
| Coverage infrastructure (backend `--cov`, frontend `include`) | Structural (enables/blocks everything else) | N/A | None directly | None directly | **P0** (informational only, per your explicit instruction) |
| `app/core/cache/redis_adapter.py`, `invalidation.py` | Medium-High | None | Medium — silent stale-data class of bugs | Low | P3 |
| `app/kernel/self_modify.py` | High | None | Low | High (see above — bundled with kernel_api) | P2 |
| `app/execution/drivers/python_{script,server}.py` | Medium-High | None | High — core "run my project" path | Low | P3 |
| Frontend `billing/` | High (compounds backend) | None | High | Low | P4 |
| Frontend `ai-routing/` | Medium | None | Medium | Low | P5 |
| E2E smoke flow | Medium (structural gap) | None | Medium | Medium | P6 (evaluate later) |

**Smallest intervention with the highest value:** wiring `pytest --cov=app --cov-report=term-missing` into CI as an informational-only step. It is a one-line CI change, touches no application code, cannot fail the build (no threshold), and immediately converts every "we think X is untested" claim in this document (and every future one) from a grep-based inference into a verifiable number. Every other item in this matrix becomes easier to prioritize correctly once this exists — including deciding whether the `runtime_api`/`kernel_api` authorization gaps (which are correctness/security findings, not test-coverage findings) get escalated ahead of the roadmap below.

**Flag, not a recommendation to act now:** §5's `runtime_api` and `kernel_api` findings are authorization gaps discovered *while auditing test coverage*, not testing gaps themselves — no test would have caught a missing `Depends(org_context)`. They're included here for visibility because they're more urgent than anything else in this document, but fixing them is application-code work explicitly out of scope for this gate. Recommend raising them as their own decision separately from the testing roadmap.

---

## 10. Recommended Testing Roadmap

Candidate order carried forward from the request, evaluated against what this audit actually found:

- **P-Test-0 — Wire real coverage measurement (informational only).** Confirmed still correct and now the clear top pick independent of everything else: backend `pytest --cov=app --cov-report=term-missing` (no `--cov-fail-under`), frontend `coverage.include` widened to `src/renderer/**` (or at minimum add `src/renderer/features/**`) with no `npm run test` gate change. No threshold in the first step — the project has no baseline number yet, so a threshold would be arbitrary.
- **P-Test-1 — Billing behavioral tests.** Order within this item should change slightly from the original guess: `credits.py` and `payment_methods.py` first (zero coverage, real Stripe mutation calls), `portal.py` third (zero coverage but only 25 lines / 1 function), then `invoices.py` (has partial structural coverage worth *replacing* with real behavioral tests — the regression test at `test_enterprise.py:608-618` is a good regression guard to keep, but should be supplemented, not treated as sufficient), then `coupons.py` last (smallest blast radius of the six).
- **P-Test-2 — Smoke coverage for the 8 mounted routers** (corrected from 9 — see §5's `package_preflight` correction). Still valid, but flag that `runtime_api` and `kernel_api` smoke tests will surface the §5/§9 authorization gaps immediately (a 200 where a 403 was expected) — decide ahead of time whether that's treated as a test *finding* to report, or whether the fix should land first. Recommend writing the smoke tests to assert current behavior and marking the org-scoping gaps explicitly with a `# TODO / KNOWN GAP` comment referencing this document, rather than silently asserting the insecure behavior as correct.
- **P-Test-3 — Cache layer** (`redis_adapter.py`, `invalidation.py`). Confirmed still appropriately ordered — real risk, but lower urgency than billing or the router auth-adjacent findings.
- **P-Test-4 — Frontend billing + AI routing.** Confirmed, with billing ahead of ai-routing given the compounding backend gap found in §7.
- **P-Test-5 — Thin E2E smoke flow.** Confirmed as a later-stage item; §8 found concrete evidence (`runtime_api` IDOR, driver reliability) that strengthens the case for eventually doing this, without changing its position in the sequence.

No candidate item's relative order needed a structural change from what was proposed; the audit refined *why* each ranks where it does and corrected the router count.

---

## 11. Minimal First Implementation

**P-Test-0, backend half only:** add a `--cov=app --cov-report=term-missing` flag to the existing `python -m pytest tests/ -v --tb=short` invocation in `.github/workflows/ci.yml`'s "Unit tests" step. No new step, no new job, no threshold, no artifact upload. This is the smallest possible change that converts this entire document's grep-based claims into verified ones on the next CI run.

(Not implemented in this gate — see §14. Described here only to answer "what would the first step concretely be.")

---

## 12. Files Expected to Change

*When P-Test-0 is approved and implemented* (not in this gate):

- `.github/workflows/ci.yml` — add `--cov=app --cov-report=term-missing` to the backend "Unit tests" step.
- `vite.config.ts` — widen `test.coverage.include`.
- Possibly `package.json` — add a `"test:coverage": "vitest run --coverage"` script for local/manual use (does not itself require a CI change).

No other files. No application code, no schema, no UI.

---

## 13. Risks

- **Coverage-first can produce a misleadingly low or high number before anyone reads it.** An informational `--cov` run with no threshold avoids blocking CI, but the first number it produces should be read as a baseline to calibrate against, not a grade — this document already establishes the qualitative picture; the number's job is to make future regressions visible, not to re-litigate priority.
- **Router smoke tests will surface real auth gaps immediately** (§5, §9) — this is a feature of doing the work, but means P-Test-2 cannot be treated as "just testing," and the team should decide in advance how to handle a smoke test that has to assert an insecure-but-current behavior.
- **Billing tests must never touch live Stripe** — every external call site enumerated in §4 needs an explicit mock; there is no shared fixture for this yet (§4's "existing reusable pattern" note), so the first billing test file also makes a small, unavoidable design decision (per-file Fake pool vs. promoting one to `conftest.py`) that is itself implementation, not audit.
- **This audit is a snapshot.** New commits (P1 Context work, etc.) landing after this document will not be reflected in it automatically.

---

## 14. Explicit Do-Not-Change List

Per this gate's instructions, none of the following were modified while producing this document:

- Application code (`app/**`)
- UI (`src/**`)
- Database / schema (`migrations/**`, `init_db.sql`, any `*_SCHEMA` constant)
- Billing logic (`app/billing/**`)
- Routers (`app/routers/**`)
- `ContextManager`
- `AgentOS`
- AI Gateway
- CI configuration (`.github/workflows/**`)
- Test files (`tests/**`, `src/**/__tests__/**`)
- Dependencies (`requirements*.txt`, `package.json`)
- Any other configuration file

Only `docs/testing-foundation-audit.md` was created.

---

## TESTING FOUNDATION DECISION GATE

```
Audit: COMPLETE
Code changes: NONE
Tests added: NONE
CI changes: NONE
UI changes: NONE
Schema changes: NONE

Recommended first implementation:
Add `--cov=app --cov-report=term-missing` to the existing pytest invocation
in .github/workflows/ci.yml (informational only, no threshold), and widen
vite.config.ts's test.coverage.include to cover src/renderer/features/**.

Why:
It is the smallest possible change (no new files, no new jobs, no gate),
touches zero application/billing/router/UI/schema code, and is the
precondition for every other item in this document being verifiable
instead of inferred — including the P0-adjacent runtime_api/kernel_api
authorization findings in §9, which deserve their own explicit decision
separate from this testing roadmap.

Next decision:
WAIT FOR APPROVAL
```
