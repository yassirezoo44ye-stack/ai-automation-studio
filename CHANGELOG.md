# Changelog

Entries below this point are generated automatically by the `release` job
in `.github/workflows/ci.yml` (`scripts/ci_release.py`) after each
successful deploy to `main`.

## v1.0.0

### Other
- fix(ci): correct post-deploy health-check fallback URL
- chore: trigger redeploy — DB DNS should now be resolved
- fix(security): check run ownership on /ws/system/{run_id}, not just run_id knowledge
- fix(security): SSRF, deliverable ownership, and WS channel isolation

## v1.0.1

### Other
- fix(ci): scope release-tag discovery to semver tags only
- feat(branding): rebrand product name to Flow
- fix(design-studio): resume last saved design on load
- fix(design): enforce project ownership on canvas read/delete
- fix(package): escape remaining app name injection paths
- feat(package): isolate build downloads via package_artifacts ownership table
- fix(package): escape generated app names
- fix(package): enforce project ownership for packaging
- fix(design-studio): apply template JSON instead of just clearing canvas
- feat(brand-kit): connect panel mutations to persistence
- feat(brand-kit): add actions layer
- feat(brand-kit): add persistent mutation service layer
- chore(auth): improve network diagnostics
- refactor(brand-kit): extract indexeddb repository layer
- feat(brand-kit): add persistence lifecycle owner (Phase A)
- fix(design-studio): connect AI Design Generation to its working backend
- refactor(design-studio): align new handlers with existing component style
- fix(design-studio): wire up Line tool, layer ordering, JSON import, and drag/resize/rotate undo

## v1.0.2

### Other
- docs(ai): add AI entry-point unification architecture audit
- fix(ai-schema): retarget ai_usage_log foreign key to ai_conversations
- fix(ai-gateway): enforce conversation ownership across gateway, services, and memory layers
- fix(build): enforce project ownership before workspace access

## v1.0.3

### Other
- docs(ai): add §9 P1 design-review findings to the unification audit
- fix(ai-gateway): enforce prompt ownership across PromptEngine

## v1.0.4

### Other
- fix(commands): block unsafe plugin loading through modify command
- fix(commands): disable unaudited plugin registration endpoint

## v1.0.5

### Docs
- align execution plan around paid pilot validation
- reflect completed security hardening in project status

### Other
- fix(chat): log run_stream exceptions server-side
- docs(gtm): define initial ICP hypothesis and update execution backlog
- chore: remove stale tracked demo workspace artifacts
- docs(ops): add Single Source of Truth governance rule to PROJECT_STATUS.md
- docs(ops): add Phase 1 operating docs — backlog, launch checklist, discovery log, status

## v1.0.6

### Docs
- document pilot readiness and live demo guidance

### Other
- docs(icp): protect ICP baseline from premature revision

## v1.0.7

### Other
- feat(agents): wire cost reporting into plan_agent and analyze_agent
- feat(agents): add max_cost_usd/max_tokens budget with live cancellation
- feat(agents): dedup POST /api/agentos/run via client-supplied run_id
- feat(jobs): support idempotency_key on JobQueue.submit
- fix(integrations): recover from failed webhook deliveries instead of permanent duplicate
- feat(core): add generic idempotency layer (idempotency_keys table)
- fix(kernel): wrap HotReloader.reload_builtin's exec/register in try/except
- fix(kernel): make HotReloader.reload_plugin roll back on partial failure
- feat(ai-reliability): wire circuit breaker + bulkhead into remaining AI router call sites
- feat(ai-reliability): wire circuit breaker into chat.py/build.py live AI traffic
- feat(observability): expose queryable current-health accessor on HealthRegistry

## v1.0.8

### Other
- feat(ai-gateway): migrate chat.py + build.py to InferenceEngine

## v1.0.9

### Features
- AI Business App Builder — full orchestration feature

