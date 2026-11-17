# Flow Business — 12-pass evidence-based audit ledger

Status: **12 cycles run; NOT PRODUCTION-READY** (see "M10 — final readiness report" at the end). Started 2026-11-15. Scope: Flow only; Axon remains separate.

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
| 2–12 | Superseded by the M10 cycles below (12 independent cycles, 2026-11-17) | | | | |

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

## M7 — FE-03 responsive / RTL, FE-04 buttons and links (2026-11-16)
Tool: `scripts/ui-runtime-audit.mjs` (`650dbc36`), real build + real backend + Chromium, synthetic signed-in users. Layout = 29 routes × 6 viewports (desktop 1440×900; tablet 768×1024 / 1024×768; Android 412×915 / 915×412; phone 360×740) × en/ar = **348 screens**. Touch viewports use a mobile, touch-enabled context.

**FE-03 results**
| Check | Before | After |
|---|---|---|
| `<html dir="rtl">` on Arabic screens | 174/174 | 174/174 |
| Error screens / uncaught page errors / raw i18n keys / unnamed controls | 0 | 0 |
| Page-level horizontal scroll | 0 | 0 |
| 360px phone, routes with cut-off content (en / ar) | 12 / 9 | 6 / 5 |
| Android portrait, routes with cut-off content (en / ar) | 7 / 5 | 5 / 4 |
| Desktop and tablets, cut-off content | 0 | 0 |
| Chat Send covered by the Copilot button | tablets + phones | no |

Fixes (`9b68d087`): page roots fill the page column (Leads was 595px wide on a 360px screen and clipped); Settings nav stacks on phones (it took 200px of 360); page headers wrap and tab bars scroll on phones; chat composer leaves room for the Copilot button; toasts are RTL-aware and never wider than the screen. Guard: `tests/responsive-rules.test.mjs`.

Still cut off on phones (page-specific layouts, not changed): AgentOS tab row, AI Routing tab row, Integrations toolbar, Devices "+ Enroll Device", Social analyzer card, Design Studio properties panel (an editor built for wide screens). On landscape phones the Copilot button floats over some primary buttons (Run, Generate, Build My SaaS) until the page is scrolled.

**FE-04 results** (desktop, English, every visible control on every route, fresh page per click): **339 controls**.
| Outcome | Count |
|---|---|
| UI changed (dialog, panel, tab, form) | 148 |
| API request sent | 90 |
| Navigated | 13 |
| In-page anchor with existing target ("Skip to main content") | 29 |
| Disabled (empty form / unavailable) | 15 |
| No visible effect | 35 |
| Not clicked: destructive (Sign Out) | 1 |
| Harness could not reach (items in the collapsed "More" menu after reload) | 8 |
| Uncaught errors / error screens / dead or unsafe links / external links | 0 |

The 35 "no visible effect" are almost all the tab or filter that is already selected (e.g. "All", "Chat", "Dark"). One was a real defect: Design Studio zoom `+`/`−` showed "100%" whatever the zoom; fixed in `11fd82a0` (initial fit now shows 78%, then 93%, 65%).

Observations for M8:
- Marketplace, Plugins, Sandbox and AI Routing call `/marketplace/*`, `/plugins/*`, `/sandbox/*` (no `/api` prefix). With `VITE_API_URL` unset, Vercel's rewrite answers them with `index.html` and these pages show "Could not load …". They work only if `VITE_API_URL` points at the backend: verify in production.
- `/api/auth/refresh` shares the 10-per-minute-per-IP `auth` limit with login. Every full page load refreshes the session, so many reloads, or many users behind one office IP, get 429 and a full-screen "Connection error". Reproduced locally.

## M8 — Section 5, internal services (2026-11-16)

Production checked read-only: Render API (services, deploys, logs, metrics), a read-only SQL session on the production database, the Vercel API, and HTTP requests through the production Vercel deployment (which rewrites `/api/*` to Render). Nothing in production was changed. This container cannot reach `*.onrender.com` directly, so `/health` on Render is evidenced by its own request logs.

