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
