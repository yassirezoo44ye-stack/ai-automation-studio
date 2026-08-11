#!/usr/bin/env sh
# Applies pending Alembic migrations, then execs the given command (uvicorn by
# default — see Dockerfile CMD). Running migrations here rather than baking a
# fixed schema into the image keeps `docker compose up` self-sufficient: a
# fresh database gets migrated automatically, and re-running the container
# against an already-migrated database is a safe no-op.
set -e

echo "[entrypoint] applying database migrations..."
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
