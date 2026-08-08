# Testing Foundation — P0 Slice

**Status:** P0-1 (Real Postgres Tenant Boundary) and P0-2 (RLS Verification) — **done, commit 1** (`e53dae2`). P0-3 (Billing critical services) — **`credits.py` and `invoices.py` done, commit 2**; `payment_methods.py` and `plan_service.py` not started, pending review of commit 2 before proceeding, per the approved execution order.
**Scope:** exactly the P0 slice approved — no coverage-percentage work, no frontend/WebSocket/AI-adapter/Redis/execution-driver/`maintenance.py` testing, no reopening of the Security Boundary Sweep, no Billing *product* work (no new billing behavior, no production code changes beyond what a confirmed bug would require — none was found). This document reports what was built and found; `docs/testing-foundation-assessment.md` §5/§13/§14 are updated to point here rather than duplicating detail.

---

## 1. Why this slice, precisely

The Testing Foundation Assessment's central finding: the entire 1488-test backend suite mocked `asyncpg` everywhere, so `app/tenancy/service.py` — the code every `org_context`/`require_permission` check in the app (including both prior security sweeps' fixes) ultimately calls — had 17% line / 13% branch coverage, and Row Level Security itself (`app/tenancy/rls.py`, 32%/26%) had never been exercised against a real Postgres instance. Every "org A cannot see org B" claim in the whole codebase, security suite included, was proven at the *application* layer (a mocked pool matching an expected query string) — never at the *database* layer, which is what RLS actually does. This slice closes exactly that gap, and nothing else.

---

## 2. Test architecture

New package: `tests/db_integration/` (`__init__.py`, `conftest.py`, `test_tenancy_rls.py`, `test_rls_session_context.py`). Kept entirely separate from `tests/` and `tests/security/` — no existing test file was touched, no existing fixture or convention was changed.

**Design decisions and why:**

- **Real Postgres, not a mock, not SQLite-with-RLS-emulated.** RLS is a Postgres-specific feature; nothing else in this codebase can prove it works.
- **Skips cleanly wherever Postgres isn't reachable**, rather than failing. A module-level `pytest.mark.skipif` in `conftest.py`, driven by a cheap, timeout-bounded connectivity probe run once at collection time. This is why the existing 1488 tests were never at risk from this change: anywhere real Postgres isn't available (a contributor's laptop without Docker running, an environment without the extra service), this whole package is 21 skips, not 21 failures, and the exit code stays 0.
- **A dedicated, non-superuser application role (`axon_pgtest_app`), never the admin/superuser connection, runs schema creation and every test.** This is the single most important design decision in this slice, and it's worth stating precisely: **Postgres superusers bypass Row Level Security unconditionally — there is no override.** If schema setup or the tests themselves had run as a superuser (which is what `test`/`test`, the admin credential convention `ci.yml`'s `postgres:16` service and this local environment both already use, would have been if reused directly), `app/tenancy/rls.py`'s `FORCE ROW LEVEL SECURITY` would have been silently meaningless, and every "RLS blocks cross-tenant access" assertion below would have passed for the *wrong reason* — proving nothing. The harness creates `axon_pgtest_app` (idempotently, `CREATEDB`, explicitly not `SUPERUSER`) using the admin connection only for that one bootstrap step, then runs `app.core.db.init_db`, `app.tenancy.init_tenancy_schema`, and `app.tenancy.enable_scoped_rls` — the exact functions `app.factory.lifespan()` calls in production, not a reimplementation of them — as that role, so it becomes the owner of every table it creates. `TestHarnessIsReal::test_app_role_is_not_superuser` asserts this directly and would fail loudly if it ever regressed.
- **One real database per test session, not per test.** Schema creation (~15 `CREATE TABLE`/`ALTER TABLE`/RLS-policy statements) is the expensive part; a session-scoped, synchronous fixture (`pg_test_database_url`) provisions it once via its own throwaway `asyncio.run()` calls and drops it on teardown. Individual tests get their own fresh `asyncpg.Pool` (function-scoped, `pg_pool` fixture) against that same database, and their own fresh organizations/users (`two_orgs` fixture, created through the real `TenancyService.create_organization()`, not hand-inserted rows).
- **Why the session/test split matters technically:** `asyncpg.Pool` objects are bound to the event loop that created them. pytest-asyncio (this project's `asyncio_mode = auto`) gives each async test function its own event loop by default. A pool created once at session scope and reused across test-function loops would break. Provisioning (session-scoped, sync, its own loop via `asyncio.run()`) and connection use (function-scoped, async, the test's own loop) are deliberately decoupled to avoid this.
- **`app.core.db.acquire_scoped()` — the actual function `TenancyService` and every RLS-scoped query in the app calls — reads a module-level global pool (`app.core.db._pool`), not an injected one.** The `pg_pool` fixture installs the real test pool into that global for the duration of each test and restores whatever was there before on teardown, specifically so tests exercise the *real* `acquire_scoped()`, not a stand-in. Same treatment for `app.tenancy.service`'s `get_tenancy_service()` singleton, which binds to a pool on first call and never rebinds — reset to `None` around each test so it can't silently pick up a stale reference from an earlier test.

