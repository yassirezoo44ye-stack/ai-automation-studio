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
