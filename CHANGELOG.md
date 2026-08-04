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