---

## 3. Real Postgres setup

Reused, not reinvented: `docker-compose.yml` already runs `postgres:16-alpine` for local dev, and `ci.yml`'s "backend" job already runs a `postgres:16` service container (currently only consumed by `scripts/ci_schema_check.py`, which validates schema creation but runs no test against it). This slice targets that same convention:

- `PG_INTEGRATION_ADMIN_DSN` env var, defaulting to `postgresql://test:test@127.0.0.1:5432/postgres` — the exact credential convention `ci.yml`'s existing service already uses, so this package would work against it unmodified if a future CI change (not made here — see §9) wires the "Unit tests" step to also see that service.
- In this session: no Docker daemon was reachable (`/var/run/docker.sock` absent in this sandbox), so the already-installed native `postgresql-16` package was started directly (`service postgresql start`) instead. This is exactly the "ephemeral, reproducible, no external/shared/production database" requirement — nothing here depends on which of the two (Docker vs. native) is available, only on a Postgres server being reachable at the configured DSN.
- No credentials of consequence are in the repository: `axon_pgtest_app`/`axon_pgtest_app` is a throwaway local/CI-only role with no access to anything beyond ephemeral `axon_pgtest_*` test databases it creates and drops itself; it is not the production `axon`/`axon` credential from `docker-compose.yml` nor any real secret.
- Ephemeral by construction: `axon_pgtest_<12 random hex>` database name per session, dropped in the `pg_test_database_url` fixture's teardown (with a `pg_terminate_backend` sweep first, so a lingering connection can't block the `DROP DATABASE`). Verified directly: `SELECT datname FROM pg_database WHERE datname LIKE 'axon_pgtest_%'` returns zero rows after every run in this session, including after intentionally interrupting runs mid-test.

---

## 4. Tests added (21, all passing, all real)