### Fixes
- move App Builder job handler registration after get_job_queue import
- resolve ruff lint regressions blocking CI (restore count to 104 baseline)
- strip trailing slash from APP_URL to prevent double-slash in email links
- eliminate setState-in-effect lint warning in AuthPage reset tab
- add password reset frontend page (P0 gap — backend was complete, frontend missing)

### Docs
- mark password reset frontend as resolved in PROJECT_STATUS.md

### Other
- fix(docker): include migrations in production image
- Merge PR #1: AI Business App Builder — production-ready
- App Builder: crash recovery, handler hardening, frontend polling fixes
- App Builder: async build pipeline, retry, RLS, real progress polling
- docs(auth): document sub_token logout-revocation P0 as a decision, not a silent fix
- Merge origin/main (chore: release v1.0.8 [skip ci]) before pushing Phase 1 auth fixes
- fix(auth): harden OAuth and refresh token lifecycle
- fix(auth): log Google OAuth token-exchange failures without changing the client response
- test(auth): reduce Google OAuth E2E test duplication
- test(auth): add Google OAuth end-to-end coverage
- feat(ai): enforce context budget in gateway enrichment
- fix(ai): enforce context budget on live chat
- fix(multitenancy): scope workflow engine approve/reject/visibility to caller's org
- fix(multitenancy): scope event bus replay/dlq to caller's org
- fix(security): restrict admin API-key scope to platform-admin allowlist
- fix(security): close workspace-trust + identity-spoofing chain in commands/plan/agent execution
- fix(security): derive runtime execution workspace from verified project ownership + close execution IDOR
- fix(security): require auth + restrict topic subscription on /ws/agent
- fix(security): harden path-traversal check with is_relative_to()
- fix(auth): remove dead sub_token cookie fallback
- fix(auth): repair token lifecycle and close auth gaps
- feat(ai-gateway): migrate agents.py + design.py + tasks.py to InferenceEngine

## v1.0.10

### Fixes
- harden AI provider diagnostics and migration image validation

## v1.0.11

### Other
- fix(ai): resolve ProviderID values correctly on Python 3.11

## v1.0.12

### Features
- Flow UI redesign + real backend integration (App Builder, Runs, Integrations)
- Flow UI/UX redesign — sidebar, topbar, dashboard, agents, automations
- connect App Builder, Runs, Integrations to real backend APIs
- Flow UI redesign — new sidebar, dashboard, App Builder, Runs, Integrations

### Fixes
- use pid.value instead of str(pid) in registry default() — Python 3.11 Enum.__str__ returns 'ProviderID.anthropic' not 'anthropic'
- resolve removeChild crash on page navigation
- add migrations/ to Docker image — resolves Render startup ModuleNotFoundError
- propagate active project_id to AgentOS run_agent and DevWorkspace

### Tests
- build_stream edge cases — valid/missing/unauthorized project_id, provider available/unavailable, generated files, preview, i18n

### Other
- Merge remote-tracking branch 'origin/main' into claude/flow-ui-redesign-rye5o6
- feat(ai-workspace): 3-column layout redesign — conversation rail, context panel, RTL
- diag: safe provider probe endpoint + key presence/length in health/full
- fix(config): correct GEMINI_API_KEY env var name in docs and render.yaml
- diag: distinguish 'no keys' vs 'circuits open' in stream_with_events log
- fix(migrations): add __init__.py to make migrations a proper Python package
- fix(projects): return full Project object from POST /api/projects
- feat(home): App Builder Command Center + project_id propagation fix
- fix(ui): resolve react-hooks/set-state-in-effect warnings
- merge: integrate auth/CI hotfixes from remote into conflict resolution
- merge: resolve Flow UI redesign conflicts with main
- fix(auth): API key requests silently 401'd by api_auth_middleware
- fix(ci): smoke-test URL warning, PRODUCTION_URL required, render.yaml CORS docs
- fix(prod): Phase 1 — split-deploy connectivity, security headers, build guard
- fix(agentos): propagate project_id through plan/deliberate paths
- feat(i18n): wire Arabic i18n across AppBuilderPage, RunsPage, IntegrationsPage, HomePage
- ci: resolve pre-existing ruff ratchet drift

