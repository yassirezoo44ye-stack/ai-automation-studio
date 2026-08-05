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
