# Flow Business — 12-pass evidence-based audit ledger

Status: **INCOMPLETE — DO NOT CERTIFY**. Started 2026-11-15. Scope: Flow only; Axon remains separate.

## Acceptance rule
Each of 12 independent passes must include: exact commit/deployment ID, test environment, dataset (synthetic only), user journeys exercised, internal services and database checks, test counts, failures and warning triage, evidence links, remediation and repeat results. A successful CI run is **not** a full-platform pass. No production writes, real payments, customer messages, or destructive testing without separate approval.

## Evidence baseline (pass 1, partial)
- PR #56 commit `7f5a03027879f1ba6108fb0e87b65454f0ca124a`.
- GitHub Actions CI #377 (run 43716154694): Backend, Frontend, Docker build succeeded; deploy, release and post-deploy health checks skipped. CodeQL #31 succeeded.
- Backend pytest: **3266 passed, 4 skipped, 41 warnings, 26 subtests passed**. Warnings include unawaited AsyncMock coroutines and deprecated per-request cookies. Investigate before signoff.
- Frontend Vitest: **520 passed across 61 files**. Typecheck, ESLint, build succeeded. Dependency installation reported **20 vulnerabilities (11 moderate, 9 high)**; subsequent npm audit step reported 0 vulnerabilities. These are different outputs and require reconciling dependency scope, command and lockfiles. Do not infer zero risk.
- PostgreSQL container logs reported missing `organizations` and `org_subscriptions` relations during initialization, and unavailable `vector` extension; startup/schema check succeeded but warnings need triage.
- Docker build succeeded with warnings: pip root user, resolver backtracking, redis asyncio extra, system UID mismatch.
- GitHub Actions reports Node 20 deprecation for actions/checkout@v4 and setup-python@v5/setup-node@v4.
- Render connector lists one accessible workspace but requires **user selection** before service enumeration. No internal Render service audit performed. No Vercel/Redis/PostgreSQL runtime audit performed. No complete browser journey executed.

## Pass ledger
| Pass | CI | Internal services | User journey | Data isolation | Verdict |
|---|---|---|---|---|---|
| 1 | CI #377 succeeded, warning triage open | Not tested | Not tested | Handler-only tests, no DB proof | **Incomplete** |
| 2–12 | Not run | Not run | Not run | Not run | **Not started** |

## Mandatory journey coverage
Guest -> registration -> verification -> login -> MFA/OAuth -> create org/team -> new project -> app builder preview/export -> AI assistant -> lead capture/qualification -> approval-gated automation -> notification -> career assistant -> feed/discover -> billing test-only -> settings -> logout -> account deletion. Exercise Arabic/English, mobile/desktop, permissions, expired sessions, invalid input, retries, simultaneous requests, recovery from dependencies being unavailable.

## Internal dependency matrix
Render web/worker/scheduler services and logs; Vercel deployments, routes, frontend assets; PostgreSQL schema/transactions/backups; Redis connectivity/fallback; queue/job workers; AI gateway quotas/errors; email delivery in test sink; OAuth provider sandbox; storage; monitoring/alerts; Docker startup/health. Record access limitations explicitly.

## Release blockers
1. Durable tenant-scoped idempotency for lead capture not yet implemented.
2. Database-backed cross-tenant integration tests not yet run.
3. Outbound follow-up human approval not yet proven.
4. CI warnings and dependency audit discrepancies not reconciled.
5. Eleven additional full audit passes not executed.
6. Licensing, payment-provider eligibility and privacy operational requirements not closed.

No production deployment or merge to main is authorized by this audit.

## Evidence update — CI #379 (2026-11-15)
- Head commit `06db9935837d0ee70ee0d394be65b74b149a41e4` adds a **separate full-tree npm audit**, informational only; production dependency audit remains a blocking step.
- Frontend job completed successfully: 520/520 Vitest tests (61 files), TypeScript, lint and build passed.
- Full dependency audit **confirmed 20 advisories: 11 moderate and 9 high**; `npm audit --omit=dev --audit-level=high` found 0 production dependency advisories. This explains the previously contradictory output: the advisories are outside the production-only dependency set. **Not fixed.** Remediation and retesting required.
- At time of inspection CI #379 Backend was still in progress; Docker and complete workflow result were not yet available. CodeQL #33 succeeded.
- This is evidence for the existing partial pass, **not a second independent full-platform pass**.

## M1 — SEC-01 dependency remediation (2026-11-15)
Branch `claude/project-thread-ok7qyu` from `e3f8390`. Environment: local container, Node 22.23.4 / npm 10.9.9.