## v1.0.13

### Fixes
- classify AI provider billing failures and prevent App Builder 500s (#5)

### Other
- fix(lint): remove unused BillingRequiredError import from AppBuilderPage
- feat(ui): billing error UI — 402 surfaces as recovery overlay, not crash
- feat(ai): production-grade provider error classification and graceful propagation

## v1.0.14

### Other
- feat(design-studio): add app builder tree and AI build workflow

## v1.0.15

### Other
- Merge remote-tracking branch 'origin/main'
- merge(app-builder): DOM cleanup crash fix + SSE abort + regression tests into main
- fix(app-builder): prevent DOM cleanup crash on generation errors

## v1.0.16

### Fixes
- expose structured AI provider billing errors in modify_app

### Tests
- fix stale stats fetch assertion (fetch_calls == 1 -> 2 with scope verification)

### Other
- feat(app-builder): wire runtime into app builder page and bottom bar
- feat(app-builder): live runtime panel with 7-state machine
- feat(app-builder): add typed runtime SSE service
- fix(build): enforce org quota on build plan
- feat(app-builder): AI Software Factory Phase 2 — build plan + copilot + bottom bar
- fix(tests/i18n): stabilize app builder timeout + Arabic nav label
- feat(platform): FLOW Command Center + AI-aware nav

## v1.0.17

### Other
- feat(ui): flow visual identity — dark-first + node integrations + use cases

## v1.0.18

### Fixes
- align SSE billing errors with frontend handling

### Other
- fix(ci): restore lint gates — ruff 121→79, ESLint 0 errors/warnings
- fix(i18n): complete Arabic translation for App Builder
- feat(ui): android-ready mobile upgrade — PWA viewport, runtime console, SVG icons, workspace layout
- fix(ai-gateway): preserve billing error in complete_with_events
- fix(agentos): resolve "Runtime ''unknown''" error with workspace pre-flight
- feat(design-studio): UI PRO PRO PRO MAX — token compliance, SVG icons, i18n
- feat(training): build production training studio UI
- feat(training-studio): Phase 1 foundation — DB + provider interface + shell UI
- security(ws): add one-time websocket authentication and process cleanup

## v1.0.19

### Other
- fix(security): update CSP connect-src to production backend (viio)

## v1.0.20

### Other
- fix(agent-builder): remove unsupported Anthropic stream temperature

## v1.0.21

### Other
- feat(app-builder): redesign entry screen as focused minimal build prompt

## v1.0.22

### Other
- fix(ci): correct smoke-test fallback URL to viio production service

## v1.0.23

### Features
- zero-cost dev mode for owner account via DevMockProvider (#6)
- zero-cost dev mode for owner account via DevMockProvider

### Other
- fix(test): replace get_event_loop().run_until_complete with asyncio.run()
- merge: sync with main, resolve conflicts — preserve DevMockProvider
- feat(ui): simplify FLOW home page and sidebar — Progressive Disclosure
- fix(agent-builder): remove unsupported Anthropic stream temperature

## v1.0.24

### Other
- fix(auth): surface actual backend error in register/login error handlers (#7)
- fix(auth): surface actual backend error in register/login error handlers

## v1.0.25

### Other
- fix(android): support rotation and preserve app builder drafts

## v1.0.26

### Other
- ux: simplify sidebar from 18 items to 7 for everyday users
- feat(landing): add Flow marketing landing page with EN/AR i18n
- security(auth): shorten sub_token TTL and re-mint it on refresh (Option A)

## v1.0.27

### Other
- ux: set app-builder as the default landing page after login

## v1.0.28

### Features
- improve Flow settings, authentication, devices, and SaaS Factory
- SaaS Factory F-1/F-7 + Business Lab Phase 1 fixes
- add Flow Library module with 3M+ book catalog support
- improve Flow settings, authentication, devices, and SaaS Factory
- consolidate sidebar to AI Business Workspace navigation
- stabilize multi-device control and app builder
- add Flow Discover and unified creations
- harden Flow multi-device control execution
- add Flow multi-device control AgentOS foundation

### Fixes
- automation_runs lifecycle, leads NameError, Render 409, cache auth + platform-wide code quality audit
- resolve all remaining ruff quality issues — clean zero-error baseline
- resolve 52 ruff code-quality issues across codebase
- clean up unused imports and dead code across project
- remove dead code, duplicate imports, and undefined-name annotation
- mark automation_runs enqueue_failed on JobQueue error; scope bp_plans DELETE
- restrict runtime cache endpoints to admin+
- resolve 26 pre-existing CI failures in test suite
- rename test_gen_handler to avoid pytest collection
- resolve SaaS Factory gate blockers

### Other
- fix(execution): resolve Run Failed for AI-generated subdirectory projects + security hardening
- fix(execution): three-layer defense for Run Failed on AI-generated subdirectory projects
- fix(execution): resolve "Run Failed" when AI builder generates files in subdirectory
- fix timing side-channel: constant-time response for non-existent accounts
- fix test_api_auth: isolate IP rate-limit test from per-email lockout
- pro max batch 3: GZip compression + per-email login lockout
- security: add JWT revocation, complete audit log coverage, and regression tests
- fix(security): reduce access token TTL from 15 min to 5 min (H3 hardening)
- fix(security): resolve phase 2 audit findings (WS ownership, session invalidation, billing meter, and OAuth verification)
- fix(tests): collapse remaining nested with statements in test_stats.py (SIM117)
- Merge origin/main into claude/extract-features-flow-studio-0cnm4v
- refactor: comprehensive code quality audit — simplify, deduplicate, harden exceptions
- fix(agent): remove unused imports and dead variable assignments
- fix(routers): remove remaining unused imports in discover and training
- fix(chat): save assistant message before yielding done event
- chore: switch to split-deploy architecture (Vercel frontend, Render API only)
- fix(leads): initialize run_id=None before try block to prevent NameError
- fix(ci): treat Render 409 as success in deploy step
- fix(app-builder): harden spec JSON repair and add regression tests
- fix(lint): remove unused imports from test_audit_fixes.py to stay within ruff baseline
- fix(security): P0/P1/P2 audit fixes — IDOR, automation, email, leads, SaaS Factory
- fix(ci): remove unused imports/variables to bring ruff count below 104 baseline
- fix(saas-factory): raise on incomplete build to stop pipeline reaching LIVE
- fix(business-plans): prevent retry from overwriting PAUSED plan status
- fix(business-plans): lifecycle status update and SSE GENERATING transition on retry
- fix(business-lab): P0-A guard COMPLETED sections + P0-B rebuild context on retry
- fix(business-lab): fix DAG deps, dead context reads, and plan completion guard
- fix(ai-workspace): scope task strip to current conversation and patch agent_run log
- fix(copilot): prevent [Context:] leak in stored messages and separate workspace
- feat(saas-factory): add PENDING_REVIEW phase and security review UI
- fix(workflow): add organization_id to WorkflowRun context for notification routing
- Fix CI lint failures: ruff (F401/F841) and ESLint (exhaustive-deps, a11y, set-state-in-effect)
- merge: integrate origin/main attribution routing into PR branch
- test(backend): add automation scheduler and upload middleware tests
- fix(pages): gate data fetches on org context being ready
- fix(leads): correct follow-up email step schema + add backend tests
- fix(runtime): JS project detection + CSP allow Google Fonts
- fix(app-builder): i18n export labels + AICommandBar status-aware errors
- fix(middleware): narrow exception swallowing to ClientDisconnect only
- fix(upload): add ASGI-level request body size limit middleware
- test(build): add upload size-limit tests — 50 MB per-file, 200 MB total
- fix(social): eliminate TOCTOU race in social oauth callback
- fix(auth): eliminate TOCTOU race in oauth_exchange — make get+delete atomic
- fix(build): add 50 MB per-file and 200 MB per-request size caps to upload endpoint
- fix(gemini): repair silent image-drop bug in _to_gemini_contents
- fix(oauth): include FRONTEND_URL in CORS allowed origins and document in render.yaml
- fix(oauth): add FRONTEND_URL so post-OAuth redirect targets frontend, not backend
- fix(tests): resolve all 113 test failures — 0 failures, 2677 passing
- fix(social): wire schema init into app startup — migration 014 gap
- feat(social): Instagram Reels integration via Meta Graph API (Step 3)
- fix(social): independent review — 3 bugs found and fixed
- feat(social): TikTok Content Posting API integration (Step 2)
- feat(social): Phase 1 foundation — migration, provider base, router
- fix(auth): atomic get_and_delete_if_matches for OAuth state to prevent DoS
- fix(auth): add browser-binding nonce cookie to restore Login CSRF protection (FINDING-1)
- fix(auth): replace cookie-based OAuth state with server-side cache
- fix(deploy): proxy /api/* to Render and correct backend URL in docs
- fix(deploy): proxy /api/* to Render and correct backend URL in docs
- fix(app-factory): distinguish Preview from Running; fix build toasts; guard short prompts
- fix(events): register lead.qualified in EVENT_TYPES
- fix(notifications): fix navigation, add real-time push and mute guard for lead.qualified
- feat(new-project): rewrite as canonical project creation entry point
- fix(navigation): establish browser history and home root
- feat(navigation): consolidate engine entry points
- feat(project-workspace): add URL project workspace contract
- fix(auth): resolve OAuth account-takeover security blocker
- fix(auth): ESLint clean-up + MFA tests + DEV_ACCOUNT_EMAIL config
- feat(auth): Phase 1 — MFA frontend, OAuth MFA gate, deep-link routing, env var cleanup
- fix(business-lab): persist section FAILED status and add startup recovery
- fix(auth): add /api/track to PUBLIC_PREFIXES
- fix(attribution): route POST /api/track to Render backend via VITE_API_URL
- feat(marketing): add conversion attribution
- merge: agency marketing landing + UTM attribution
- feat(marketing): position Flow for small agencies
- merge: SaaS Factory pipeline + UI redesign (sidebar/header)
- feat(ui): restructure sidebar to 4 semantic groups + enrich header
- feat(saas-factory): add SaaS Factory pipeline and UI
- feat(feed): remove mock initial state, short commercial CTAs, micro-learning (#11)
- feat(feed): remove mock initial state, short commercial CTAs, micro-learning
- feat(flow): complete commercial lead engine (#10)
- fix(settings): resolve react-hooks/set-state-in-effect and exhaustive-deps in ApiKeysTab
- fix(leads): resolve CI lint and test path blockers
- feat(flow): complete commercial lead engine access
- feat(leads): enable commercial lead capture and email follow-up
- feat(leads): add agency lead engine MVP
- fix(feed): handle empty production feed
- fix(discover): use correct JWT decoder for interactions
- feat(discover): add optional immediate publishing
- fix(feed): disable interactions on mock content
- feat(automation): complete cloud routines frontend and test coverage
- feat(automation): complete cloud routine execution flow
- feat(ai): add monthly usage cost reporting
- feat(feed): add initial interaction counts and harden state
- feat(feed): implement Like/Save persistence (Phase 2)
- feat(phase1): implement policy blocked_patterns and approval notifications
- fix(ws): remove JWT fallback from remaining websocket hooks
- fix(ws): migrate notifications to ticket auth
- fix(business-plans): validate plan ids as UUIDs
- fix(business-lab): replace JWT query-param SSE auth with short-lived ticket flow
- fix(frontend): recover from stale dynamic chunks
- fix(app-builder): normalize stream build errors
- fix(app-builder): prevent single-character project names causing HTTP 422
- fix(feed): repair sharing and disable unavailable comments
- fix(business-lab): scope section workflow queries by organization
- fix(business-lab): align workflow steps with engine contract
- fix(business-lab): fix RLS on plan detail and WorkflowEngine API mismatch
- fix(business-lab): use scoped connection for plan creation
- fix(app-builder): harden plan mode for dev account
- fix(discover): use shared auth infrastructure
- fix(discover): enforce source uniqueness
- feat(discover): add publish flow for apps and agents
- fix(discover): fix auth middleware + SQL pagination bug
- fix(devices): align session response contract
- fix(devices): align enrollment token response contract
- fix(app-builder): restore static preview runtime
- fix(devices): inject permission dependencies
- feat(feed): wire real data and build intents
- feat(feed): add TikTok-style Flow Feed foundation
- fix(runtime): detect static HTML apps before node
- fix(build): make dev account matching case-sensitive
- feat(app-builder): wire approved plan through build pipeline
- feat(business): add Business Lab
- feat(automation): add persistence and definitions API
- ux(simplify): trim sidebar to 3 items and simplify landing copy
- feat(inference): add POST /api/ai/chat for App Builder copilot
- fix(app-builder): skip plan step when modifying from workspace
- feat(app-builder): wire MODIFY + EXPORT flow
- feat(dev_mock): dynamic landing page from prompt — no more generic template
- fix(build): robust email comparison in _is_dev_account (case + strip)
- feat(build): free unlimited usage for owner account via prompt-aware dev_mock
- fix(build): remove dev_mock bypass — owner account now uses real Claude API
- fix(i18n): disable browser auto-translate to prevent Arabic mangling
- fix(anthropic): pop temperature/top_p from complete() path, catch TypeError
- ux(app-builder): simplify interface for everyday users

## v1.0.29

### Other
- Add protected visual study library with Payhip purchase access (#20)
- Merge pull request #19 from yassirezoo44ye-stack/feature/career-assistant
- fix(careers): retain uncertainty after listing verification fails
- feat(careers): add private job-alert assistant with Gmail consent

## v1.0.30

### Other
- Merge pull request #22 from yassirezoo44ye-stack/claude/flow-lead-automation-audit-w3ldyc
- fix(jobs): dispatch queued jobs without Redis and store them on real Redis
- Merge pull request #21 from yassirezoo44ye-stack/claude/flow-lead-automation-audit-w3ldyc
- fix(leads): admin write access and a no-organization state
- fix(leads): validated hot/warm/cold qualification through AIGateway
- test(leads): check create_lead run_id via the shared enqueue helper
- fix(leads): make lead follow-up honest end-to-end
- test(automation): expect server-side org_id in run context
- fix(automation): make webhook lead intake work end-to-end

## v1.0.31

### Other
- Merge pull request #23 from yassirezoo44ye-stack/claude/flow-lead-automation-audit-w3ldyc
- feat(careers): AI-first Career Assistant with a guided redesign

## v1.0.32

### Other
- Merge pull request #24 from yassirezoo44ye-stack/claude/flow-lead-automation-audit-w3ldyc
- fix(automation): interrupt pending runs whose in-memory job was lost

## v1.0.33

### Other
- Merge pull request #25 from yassirezoo44ye-stack/claude/flow-lead-automation-audit-w3ldyc
- fix(leads): declare AIRequest with the other request models
- feat(leads): AI lead board, follow-up drafts and pipeline brief

## v1.0.34

### Other
- Connect study library review workflow to social drafts (#27)
