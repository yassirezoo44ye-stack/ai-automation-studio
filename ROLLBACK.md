# Rollback

There is no automated rollback. The `smoke-test` CI job checks
`/health/deep` after a deploy and fails loudly if it's unhealthy, but it
cannot revert Render to the previous deploy by itself — that needs
Render's full REST API plus an API key that isn't configured (see the
"Not implemented" section of `DEPLOYMENT.md`).

## Manual rollback via Render's dashboard

1. Render dashboard → your service → **Events** (or **Deploys**) tab.
2. Find the last known-good deploy.
3. Click **Rollback to this deploy** (Render's own built-in feature — this
   redeploys that exact prior build, it doesn't require re-running CI).
4. Confirm the app is healthy again: `curl https://<your-service>.onrender.com/health/deep`.

## If the bad deploy also included a schema change

The schema mechanism (`app.factory.lifespan()`'s `init_db()` /
`ensure_*_table()` / `init_*_schema()` calls) only ever *adds* tables/
columns idempotently — nothing in the startup path drops or destructively
alters existing data. Rolling back the application code via Render's
dashboard (above) is safe on its own; there is no separate
"down-migration" step to run. If a bad deploy wrote bad *data* (not
schema), that needs a manual, situation-specific fix — restore from
Render's managed Postgres backups if necessary (Render dashboard → your
database → **Backups**).

## To add automatic rollback later

Would need:
1. A `RENDER_API_KEY` (Render dashboard → Account Settings → API Keys)
   and the service's `RENDER_SERVICE_ID`, both as new GitHub secrets.
2. The `smoke-test` job in `ci.yml`, on failure, calling Render's
   `POST /v1/services/{serviceId}/rollback` API instead of just reporting.

Not built in this phase — flagged as a follow-up recommendation.
