# Testing Foundation — P0 Slice

**Status:** P0-1 (Real Postgres Tenant Boundary) and P0-2 (RLS Verification) — **done, commit 1**. P0-3 (Billing critical services) — not started, pending review of this commit before proceeding, per the approved execution order.
**Scope:** exactly the P0 slice approved — no coverage-percentage work, no frontend/WebSocket/AI-adapter/Redis/execution-driver/`maintenance.py` testing, no reopening of the Security Boundary Sweep, no Billing product work. This document reports what was built and found; `docs/testing-foundation-assessment.md` §5/§13/§14 are updated to point here rather than duplicating detail.

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

## 11. Remaining P0 gaps

Per the approved P0 scope (P0-1, P0-2, P0-3) and the original assessment's P0 list:

- **P0-3 — Billing critical services** (`credits.py`, `invoices.py`, `payment_methods.py`, `plan_service.py`): not started. Next step, pending review of this commit.
- The original assessment's other two P0 items — execution-driver behavioral tests (`python_script.py`/`python_server.py`/`detector.py`) and `PolicyEngine` table-driven tests (`app/kernel/policy.py`) — remain out of scope for this specific approval (explicitly excluded: "لا تعمل execution drivers الآن") and are unaddressed by this commit, as expected.
- RLS coverage for the 15 non-`organization_members` tables in `_RLS_TABLES` beyond the representative case tested here (§8) — most directly relevant ones (`invoices`, `payment_methods`, `credits`, `billing_events`) will get real coverage naturally as part of P0-3's billing-service tests, since those services are the ones that actually write to those tables.
