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