**`test_tenancy_rls.py` (14 tests):**
- `TestHarnessIsReal` (3) — the pool is genuinely `asyncpg.Pool` connected to real Postgres; the connecting role is confirmed **not** superuser; the real schema/RLS setup functions genuinely ran (`users`/`organizations`/`organization_members`/`role_permissions` tables exist, `organization_members`'s `relrowsecurity` and `relforcerowsecurity` are both `true`).
- `TestTenancyServiceRealDB` (5) — `get_member_role`/`has_permission` through the real `TenancyService` against real rows: owner has their own org's role; a non-member of another org gets `None`; `has_permission` reads the real, seeded `role_permissions` table (not a mock return value) for both an allowed and a denied case; an unknown org id resolves to `None`, not an error.
- `TestRowLevelSecurityEnforcement` (6) — the core of P0-2. Two positive/negative pairs at the database layer specifically:
  - **`test_scoped_connection_cannot_read_other_orgs_row_with_no_where_clause`** (and its reverse) — the single strongest test in this slice: a `SELECT organization_id FROM organization_members` with **zero** `WHERE` clause, run through a connection scoped to org A via `acquire_scoped()`, returns only org A's rows. This proves the database itself enforces the boundary, independent of whether any Python code remembered to add a filter — the exact thing no mocked test in the rest of the suite can reach.
  - **`test_scoped_connection_cannot_update_other_orgs_row`** / **`..._cannot_delete_other_orgs_row`** — an `UPDATE`/`DELETE` targeting org B's row while scoped to org A affects **zero** rows (RLS's `USING` clause hides the row before the statement's own `WHERE` is even evaluated), confirmed by re-checking org B's row is genuinely untouched from a connection scoped to B.
  - **`test_own_org_write_still_succeeds`** — the necessary positive control: RLS doesn't also block legitimate same-org writes.
  - **`test_unscoped_connection_sees_everything_by_design`** — documents, as a verified behavior rather than an assumption, that a plain never-scoped connection is intentionally unrestricted (RLS here is additive defense-in-depth for `TenancyService`/`UsageService` specifically, per `app/tenancy/rls.py`'s own docstring — not a blanket rewrite of how the rest of the app talks to Postgres).

**`test_rls_session_context.py` (7 tests):**
- `TestSessionContextDoesNotLeakAcrossPooledConnections` (3) — the specific leak scenario `acquire_scoped()`'s own docstring and the RLS policy's `nullif(...,'')` comment are written to guard against, forced with a `max_size=1` pool so connection reuse is guaranteed rather than hoped for: the `app.current_org_id` GUC does not survive from a scoped block into a later *unscoped* acquisition on the same physical connection; it does not leak from org A's scope into org B's scope on the same connection; and a connection that has ever been scoped (and had its GUC reset to `''`, not `NULL`, per Postgres's own `SET LOCAL` semantics) is still correctly treated as unscoped by the policy afterward.
- `TestOrgContextFullChainRealDB` (4) — the full **request/auth context → `org_context()` → `TenancyService` → real connection/transaction → real RLS → result** chain requested, with only the auth/JWT identity-resolution step mocked (a real `starlette.requests.Request` is constructed with a real `X-Organization-Id` header; only `get_current_user`'s return value is supplied directly — a separate, already-covered concern, see `tests/test_auth.py`/`tests/security/test_authentication.py`). Own-org resolution succeeds with the real role; a non-member gets 404 (not 403 — matching the convention verified throughout the tenant-boundary sweep); a missing header is 400; and `require_permission("billing","manage")` denies a real `viewer`-role member using the real, seeded permission matrix, not a mocked one.

---

## 5. Production paths exercised

- `app/tenancy/service.py::TenancyService.get_member_role`, `.has_permission`, `._permissions_for`, `.create_organization`
- `app/tenancy/context.py::org_context`, `require_permission`
- `app/core/db.py::acquire_scoped`, `init_db`
- `app/tenancy/schema.py::init_tenancy_schema` (including its `role_permissions` seeding)
- `app/tenancy/rls.py::enable_scoped_rls` and the RLS policy it installs, executed by PostgreSQL itself — not simulated

---

## 6. Vulnerabilities / bugs discovered

**None.** All 21 tests passed on first execution against real Postgres, with no production code changed. Row Level Security, `TenancyService`, `org_context`, and `require_permission` all behave exactly as their docstrings and the two prior security sweeps assumed, now verified at the database layer instead of assumed from mocked tests. Per the approved instructions, no code was touched beyond the new test files (`app/tenancy/*`, `app/core/db.py` — untouched).

---

## 7. Fixes

None required (§6).

---

## 8. Limitations

- **Covers `app/tenancy/` and `app/core/db.py::acquire_scoped` specifically — not every RLS-scoped table.** `_RLS_TABLES` in `app/tenancy/rls.py` lists 16 tables; this slice directly exercises `organization_members` (representative of the pattern) plus schema/role-seeding verification across the board, but does not individually re-prove RLS for each of the other 15 (`invoices`, `payment_methods`, `credits`, `sandbox_workers`, etc.) — P0-3 (billing tables specifically) is the next step, per the approved order, not yet started.
- **Single-node, single-session test database — no concurrency/load testing.** These tests prove correctness, not behavior under connection-pool contention beyond the deliberate `max_size=1` leak tests.
- **`org_context`/`require_permission` tests mock only the auth/JWT layer, by design** (that layer is already covered elsewhere) — this is a scope choice, not a gap, but worth stating plainly: this slice does not re-test JWT decoding or session-token verification.
- **CI does not yet run this package** (§9) — it is real and passing locally, but until CI is updated to point at its existing `postgres:16` service, these 21 tests only run where a developer or agent explicitly has Postgres reachable, same as any other opt-in integration suite.

---

## 9. Execution time

```
tests/db_integration/ alone (Postgres reachable):        21 passed in ~1.6-2.0s
tests/db_integration/ alone (Postgres unreachable):       21 skipped in 0.34s
Full suite (tests/ + tests/db_integration/, PG reachable): 1509 passed in ~91-94s
Full suite baseline before this slice:                     1488 passed in ~46-72s (no --cov)
```

The ~1.6-2s added when Postgres is reachable is negligible relative to the full suite's ~90s; the one-time session-scoped schema-creation cost (a handful of `CREATE TABLE` statements) dominates and is paid once, not per test.

---

## 10. CI implications

**No CI file was changed in this commit** (out of scope for this slice — see the approved instructions' "لا تعمل commit في هذه المرحلة" boundary from the assessment phase, now narrowly relaxed only for the specific commits approved here, which are test-file-only). Practical implication: as committed, this package runs and passes locally and in any environment where `PG_INTEGRATION_ADMIN_DSN` resolves to a reachable Postgres — but **CI's current "Unit tests" step (`python -m pytest tests/ -v --tb=short`) will collect and skip all 21 tests**, since the existing `postgres:16` service container in `ci.yml` is not yet wired to be visible the same way locally (host `127.0.0.1:5432` inside the same job, which — because CI's `postgres` service is already configured with `ports: 5432:5432` — should in fact already be reachable at `127.0.0.1:5432` with `test`/`test` from within the same job with no CI changes at all; this has not been verified in an actual CI run, only reasoned from `ci.yml`'s existing service definition, and should be confirmed before relying on it). Making that explicit, and deciding whether to also gate on it (informational vs. blocking), is a P1 follow-up, not something this slice enables on its own without that verification.

---

## 11. Billing Critical Services (P0-3) — commit 2

Goal restated precisely, per the approval: not more test *count* — proof that financial operations and billing data don't fail silently, don't cross tenant boundaries, and don't leave inconsistent state on failure. Both services below were read in full (implementation + schema + every real caller in the codebase, via `grep`) before any test was written, specifically to avoid asserting behavior that isn't actually implemented anywhere.

### 11.1 — `app/billing/credits.py`

**Production paths examined:** `CreditService.grant()`, `.get_balance_cents()`, `.list_ledger()`; every caller of `get_credit_service()` in the codebase (exactly one: `app/routers/org_billing.py::grant_credit`, owner-only, `Pydantic Field(gt=0)`-validated).

**Tests added:** `tests/db_integration/test_billing_credits.py`, 12 tests, all real (no `asyncpg` mocking for anything DB-dependent).

**Real PostgreSQL usage:** every test. `grant()`/`get_balance_cents()`/`list_ledger()` all run against the real `credits` table (schema now provisioned by the harness — see §2 update below); FK constraint (`organization_id REFERENCES organizations(id)`) exercised directly for the rollback test; real RLS policy exercised directly for the tenant-isolation tests, same "no WHERE clause" rigor as P0-1/P0-2.

**Mocks used, and why:** none. `grant()`'s Stripe call is wrapped in the production code's own `try/except` (best-effort by design — see the source's own comment), so it fails closed to "no Stripe transaction id" without needing a mock at all in a test environment with no `stripe.api_key` configured; nothing here reaches across the network.

**Failure/rollback tested:** yes — `grant()` against a non-existent `organization_id` raises `asyncpg.exceptions.ForeignKeyViolationError` and leaves zero rows (`TestRollbackOnFailure`).

**Tenant isolation tested:** yes, both directions — `list_ledger()` is RLS-backed (proven with an unqualified `SELECT`, no `WHERE`, through a scoped connection); `grant()`/`get_balance_cents()` are confirmed to run *unscoped* (they never call `acquire_scoped()`), which is itself the significant finding below, not a hidden assumption.

**Idempotency/concurrency relevance:** concurrency is relevant (an append-only ledger under concurrent writers) and tested — 20 concurrent real `grant()` calls all persist, no lost updates (`TestConcurrentGrants`). Idempotency is relevant (retries/double-clicks on a financial mutation) and found to be **absent** — see findings.

**Findings (documented, not fixed — none rise to a confirmed bug against the code's own contract):**

1. **No insufficient-credit protection at the service layer.** `grant()` accepts any negative `amount_cents` with zero balance check; the local ledger sum can go negative (verified: `TestNoInsufficientCreditsProtection`). **Currently unreachable in production**: the only HTTP path to `grant()` Pydantic-validates `amount_usd > 0`, so this is a dormant capability, not a live exploit path — `test_no_router_ever_calls_grant_with_a_negative_amount` pins that boundary so it's caught immediately if it ever changes.
2. **No idempotency key on credit grants.** Two identical `grant()` calls (e.g. an owner's double-click, or a client retry after a timed-out response) create two ledger rows and double the balance — verified directly (`TestNoIdempotencyKey`). Unlike finding 1, **this *is* reachable today** through the live `grant_credit` endpoint by an ordinary user action, no malicious input required. Flagged for your explicit decision, per the approved instructions, rather than fixed here.
3. **`grant()`/`get_balance_cents()` bypass RLS by design** (no `acquire_scoped()`), unlike `list_ledger()`. No known caller passes attacker-controlled `org_id` to these two methods (both are always called with a server-verified `ctx.org_id` from `org_billing.py`), so this is an architectural asymmetry worth knowing about, not a demonstrated vulnerability.

**Remaining gaps:** none beyond the findings above — every method on `CreditService` has direct test coverage now.

### 11.2 — `app/billing/invoices.py`

**Production paths examined:** `InvoiceService.upsert_from_stripe_invoice()` (the only write path — invoices + invoice_items + derived payments row, one real transaction), `.get()`, `.list_for_org()`, `.list_payments_for_org()`; `app/routers/org_billing.py`'s invoice routes (confirmed read-only — no `update_invoice`/`delete_invoice` exists anywhere).

**Tests added:** `tests/db_integration/test_billing_invoices.py`, 15 tests, all real.

**Real PostgreSQL usage:** every test, including a genuine multi-statement transaction-atomicity proof (see below) that no mock could produce.

**Mocks used, and why:** none. No Stripe API call exists in this file at all outside `backfill_from_stripe()` (not tested here — it's a thin wrapper that calls `upsert_from_stripe_invoice()` in a loop over live `stripe.Invoice.list()` results, i.e. it's a Stripe-API-boundary concern, not a database-behavior one, and mocking `stripe.Invoice.list()` to test a loop-and-call wrapper would not add to what this slice is proving).

**Failure/rollback tested:** yes, and this is the strongest test in this file — `TestTransactionRollback::test_invoice_row_does_not_persist_if_line_item_insert_fails` forces a real type-coercion failure on the *second* of three statements inside the transaction (a non-integer `quantity` for `invoice_items`, which is `INTEGER NOT NULL`) — after the *first* statement (the invoice `INSERT ... RETURNING *`) has already run and returned a row within that same transaction. Confirms the invoice row does **not** survive the rollback: proof that the whole `async with conn.transaction():` block is genuinely atomic, not proof by reading the code. A second test does the same via a `ForeignKeyViolationError` on a non-existent `organization_id`.

**Tenant isolation tested:** yes — `get()` returns `None` for another org's invoice id; `list_for_org()` excludes it; and, matching P0-1/P0-2's rigor, RLS itself is proven independently of the application-layer `WHERE organization_id=` filter for both `invoices` and `payments` (unqualified `SELECT`, no `WHERE`, through a scoped connection, only sees the scoped org's rows). "Tenant A cannot mutate/delete tenant B's invoice" has **no dedicated test** because there is no such endpoint to attack — `test_no_tenant_triggered_mutation_endpoint_exists` asserts that absence structurally so a future `PUT`/`DELETE` route would need this test file updated, not silently leave the gap unnoticed.

**Idempotency/concurrency relevance:** idempotency is highly relevant (Stripe webhooks redeliver) and confirmed **present and correct** by design: `stripe_invoice_id` is `UNIQUE` with `ON CONFLICT ... DO UPDATE`, and the `invoice_items`/`payments` DELETE-then-INSERT pattern (documented in the source's own comment, now also verified by test) converges repeated deliveries to one row each, not duplicates (`TestIdempotentUpsert`, 3 tests). Concurrency (two simultaneous webhook deliveries for the same invoice) was not separately tested — `ON CONFLICT` makes the invoices upsert itself concurrency-safe by construction (a Postgres guarantee, not something this slice needed to re-prove), and the multi-statement items/payments replace happens inside the same transaction as the conflict-checked invoice row, so a genuine concurrent-delivery race would need to be understood at the transaction-isolation level specifically — flagged as a gap, not tested here (see below).

**Findings (documented, not fixed):**

1. **No status-transition validation.** `upsert_from_stripe_invoice()` unconditionally overwrites `status` with whatever the caller passes — an out-of-order-delivered `draft` event after a `paid` one silently regresses the row (verified: `TestNoStatusTransitionValidation`). This depends entirely on Stripe's own webhook-ordering guarantees (which are best-effort, not strict) — a real but bounded risk (Stripe redelivers rarely and mostly in-order), not something to redesign inside a testing-only task.

**Remaining gaps:**
- **Concurrent-delivery transaction-isolation behavior** for two simultaneous `upsert_from_stripe_invoice()` calls for the *same* `stripe_invoice_id` was not tested — `ON CONFLICT` handles the invoices row itself safely, but whether the two transactions' invoice_items/payments DELETE-then-INSERT pairs could interleave in a way that leaves a transiently inconsistent (not permanently wrong, since both transactions still each fully commit or fully roll back) item set was not verified under real concurrent load. Worth a follow-up if this proves to matter in practice — Stripe does not typically deliver the same event concurrently.
- `backfill_from_stripe()` (the Stripe-API-boundary wrapper) has no test in this slice, per the "mock only the external boundary, don't newly integrate a real payment provider" instruction — it would need a mocked `stripe.Invoice.list()`, which is a legitimate future addition but wasn't necessary to prove this slice's goal (DB-layer correctness).

### 11.3 — Findings Decision Gate (post-commit-2 deep-dive, no code changed)

Additional confirmation work only, per explicit instruction, before any of these four are fixed. No production code was touched producing this section; the two "reproduction" tests referenced already existed in commit `8efae17` (`TestNoIdempotencyKey`, `TestNoStatusTransitionValidation`) — no new tests were added, since both scenarios were already proven and adding a second test for the same fact would not add information.

#### Finding #1 — `credits.grant()` idempotency → **Confirmed Financial Integrity Finding**

**HTTP endpoint traced end to end:** `POST /api/orgs/{org_id}/credits` (`app/routers/org_billing.py::grant_credit`) → `ctx: OrgContext = Depends(require_permission("billing","manage"))`, **plus** an explicit `if ctx.role != "owner": raise 403` — this is genuinely owner-only, no permission-check bypass found. `GrantCreditRequest.amount_usd: float = Field(gt=0)` is the only input validation. The handler calls `CreditService.grant(ctx.org_id, round(amount_usd*100), reason, actor_id=ctx.user_id)` directly — no idempotency key field exists on `GrantCreditRequest`, no idempotency wrapping exists in the handler or the service method.

**Who can call it:** only a verified member of the org holding the `owner` role (server-verified via `require_permission`'s real DB membership check, not client-trusted). This bounds the finding precisely: it is **not** an attacker-exploitable cross-tenant or privilege-escalation issue — it is a data-integrity risk triggered by a *legitimate, authorized* actor's own retry (accidental double-click, a client-side network timeout causing an automatic retry, a proxy retry, browser back-button resubmission). The party harmed is the organization's own credit ledger accuracy (and, since credits reduce what Stripe bills, the company's realized revenue) — not another tenant.

**Existing idempotency mechanism found — `app.core.idempotency.idempotent()`** (`app/core/idempotency.py`), already schema'd (`idempotency_keys` table, `UNIQUE(scope, key)`), already tested (`tests/test_idempotency.py`), and **already used by two other call sites in this exact codebase**:
- `app/routers/agent_os_api.py`'s `/api/agentos/run` — keyed by a client-supplied `req.run_id`.
- `app/core/jobs/queue.py::JobQueue.submit()` — an **optional** `idempotency_key` parameter; when omitted (the default), no dedup happens at all — the exact same "opt-in, backward compatible" shape a credits fix would need.

Its own docstring literally names "client double-submit" as a scenario it exists to solve — this is precisely the mechanism to reuse, not a new one to invent.

**Is there an existing request-ID/idempotency-key already flowing through this specific request that could be reused for free?** No. `app/core/middleware.py::RequestIdMiddleware` does accept a client-supplied `X-Request-Id` header, but (a) it is used only for log/trace correlation (`set_request_id(rid)`), never read by any business-logic code, and (b) the frontend never sends this header at all (confirmed: zero occurrences of `X-Request-Id` anywhere in `src/`) — every request, including a genuine retry, gets a fresh server-generated UUID either way. **This header is not usable as an idempotency key today without both a frontend change (generate and persist one key per logical submit attempt, resend unchanged on retry) and a backend change (read and use it) — it is not "already wired," just present as unused plumbing.**

**Reproduction:** `tests/db_integration/test_billing_credits.py::TestNoIdempotencyKey::test_identical_grant_calls_create_two_ledger_rows_not_one` (already in commit `8efae17`) — two `grant()` calls with byte-identical arguments create two distinct rows and double `get_balance_cents()`'s result. This generically covers "a retry of the same logical operation," not just "two deliberately different calls": at the HTTP layer, an automatic retry of the same `POST` *is* two calls with identical arguments — there is no third case in between that the existing test doesn't already cover.

**Root cause:** no idempotency key exists anywhere in the request/response contract for this endpoint (not in the schema, not in the service signature), and no mechanism wraps the write.

**Minimal fix proposal (not implemented — pending approval):**
1. Add `idempotency_key: Optional[str] = None` to `GrantCreditRequest` (backward compatible — omitting it preserves today's exact behavior, mirroring `JobQueue.submit()`'s own optional-parameter convention).
2. `CreditService.grant()` gains a matching optional `idempotency_key` parameter. When provided, the **entire** current body of `grant()` (both the best-effort Stripe balance-transaction call and the local `INSERT`) moves inside `async with idempotent("credit_grant", f"{org_id}:{idempotency_key}", pool=self._pool) as guard:` — both side effects need to be inside the guard, not just the DB write, or a replay would still re-attempt the Stripe call. `guard.result` gets set to the inserted row (JSON-serializable subset); a replay returns `guard.cached_result` instead of inserting again.
3. **Effectiveness depends on the frontend generating and reusing a stable key per logical submission** (e.g., a UUID created once when the "Grant Credit" form is opened/submitted, kept unchanged across that submission's retries, discarded after a terminal response). A backend-only change with no client sending a stable key would leave the vulnerability's practical trigger (double-click/timeout-retry) unaddressed — this is a two-sided fix, not backend-only, and worth flagging explicitly since "smallest possible fix" could otherwise be misread as backend-only.

**Database constraint/transaction implications:** none new — `idempotency_keys`'s existing `UNIQUE(scope, key)` constraint is the actual atomicity guarantee (the same `INSERT ... ON CONFLICT DO NOTHING` pattern already proven in `tests/test_idempotency.py`), so no new constraint or migration is needed on `credits` itself. The credits `INSERT` and the `idempotency_keys` bookkeeping would run as two separate statements (not one transaction) under `idempotent()`'s existing design — matching how `agent_os_api.py`/`JobQueue` already use it, not a new pattern.

**Not implemented in this task — awaiting your explicit approval, per instruction.**

#### Finding #2 — invoice status regression (`paid → draft`) → **Confirmed Domain Integrity Finding**

**Schema/model read:** `invoices.status VARCHAR(20) NOT NULL DEFAULT 'draft'` — no `CHECK` constraint on value or on transitions; `_STATUS_TO_PAYMENT_STATUS`'s five keys (`paid, open, draft, uncollectible, void`) are exactly Stripe's real `Invoice.status` enum.

**Webhook handling path read:** `app/routers/subscriptions.py::_dispatch_webhook_event` dispatches `invoice.created|finalized|paid|payment_failed|voided` all to the same `_sync_invoice()` → `upsert_from_stripe_invoice()`. `app/billing/webhooks.py::WebhookEventService.record()` dedupes by `stripe_event_id` — this stops an **exact redelivery of the same event** from double-processing, but does **nothing** to order **different** events for the same invoice relative to each other. `invoice.created` (status snapshot: `draft`) and `invoice.paid` (status snapshot: `paid`) are two distinct Stripe event IDs; each is "new" to `WebhookEventService` and processed independently. Stripe's delivery guarantee is at-least-once, explicitly not strictly ordered under retry — so `invoice.created`'s delivery can be delayed (network retry, an earlier processing failure that Stripe redelivers later) and arrive **after** `invoice.paid` already applied.

**Status transition rules found in the codebase today:** none. No state machine, no ordering check, no use of the Stripe event's own `created` timestamp anywhere in this path.

**Legal states in practice (Stripe's real domain, not invented):** the canonical flow is `draft → open → {paid | void | uncollectible}`, with one well-known legitimate "reopening" exception — `uncollectible → paid` (a previously-uncollectible invoice can still be paid later). Stripe's own system never actually transitions a real invoice from `paid` back to `draft` — a local row observing that "transition" is by definition processing a **stale, out-of-order snapshot**, not a genuine new state change.

**Is `paid → draft` legitimate or an artifact?** An artifact of out-of-order webhook delivery, not a real domain transition — confirmed by the above, not assumed. **Classification: Confirmed Domain Integrity Finding, not Safe/Expected.**

**Reproduction:** `tests/db_integration/test_billing_invoices.py::TestNoStatusTransitionValidation::test_status_can_regress_on_out_of_order_delivery` (already in commit `8efae17`) — applying a `draft` delivery after a `paid` one for the same `stripe_invoice_id` leaves the row showing `draft`, against real PostgreSQL.

**Minimal fix proposal (not implemented — pending approval):** the narrowest fix does **not** require encoding Stripe's full status state machine (which would be more invasive and Stripe-domain-knowledge-fragile than "smallest fix" allows). Instead: capture the Stripe event's own `created` (epoch) timestamp — already available on every webhook `event` object, currently discarded — as a new `last_event_at` column on `invoices`, and change the `ON CONFLICT ... DO UPDATE` clause to a conditional update (`WHERE invoices.last_event_at IS NULL OR EXCLUDED.last_event_at >= invoices.last_event_at`), so a delivery that's provably older than what's already stored is a no-op rather than an overwrite. This is a "last-write-wins by event time, not by arrival time" pattern — standard for out-of-order webhook handling, requires one additive column (no destructive migration), and doesn't need to model Stripe's status semantics at all.

**Not implemented in this task — awaiting your explicit approval, per instruction.**

#### Finding #3 — `grant()`/`get_balance_cents()` bypass RLS → **P1 Architectural Hardening** (no exploit path found)

**All callers traced, exhaustively** (`grep -rn "get_credit_service()\.\|\.grant(\|\.get_balance_cents(" app/` — zero results outside `app/billing/credits.py` and exactly two call sites in `app/routers/org_billing.py`):
- `grant()` ← `grant_credit` only, with `ctx.org_id` from `require_permission("billing","manage")` **plus** the owner-role check (§ Finding #1).
- `get_balance_cents()` ← `get_credits` only, with `ctx.org_id` from plain `org_context`.

**Can an attacker reach either with an unverified `org_id`?** No. Both call sites' `ctx.org_id` is resolved by `org_context`'s `_extract_org_id()` (header/query/path — client-suppliable) but then **independently verified** against real DB membership (`get_tenancy_service().get_member_role(org_id, user_id)`) before `OrgContext` is ever constructed — the same server-verification pattern examined exhaustively across both prior security sweeps. There is no path from client input to `grant()`/`get_balance_cents()` that skips this check.

**Can `get_balance_cents()` leak another org's balance?** No — same reasoning; its one caller always supplies a membership-verified `org_id`.

**Are there service-to-service (non-HTTP) callers?** No — confirmed zero (checked `cli.py`, `agentos.py`, `scripts/`, `dev_plugins/`, and all of `app/` for any other importer of `CreditService`/`get_credit_service`).

**Should these be RLS-protected per the current architecture's own stated intent?** The architecture's own documented intent (`app/tenancy/rls.py`'s docstring: "additive defense-in-depth for the tenancy-critical services") suggests yes, for consistency with `list_ledger()`'s treatment of the same table — but "should be more defensive" is a hardening judgment, not evidence of a live gap, since no caller today relies on RLS as the *only* protection for these two methods.

**Classification: P1 Architectural Hardening.** No exploit path exists today; not modified in this task, per instruction.

#### Finding #4 — negative `grant()` amount → **P2 / Dormant**

**Confirmed no other entry point exists:** exhaustive `grep` (same sweep as Finding #3) found exactly one HTTP path to `grant()`, and `GrantCreditRequest.amount_usd: float = Field(gt=0)` is enforced by Pydantic on every request before the handler body even runs. No CLI, script, admin tool, or other router calls `CreditService.grant()` anywhere in this repository.

**Classification: P2 / Dormant**, confirmed, not just assumed. The pinning test (`TestNoInsufficientCreditsProtection::test_no_router_ever_calls_grant_with_a_negative_amount`, already in commit `8efae17`) stays as the tripwire — no further action.

---

## 12. Remaining P0 gaps (updated after commit 2)

Per the approved P0 scope (P0-1, P0-2, P0-3) and the original assessment's P0 list:

- **P0-3 continuation — `payment_methods.py` and `plan_service.py`**: not started. Next step, pending review of commit 2.
- The original assessment's other two P0 items — execution-driver behavioral tests (`python_script.py`/`python_server.py`/`detector.py`) and `PolicyEngine` table-driven tests (`app/kernel/policy.py`) — remain out of scope for this specific approval and unaddressed, as expected.
- RLS coverage for the remaining non-tested tables in `_RLS_TABLES` beyond `organization_members`/`credits`/`invoices`/`payments` (now covered: `payment_methods`, `billing_events`, `sandbox_workers`, `sandbox_events`, `chat_messages`, `teams`, `usage_records`, `marketplace_installs`, `api_keys`, `marketplace_downloads`, `plugin_installations`) — will get real coverage naturally as their owning services get tested in future slices, same pattern as this one.
- Two specific findings from §11 are flagged for an explicit decision rather than fixed in this commit: **no idempotency key on `credits.grant()`** (live, reachable via ordinary double-click/retry) and **no status-transition validation on invoice upserts** (live, reachable via out-of-order Stripe webhook delivery). Neither is a bug against the code's current documented contract — both are gaps relative to a more defensive design. See §11.1/§11.2 for full detail.

---

## 13. Execution time (updated after commit 2)

```
tests/db_integration/ alone (Postgres reachable):        48 passed in ~3-7s
tests/db_integration/ alone (Postgres unreachable):       48 skipped, exit code 0
Full suite (tests/ + tests/db_integration/, PG reachable): 1536 passed in ~90-98s
Baseline before P0-1/P0-2 (commit 1):                      1488 passed in ~46-72s (no --cov)
Baseline after P0-1/P0-2 (commit 1):                       1509 passed
```