| Service | Verdict | Evidence |
|---|---|---|
| Render web service `ai-automation-studio` (srv-d6705koboq4c7384n0cg) | PASS | Live deploy `bcd6fce` (#51), 2026-11-14. `/health` 200 every 5 s in logs. 0 error/critical log lines and one 500 in 7 days (2026-11-14, no log line kept). Memory 172 MB of 512 MB, CPU ≈0.4 %. `main` commits #52–#54 after it are frontend-only, so no backend skew. |
| Vercel frontend | PASS (fixed) | Production `26b4d72` (#54) READY. `/api/health/full` and `/api/health/providers` through the production domain reach Render (header `x-render-origin-server: uvicorn`). Security headers present. `VITE_API_URL` set for Production only. **Defect fixed:** a missing `/assets/*.js` returned `index.html` with 200 (checked on the PR #57 preview); see `5b802993`. |
| PostgreSQL `ai-studio-db` | PASS | PostgreSQL 18.6, `vector` 0.8.1, 135 public tables, 48 MB of 1 GB, no `alembic_version` table (matches the Alembic archive in M3). Pool 4/4 idle. Note: CI uses pg16 (`pgvector/pgvector:pg16`), production is 18. |
| Redis `flow-production-redis` | FAIL (not wired) | The instance exists (free plan, persistence off, internal only) but the service has no `REDIS_URL`: logs say "using local in-process backend" and the `redis` probe is DEGRADED. Cache, rate limits and the event bus are per process. Safe while `numInstances` = 1; wrong as soon as it scales. |
| Docker image | BLOCKED locally | `docker build` here cannot reach Docker Hub (429) or `deb.debian.org` (proxy 403). Evidence instead: Render built this Dockerfile for the live deploy, and CI #380's Docker job passed. Node 20 in the `frontend` stage is past end of life (April 2026). |
| AI gateway | PASS | `/api/health/providers`: Anthropic key present (108 chars, no whitespace), circuit closed, 0 consecutive failures; default `anthropic`. `dev_mock` shows "available" but is not in the default chain (owner build mode only). Only one real provider, so no failover. |
| OAuth | PASS for Google, start only (fixed) | `/api/auth/google` → 307 to Google with `state` and an HttpOnly `oauth_bind` cookie; callback host `ai-automation-studio-kohl.vercel.app`. The full round trip needs a real Google account: BLOCKED by the no-real-accounts rule. GitHub and Microsoft answer 503 (not configured). **Defect fixed:** their buttons still showed and led to a bare JSON 503 page; see `7ee3eb43`. |
| Email (SMTP) | BLOCKED | Sending is the only real test and real messages are forbidden. No SMTP line in 7 days of logs, and the env values cannot be read through the tools available. |
| File storage | FAIL (risk) | `storage` probe OK (56 GB free), but the service has no persistent disk: `workspaces/`, `dist_packages/`, generated images and deliverables are on the container's disk and are lost on every deploy or restart. |
| Notifications / WebSocket | PASS | Dispatcher wired for 16 event types; `ws_connections` 2 at the time of the check. |
| Payments (Stripe) | PARTIAL | `STRIPE_SECRET_KEY` set and the `billing` probe is healthy. Whether it is a test or live key was not checked (values were not decrypted). Checkout is an M9 journey, sandbox only. |
| Error monitoring | FAIL (none) | No Sentry or other external tracker. Only logs, the in-process `alerting` service and Render's default failure e-mails. |
| Queues / scheduler | PASS (single instance) | Job runner: 5 completed, 0 failed, 0 dead. Automation scheduler started (60 s). Both in process, which again assumes one instance. |
| Other Render services | Note | `ai-automation-studio` background worker suspended since 2026-09-03 (crash-looping), `ai-automation-studio-1` suspended by the owner, two PgHero services. `flow-api` belongs to the separate `flag` repository and was not audited. |

Defects fixed in this milestone:
- `5b802993` Service worker. It cached every GET without `/api/` in the URL, including signed-in calls to the backend's `/marketplace`, `/plugins` and `/sandbox` routes (on the `VITE_API_URL` origin with an `Authorization` header), and served them offline to whoever used the device next. It also cached the HTML returned for a missing chunk. Now only same-origin navigations (as the app shell) and `/assets/` files are cached; the cache is renamed so old entries are deleted. `vercel.json` no longer rewrites `/assets/`. Test: `tests/service-worker.test.mjs` (fails on the old files, passes now).
- `f271f200` The dependency monitor logged the same `GITHUB_CLIENT_ID` warning 288 times a day; it was the only warning in production logs. Now one INFO line when the set changes.
- `7ee3eb43` Sign-in page shows only configured OAuth providers (`/api/auth/oauth-config` now lists them).
- `56b810fb` pytest printed a `PytestDeprecationWarning` on every run.

Tests after M8: backend 3261 passed / 28 skipped, E2E 14/14, frontend 552/552, `tsc` and `eslint` clean.

Needs an owner decision (not changed, production settings):
1. Set `REDIS_URL` on the Render service to the existing Redis instance, or delete the instance.
2. Persistent storage for builder output and generated files (Render disk or object storage).
3. An error tracker (e.g. Sentry) for backend and frontend.
4. `/api/health/full` is public and returns the exact PostgreSQL version, API key lengths, pool, disk, job and WebSocket counts. Suggest limiting it to admins.
5. Set `VITE_API_URL` for Preview too, so previews can load Marketplace, Plugins and Sandbox.
6. Move the Docker `frontend` stage from Node 20 (end of life) to Node 22.
7. Clean up the suspended worker and the second web service.

Seen but not fixed: `/api/ws/ticket` gets a 401 about every 31 s from a client whose session has ended (backoff capped at 30 s); it is harmless in load but the client never stops trying.

## M9 — Section 6, the 12 user journeys (2026-11-16)

`tests_e2e/test_journeys.py` runs each journey against the real app (real lifespan, PostgreSQL 16, every router) with synthetic users only. The AI vendor call goes to an offline sink (DevMockProvider registered as `anthropic`); email goes to the console; payments go through a Stripe webhook signed locally with a test secret, so no Stripe account, no network call and no charge. Result: 12/12 PASS, with the parts below marked BLOCKED where this environment cannot reach the real thing.

| # | Journey | Result | What it checks |
|---|---------|--------|----------------|
| 1 | Account | PASS | Register, unverified login refused, verify by token, login, sessions list, refresh, logout, logout-all. Real inbox and Google OAuth round trip: BLOCKED (no SMTP, no OAuth client here). |
| 2 | Organization | PASS | Create org, Free plan refuses a second seat (409), invite and accept, role change, viewer cannot write, other org sees nothing. |
| 3 | Building apps | PASS | Project, describe, generated files, preview, edit, re-run, export. |
| 4 | AI assistant | PASS | Stream a reply, history saved, reload restores it, another user cannot read it. |
| 5 | Leads | PASS | Website capture with API key, AI qualification, follow-up run stops at the approval gate, approve, run completes, outcome recorded, notification sent. |
| 6 | Automation | PASS | Bad definitions refused (422), run to completion, AI step fails visibly during an outage, retry succeeds after the provider is back. |
| 7 | Devices | PASS | Enroll token is single-use, session start, another org gets 404 on every device/session route, stop, revoke, revoked device gets no session token. Real device agent: BLOCKED. |
| 8 | Content | PASS | Creation private until published, feed, like/save idempotent, library catalog, lesson locked (403) before purchase, opens after a sandbox purchase, locked again after refund, unknown lesson 404. |
| 9 | Careers | PASS | Profile, import an alert twice without duplicates, matching role ranked first, save a job. |
| 10 | Billing | PASS | Plans, checkout without a payment provider refuses (503), unsigned webhook refused (400), signed subscription webhook moves the org to Starter and limits change, cancellation returns it to Free, zero payments recorded. Stripe test-mode checkout: BLOCKED (the Stripe connector's sign-in has expired and no test key is set here). |
| 11 | Security | PASS | Forged and expired tokens, revoked sessions, account lockout after repeated failures, every GET route with a malformed id, oversized and malformed input. |
| 12 | Recovery | PASS | AI provider down: the user gets an error event, leads and health keep working; provider back: the conversation continues, no lost or duplicated messages, no empty reply stored, the lead created during the outage exists once. |

Defects the journeys found and this milestone fixed:
- `73866a33` **Stripe subscription webhooks always failed.** stripe-python 8+ objects are not dicts and the handler called `.get()` on them, so every `customer.subscription.*` event returned 500 and the plan never changed after a payment. Payment-method, invoice and credit-balance syncs failed the same way, silently. Production `billing_events` holds only 2 expired-checkout events, so no real subscription was affected yet. Same commit: `/api/subscription/checkout` answers 503 when Stripe is not configured.
- `985cfd87` Org checkout and billing portal answered 500 when payments are not configured; now 503.
- `21d64af7` Automation definitions with an unknown step kind (e.g. `emial`) were saved and then ran as a silent no-op that reported success; duplicate ids, unknown dependencies and empty names were accepted too.
- `a4867364` A device session or device belonging to another org answered 400; now 404, the same as one that does not exist.
- `229afb83` Creation routes (`/api/creations`) refused a client that holds only the account access token.
- `a9fe3f17` The same email in different case created a second account; a 10,000-character display name was accepted.
- `8ae7dbb7` 31 GET routes answered 500 for a malformed id in the URL; now 404.
- `ec70bce4` Two duplicate OpenAPI operation ids (shadowed `GET /api/ai/models`, the build proxy).

Unit guards: `tests/test_m9_journey_fixes.py` (5 of its 6 tests fail on the code before the fixes).

Tests after M9: backend 3267 passed / 28 skipped, E2E 26/26, `ruff` clean on changed files. Frontend unchanged in M9 (552/552 at M8).

Residual risks (not changed, need a decision):
1. Retry amplification: one AI workflow step during a provider outage made 18 provider calls and took about 20 s (engine step retries × gateway retries × registry retries). The circuit breaker opens, but only after the inner layers have retried.
2. After an outage the breaker keeps the only AI provider closed for 30 s; users see "Retry in 30s" even once the provider is back. Expected design, worth a shorter cooldown or a second provider.
3. Account lockout is per account, so anyone who knows an email can lock that user out for 15 minutes.
4. Single-session logout leaves that session's access token valid for up to 5 minutes (logout-all revokes it).
5. The Free plan has 1 seat, so a Free org cannot invite anyone; confirm this is intended.
6. On shutdown, a workflow waiting for approval logs "workflow usage record failed … pool is closed"; the run's usage is not recorded for that shutdown.

## M10 — 12 independent cycles (2026-11-17)

Runner: `scripts/audit_cycle.sh <n> <out>` (summary by `scripts/audit_cycle_summary.py`). Each cycle starts from nothing shared with another cycle: three new empty PostgreSQL 16 databases, a new `SESSION_SECRET`, backend and frontend tests in a new random order (pytest-randomly and vitest shuffle, seed recorded), a fresh production build, a fresh backend process and a new synthetic account. Synthetic data only; AI goes to an offline sink or is unconfigured, email to the console, Stripe unconfigured (journey 10 signs its sandbox webhook locally). Nothing touched production.

Each cycle runs, in order:
1. Static gates: `py_compile`, ruff ratchet (≤ 104), `ci_secret_scan.py`, `ci_schema_check.py` (lifespan schema against an empty DB).
2. Backend unit/integration suite, then the end-to-end suite (isolation, idempotency, the 12 journeys), each on its own empty DB.
3. Frontend: Vitest, `tsc --noEmit`, `eslint --max-warnings 0`, `vite build`.
4. Dependencies: `npm audit`, `pip-audit -r requirements.txt`.
5. The built app in Chromium, served like `vercel.json` (files, `/api` proxied, missing `/assets/` = 404, else `index.html`) over the fresh backend: every route's every visible control clicked on desktop (destructive ones listed, not clicked), every route laid out at 1440 px and 360 px in English and Arabic, a missing old chunk must 404, and the backend log must have no ERROR/CRITICAL line.

A cycle is PASS only if every step exits 0 and the browser run has no error screen, uncaught page error or failed click.

| Cycle | Commit | Seed | Backend | E2E | Frontend | Browser (controls / screens) | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | `4d5f4157` | 180472529 | 3267 / 28 skipped | 26 | 554 | 304 / 116 | PASS |
| 2 | `4d5f4157` | 1072835695 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 3 | `4d5f4157` | 227445813 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 4 | `4d5f4157` | 39635662 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 5 | `4d5f4157` | 34975438 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 6 | `4d5f4157` | 505598767 | 3267 | 26 | **553 / 554** | 304 / 116 | **FAIL** (flaky test, fixed in `f0be560b`) |
| 6 repeat | `f0be560b` | 335478055 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 7 | `4d5f4157`* | 241694826 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 8 | `4d5f4157`* | 691883648 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 9 | `f0be560b` | 548973697 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 10 | `f0be560b` | 660028389 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 11 | `f0be560b` | 1002664283 | 3267 | 26 | 554 | 304 / 116 | PASS |
| 12 | `f0be560b` | 461025915 | 3267 | 26 | 554 | 304 / 116 | PASS |

\* Cycles 7 and 8 started on `4d5f4157`; the test-only fix of `f0be560b` was already in the tree when their frontend step ran.

Same in every cycle: secret scan clean, schema check OK, ruff at baseline, `tsc` and ESLint clean, build OK, `npm audit` 7 moderate / 0 high (dev tooling: minimatch via typescript-eslint, no upstream fix), `pip-audit` 0 known vulnerabilities, missing chunk 404, 0 backend ERROR lines, about 29 minutes per cycle. Per-cycle summaries: `/mnt/project-files/flow-audit-m10/cycle-<n>.json` in the project; full logs were kept in the audit container only.

What the cycles found and what was done:
- `69e99966` **AgentOS → Jobs crashed to the error screen** for an account with no organization selected: `/api/jobs/stats` answers 400 with a JSON body that the tab read as stats. Test: `features/agentos/__tests__/JobsMonitor.test.tsx` (fails before the fix).
- `227505d2` The runtime security monitor logged a CRITICAL "possible secret" for the E2E harness's synthetic password on every local boot; `tests_e2e` is now skipped like `tests` (neither is in the Docker image).
- `156e1f67`, `4d5f4157` Four tests passed only in file order (shared mock history, a shared approval-registry key, a shared gauge, skill files loaded by an earlier test). Found by the random order of the first attempt at cycles 1 and 2 (`/mnt/project-files/flow-audit-m10/` keeps only the final run).
- `f0be560b` One frontend test pressed Escape before the drawer's listener was attached when the machine was loaded (cycle 6).
- `43e6bd0a` The UI audit counted controls inside the closed "More" menu as visible (Chromium keeps their box) and reported 7 false failed clicks; fixed in the audit script, which now also clicks `<summary>`.

Seen in every cycle, not fixed (minor, 360 px phones): content cut at the screen edge on `/design` (Properties panel), `/devices` ("+ Enroll Device"), `/social` (YouTube card), and tab buttons on `/agentos` and `/ai-routing`, in both languages. 24 controls do nothing visible, all of them the tab or filter that is already selected.

BLOCKED in every cycle (not counted as passed): Docker image build (Docker Hub rate limit and package mirror blocked here; the last proof is CI #380 and the live Render deploy); real email delivery; Google OAuth round trip; Stripe test-mode checkout (connector sign-in expired, no test key); a real device agent; Redis (not configured anywhere); behaviour of the deployed production stack with these fixes, because they are not deployed.

## M10 — final readiness report (2026-11-17)

**Verdict: NOT PRODUCTION-READY.** The code on this branch (`f0be560b` and later docs) passed 12 independent cycles (11 first time, 1 after a test-only fix), the 12 user journeys and a real-browser sweep of every route. That is evidence about this branch in a test environment. It does not make the live platform ready, for these reasons:

1. **None of M1–M10 is live.** Production runs older code: Render `bcd6fce` (main #51, deployed 2026-11-14) and Vercel `26b4d72` (main #54). The live backend still has the bugs fixed here, including the Stripe subscription webhook that fails on every subscription event (`73866a33`), the 500s on malformed ids, the duplicate accounts by email case, the service worker that caches signed-in API responses, and the AgentOS Jobs crash. PR #57 targets PR #56's branch, and neither is merged to main.
2. **CI has not run on this work.** `ci.yml` only runs for pull requests to main, so PR #57 got Vercel previews only. Merging needs a PR to main and a green CI run there.
3. **Owner decisions still open (M8):** set `REDIS_URL` (rate limits and the circuit breaker are per process without it), persistent storage for generated files, an error tracker, make `/api/health/full` admin-only (it is public and shows internals), `VITE_API_URL` for Preview, Node 20 → 22, clean up the suspended services.
4. **Residual risks (M9):** retry amplification (18 provider calls, about 20 s for one failed AI step), 30 s breaker cooldown with a single AI provider, per-account lockout usable to lock a user out, 5-minute access token after single logout, Free plan has 1 seat.
5. **Not verified here (BLOCKED):** Docker build, real email, Google OAuth, Stripe test checkout, a real device agent, Redis.
6. **Outside this audit:** licensing, payment-provider eligibility for the UAE business, privacy and data-retention obligations (release blocker 6 above).

Production at the time of this report (read-only checks, 2026-11-17 09:25 UTC): Render web service healthy (`/health` 200), no ERROR/CRITICAL application logs and no 5xx responses in the previous 24 hours; production DB holds 14 users and 2 Stripe events (both expired checkouts).

Suggested order to reach ready: (1) open a PR from this work to main and get CI green; (2) decide items 3.1 and 3.4 at least; (3) deploy to a staging service first and repeat one cycle plus journeys 1, 10 and 12 against it, with a Stripe test key and a test SMTP inbox; (4) then production, with the Stripe webhook watched for the first real subscription.