| Measure | Before (`e3f8390`) | After |
|---|---|---|
| `npm audit` full tree | 20 (9 high, 11 moderate) | 7 moderate, 0 high |
| `npm audit --omit=dev` | 0 | 0 |
| Typecheck / lint:strict / build | pass | pass |
| Vitest | 520/520 (61 files) | 520/520 (61 files) |

Fixed (no major upgrades): vite 7.3.8; vitest, @vitest/coverage-v8, @vitest/mocker 4.1.12; postcss 8.5.33; nanoid 3.3.20; source-map-js 1.2.2; browserslist 4.29.5; baseline-browser-mapping 2.11.37; brace-expansion 1.1.22 / 5.0.13; js-yaml 4.3.2; undici 7.30.2; zod 4.6.7. All are dev/build/test tooling; none ship in the production bundle.

Remaining (accepted, documented): **minimatch 10.2.5** — GHSA-g3hv-75wg-m249 (moderate, ReDoS-style DoS via crafted glob patterns). Reached only through `typescript-eslint` → `@typescript-eslint/typescript-estree` (`minimatch ^10.2.2`); this accounts for all 7 remaining entries. The newest `typescript-eslint` (8.72.2) still requires minimatch 10, so no safe upstream fix exists. `npm audit fix --force` would *downgrade* typescript-eslint to 8.36.0 and was rejected. Exposure: lint only, glob patterns come from repository config, not user input. Re-check when typescript-eslint ships a release on minimatch ≥ 11.0.1.

Regression guard: the full-tree `npm audit --audit-level=high` CI step is now blocking (was `continue-on-error`).

Note: npm 10.9.9 crashes (`Cannot read properties of null (reading 'edgesOut')`) when changing the vite/vitest peer set; the lockfile was regenerated with npm 11 and verified with `npm ci` on npm 10.9.9.

## M2 — BE-01 / BE-02 backend test warnings (2026-11-15)
Environment: local container, Python 3.11, PostgreSQL 16 (synthetic `test_axon` DB), same env vars as CI.

| Measure | CI #380 (`e3f8390`) | After M2 |
|---|---|---|
| pytest | 3266 passed, 4 skipped, **42 warnings** | 3266 passed, 4 skipped, **0 warnings** |

- **BE-01 (7 RuntimeWarnings, `ab12cf9`)** — test-side only. (a) Register tests mocked `conn.transaction` as AsyncMock, but asyncpg's `Connection.transaction()` is synchronous; now a MagicMock. (b) Security-patch tests replaced `asyncio.create_task` with a MagicMock, dropping the `write_audit` coroutine; now closed via `_discard_coro`. The warning attributed to `test_team_chat` was the same leaked coroutine collected later.
- **BE-02 (35 DeprecationWarnings, `ab12cf9`)** — per-request `cookies=` replaced by `tests/cookie_client.request_with_cookies` (sets cookies on the client for one request, then removes them) and, for the async case, cookies on the `AsyncClient` constructor.
- **Regression guard (`ab12cf9`)** — `pytest.ini` turns both warning classes (plus `PytestUnraisableExceptionWarning`) into errors. Verified: the pre-fix test files fail under the guard.
- Observation, not changed: `change_password` / `logout_all` schedule `write_audit` with a bare `asyncio.create_task` and keep no reference, so an audit write can in principle be garbage-collected before it runs. Tracked for the audit-log reliability review.

## M3 — BE-03 / BE-04 schema and migrations (2026-11-15)
Environment: local PostgreSQL 16 (fresh `schema_check` DB per run), `scripts/ci_schema_check.py` (runs the real `lifespan()`), Python 3.11.

**BE-03 — root causes (both reproduced, both fixed):**
| CI Postgres log line | Cause | Fix |
|---|---|---|
| `relation "organizations" does not exist` / `relation "org_subscriptions" does not exist` | Init-order bug: `lifespan()` created `maintenance_loop()` before `init_tenancy_schema()` / `init_org_subscriptions_schema()`. Its first cycle runs immediately; on a fresh DB the active-user and Stripe seat reconciliation failed and were swallowed by `record_error()`. Not a schema defect. | `729141d1`: start maintenance after the tenancy/billing schema block. Guard: `tests/test_lifespan_maintenance_order.py` (fails on old order). Fresh DB now logs no error; first cycle `errors={}`. |
| `extension "vector" is not available` | Test-environment gap: CI used plain `postgres:16`. `app/memory/semantic.py` falls back to an in-process TF-IDF store by design, so CI never exercised the pgvector path. | `1c4644eb`: CI service image `pgvector/pgvector:pg16`. With pgvector, fresh-DB startup logs zero errors and reports "using pgvector backend"; full suite 3267 passed, 4 skipped. |

