# Deployment

## Pipeline overview

`.github/workflows/ci.yml` runs on every push and pull request to `main`:

```
backend ─┐
         ├─→ docker ─→ deploy (main push only) ─→ smoke-test ─→ release
frontend ┘
```

- **backend** — syntax check, ruff lint (ratcheted, see below), a secret
  scan, a schema-safety check, `pytest`, and an informational `pip-audit`
  run. Uses a `postgres:16` service container.
- **frontend** — `npm audit`, TypeScript typecheck, ESLint (zero errors),
  `vitest`, production build.
- **docker** — builds the production `Dockerfile` as a smoke test (no
  push to any registry — Render builds from source itself).
- **deploy** — only on a push to `main`, only after backend/frontend/docker
  all pass. Triggers a Render Deploy Hook with `ref=<sha>` pinning the
  deploy to the exact commit this run validated (not the branch tip, which
  may have moved to an unvalidated later push while tests ran).
- **smoke-test** — polls `/health` (every 15s, up to 15 min) until its
  `commit` field equals the deployed SHA — Render's zero-downtime swap
  keeps the OLD build serving 200 during the whole new build, so checking
  health alone would false-PASS; the commit match is what proves the new
  build is actually live. Then requires `/health/deep` to return 200.
- **release** — bumps a patch version, updates `CHANGELOG.md`, tags, and
  creates a GitHub Release.

## Two things that were broken before this phase, and what fixed them

1. **`ci.yml` had failed 100% of its 39 runs since it was created, every
   one in under 1 second** — no job ever actually dispatched. The `docker`
   job was the only one referencing non-GitHub-authored actions
   (`docker/setup-buildx-action`, `docker/build-push-action`); the
   `docker` job now uses a plain `docker build` shell step instead (the
   Docker CLI is preinstalled on `ubuntu-latest`), which needs no
   third-party action at all. If a future run still fails to dispatch,
   check **Settings → Actions → General → Actions permissions** — it may
   be restricted to GitHub-authored actions only.
2. **Render was auto-deploying every push with zero gate.** `render.yaml`
   now has `autoDeploy: false`; deploys only happen via the `deploy` job
   above.

## One-time manual setup (I can't do these — no Render/GitHub account access)

1. **Render Deploy Hook**: Render dashboard → your service → Settings →
   Deploy Hook → copy the URL.
2. **GitHub secret**: this repo → Settings → Secrets and variables →
   Actions → New repository secret → name it `RENDER_DEPLOY_HOOK_URL`,
   paste the URL from step 1.
3. **Workflow write permissions** (needed for the `release` job to push a
   tag/commit): this repo → Settings → Actions → General → Workflow
   permissions → select "Read and write permissions". If this is left as
   read-only, the `release` job's push step will fail with a 403 — deploys
   and everything before `release` will still work fine either way.
4. **Optional**: if production isn't at the default
   `https://ai-automation-studio.onrender.com` (e.g. a custom domain), set
   a repo variable `PRODUCTION_URL` (Settings → Secrets and variables →
   Actions → Variables) so the smoke-test job checks the right host.

## Ruff lint ratchet

`ci.yml`'s ruff step is not zero-tolerance. This workflow never actually
ran before this phase (see above), so its ruff gate never really applied
either — when checked directly, there were 307 pre-existing errors; 191
were safe-auto-fixed (`ruff check --fix`, dead imports only) and 2 were
confirmed real bugs (see below), fixed directly. The 104 that remain are
style-only (unused-variable / ambiguous-name / import-order /
multiple-statements-per-line rules, plus 2 known-safe `F821` false
positives from deferred imports inside string type hints) and are spread
across dozens of files — fixing all of them in this phase would be exactly
the "refactor unrelated application code" it's scoped not to do. The CI
step instead **ratchets**: it fails only if the error count exceeds 104,
so no new lint debt can be introduced silently, without blocking on debt
that predates this check ever actually running. A dedicated lint-debt
paydown pass is a reasonable follow-up.

## Two real bugs this phase's tooling found (and fixed)

Both were found because turning on `ruff` for real (see above) surfaced
`F821` undefined-name errors that weren't stylistic:

- `app/execution/drivers/python_server.py` called an `_ev(...)` SSE-event
  helper that was never defined in that file (every sibling driver defines
  its own copy) — any FastAPI/Flask/generic Python project run through the
  Build page hit `NameError` on the first status event.
- `app/routers/package.py`'s Windows-installer generator had 4 lines using
  single braces instead of double braces in an f-string template, causing
  Python to evaluate `{shortcut_path}`/`{target}`/`{work_dir}`/`{APP_NAME}`
  immediately in `package.py`'s own scope (where they don't exist) instead
  of deferring to the generated installer's own runtime — `NameError` the
  instant anyone built a Windows installer via the Package page.

## Schema/migration safety

Alembic is **not** how this app's schema actually gets applied in
production. `alembic history` fails outright past migration `001` —
migrations `002`+ use a different, non-Alembic `up(conn)/down(conn)` shape
with no `revision`/`down_revision` metadata, so `alembic upgrade head`
cannot run. The real mechanism is the idempotent
`init_db()`/`ensure_*_table()`/`init_*_schema()` calls that
`app.factory.lifespan()` runs on every app startup. `scripts/ci_schema_check.py`
exercises that exact mechanism — it runs the app's real `lifespan()`
context manager against the CI Postgres service container — rather than
`alembic upgrade head`, which would fail on every run regardless of any
real regression. Fixing the Alembic revision chain itself is a separate,
larger, riskier follow-up, not done in this phase.

## Environments

Local (docker-compose) and Production (Render) only — no staging/preview
environment tier exists. Render Preview Environments were considered and
explicitly deferred (adds paid infrastructure) rather than silently built.

## Not implemented (documented gaps, not oversights)

- **Automatic rollback** on a failed post-deploy health check — needs
  Render's full REST API plus an API key that isn't set up. See
  `ROLLBACK.md` for the manual procedure.
- **Preview/staging environments** — deferred by choice.
- **Fixing the Alembic revision chain** beyond migration 001.
- **The remaining 104 ruff findings / any residual ESLint findings beyond
  today's clean state** — ratcheted, not fixed, per above.