Open item for M8: whether the **production** database has pgvector. Without it, semantic memory is per-process (lost on restart, not shared between instances). `docker-compose.yml` (local dev) still uses `postgres:16-alpine` without pgvector.

**BE-04 — Alembic chain (diagnosed; no migration or database changed):**
- `alembic history` fails: `Could not determine revision id from filename 003_ai_gateway.py`. 002's `down_revision="001_initial_schema"` does not match 001's `revision="001"`; 003–014 use `up(conn)/down(conn)` or async `upgrade(conn)` shapes with no revision metadata; 009/010 are `_`-prefixed.
- Nothing in production runs Alembic: `Dockerfile` CMD is `uvicorn app_main:app`; `render.yaml` / `railway.toml` have no migrate step. The schema is created by `lifespan()`'s idempotent `init_*` calls.
- Parity: all 66 tables declared across `migrations/versions/*.py` exist after a fresh `lifespan()`, except 001's `agents`, superseded by `ai_agents`; no query references `agents`.
- Guard `3e00eb76`: the CI schema check now fails if any table declared in a migration file is not created by `lifespan()`.
- Decision (owner, 2026-11-15): **retire Alembic**. Config archived to `migrations/_alembic_archive/` in the commit after this entry; guard `tests/test_alembic_archived.py`. No database touched. Still to check in M8 (read-only): whether the production DB has an `alembic_version` table.

## M4 — SEC-02 tenant isolation, end to end (2026-11-15)
Suite: `tests_e2e/test_org_isolation_http.py` (new CI step). Real `lifespan()` on an empty PostgreSQL 16 DB, real auth (register → verify e-mail → login → create org), two synthetic tenants, `example.com` addresses, console e-mail, no Stripe key. Tenant B attacks tenant A's records with B's own valid session, (1) with B's org header + A's ids and (2) with A's org header; A's records are re-read afterwards through A's session.

| Resource | Paths attacked | Result |
|---|---|---|
| Organization | get, settings, members, invitations, activity, API keys, rename, invite-self, delete | denied, A unchanged |
| Leads | get, status change, qualify, list in A | denied, A unchanged |
| Projects + files | get, update, delete, file list/read/upload/wipe | denied, A's file intact, no foreign upload |
| Conversations | messages, export, delete, create in A's project, list, search | denied / not listed |
| Automations + runs | get, update, activate, run, delete, list; run get/cancel/approve/reject | denied, A unchanged (after fix below) |
| Devices | get, rotate credential, session token, revoke, delete, list | denied, A unchanged (after fixes below) |
| Notifications | read, archive, delete, read-all, list | denied, A's stays unread |
| Invoices / billing | invoices, invoice by id, summary, payments, methods, credits (both header modes) | denied / not leaked |

Result: **8/8 pass. No cross-tenant read, write or delete was possible.**

Defects found while building the suite (each fixed in its own commit with a guard):
- `2d6f2243` — run cancel answered 409 (not 404) for another org's run; inconsistent with the rest of the API. No write was possible.
- `14faa6f0` — **device enrollment was broken end to end**: (1) auth middleware returned 401 to the unauthenticated agent on `POST /api/devices/enroll`; (2) agent sends `enrollment_token`, API required `token`; (3) `consume_enrollment_token()` violated the `device_id` foreign key on every call. All three fixed; token now locked `FOR UPDATE` for single use.

Observations (not changed in M4):
- Projects, conversations, files and notifications are **per-user**, not per-organization: org members cannot share them. Isolation holds, but this is a product-design limit for team use.
- For `/api/orgs/{org_id}/...` routes the `X-Organization-Id` header wins over the path `org_id`. A caller always acts on an org they belong to (no escalation), but a mismatched header/path silently targets the header's org.
- Shutdown order: `lifespan()` closes the DB pool while queued automation runs may still execute (`pool is closing` in E2E logs); runs in flight at shutdown are marked failed. To review under journey 12 (recovery).
- Not covered by this suite yet: WebSocket channels, study library, social publisher, careers, marketplace, team chat.

## M5 — SEC-03 lead capture idempotency (2026-11-15)
Reproduced first, over real HTTP + API key + PostgreSQL (`tests_e2e/test_lead_capture_idempotency.py`, org with an active lead follow-up automation): **6 identical concurrent `POST /api/leads/capture` created 6 leads and 6 follow-up runs; a sequential re-send created a second lead and run.** The follow-up job already had a per-lead dedup key, but each copy made a new lead, so it never matched.

Fixes:
- `c45bea1e` — `app/core/idempotency.py`: reclaiming a failed / stale-pending key was an unconditional `UPDATE`, so concurrent callers that saw the same row all ran the work. Now a conditional `UPDATE … RETURNING`; the loser gets `IdempotencyInProgress`. New `max_age_s` lets a completed claim expire. Unit tests for both (`tests/test_idempotency.py`, 10 pass).
- `c7afe50d` — `capture_lead` claims each submission in `idempotency_keys` (scope `lead_capture`), always prefixed with the API key's org:
  - `Idempotency-Key` header (1–255 visible ASCII, else 400): replay for 24 h; same key with a different body → 422.
  - no header: SHA-256 fingerprint of normalised name / email / phone digits / source, deduplicated for 24 h.
  - replay → first result + `Idempotent-Replayed: true`; copy arriving while the first is still running → 409 + `Retry-After: 2`.
- `345bb700` — E2E proof.

| E2E case | Result |
|---|---|
| sequential re-send, no key | same id, 1 lead, 1 follow-up run |
| 6 concurrent, no key | one id, 1 lead, 1 run (others 409) |
| 5 concurrent + replay, same key | one id, replay header set, 1 lead, 1 run |
| same key, different body | 422 |
| same key + same e-mail in two orgs | two separate leads (no cross-org dedup) |
| two different people | not merged |

Whole E2E suite 14/14 (isolation 8 + capture 6); unit suite 3283 passed, 4 skipped; ruff unchanged (3 pre-existing).

Residual risks / decisions for the owner:
- Without a header, the same person submitting the same details again within 24 h gets the first lead back (no new lead). After 24 h a new lead is created; merging repeat leads is a product decision, not done here.
- If the database fails *after* the lead row is written (qualification is already failure-tolerant), the claim is marked failed and a retry can create a second lead. Low likelihood; would need lead creation and the claim in one transaction.
- Other create endpoints (`POST /api/leads` from the dashboard) are not deduplicated; they are user actions, not external re-sends.

## M6 — FE-01 chunk loading, FE-02 chat stability (2026-11-15)
Method: the real production build (`npm run build`) served like `vercel.json` (existing files, `/api` proxied, every other path → `index.html`) with the real backend on PostgreSQL, driven by Playwright/Chromium with a synthetic signed-in user. A deploy is emulated by giving every built asset a new hashed name while the tab stays open.

**FE-01 — reproduced, then fixed (`d9a6b3dd`):**
| Scenario | Before | After |
|---|---|---|
| Tab open across 1 deploy, open Leads | recovered by one reload | recovered by one reload |
| Same tab, 2nd deploy, open Automate | stuck on "Failed to fetch dynamically imported module"; Retry does nothing | recovered by one reload |
| Two deploys within 10 s | — | "A new version of Flow is available" + Reload (no loop) |
| All 29 routes, fresh load | 29/29 | 29/29 |
| All 29 routes, tab open across a deploy | — | 29/29, one reload, 0 uncaught errors |

Causes: the reload guard was a sessionStorage flag never cleared (only the first deploy per tab was recovered); `React.lazy` keeps a failed import, so the error screen's Retry could never work; the public study-library page had no recovery at all. Fix: `shared/lib/staleChunk.ts` (`lazyPage()` for all lazy pages, 10 s cooldown guard), ErrorBoundary shows Reload for stale chunks. Note: Vercel's catch-all rewrite answers a missing `/assets/*.js` with `index.html` (200, text/html); the browser reports the same import error, so detection works, but excluding `/assets/` from the rewrite (true 404) is cleaner — left for M8 as it changes deploy config.

Also fixed `5110d891`: `AutomationPage.test.tsx` "does not issue overlapping workflow refresh requests" (added on the base branch in 29c41868) failed from its own commit: it counted the approvals panel's `/api/automation-runs/pending-approvals` as a refresh and clicked a button that is disabled while loading. It now tests the 5 s poll; passes with the in-flight guard, fails without it.

**FE-02 — chat (`7c22da27`):** 7 new `ChatTab` tests, all failing before the change:
| Check | Before | After |
|---|---|---|
| Conversation history restore | history loaded only when clicked | reopened after refresh (per tab) |
| Drafts | lost on refresh / when switching chat | kept per conversation (localStorage) |
| Concurrent sends | double Enter in one tick sent twice | one request |
| Network down before sending | typed text cleared | text given back + "Backend offline" |
| Connection lost mid-reply | partial reply looked complete | kept and marked as interrupted (en/ar) |
| Leaving the chat mid-reply | request kept running | aborted |

Real browser on the built app + backend: draft survived a refresh; a message created a server conversation and the refresh reopened it with its history; offline send kept the text and showed the notice.

Frontend checks: typecheck, `lint:strict`, vitest 538/538, build OK.
Not covered yet: Safari/Firefox (only Chromium was driven), team chat, WebSocket reconnect.
