# SocialPilot AI

Turn a plain-language instruction — *"post about AI every hour for 3 days on X
and LinkedIn"* — into a running, unattended content operation: strategy →
generation → quality gate → scheduling → publishing → analytics →
optimization.

**This is a standalone product.** It lives under `socialpilot-ai/` in this
repository purely for hosting convenience — it shares no code, no runtime, and
no architecture with the `Flow` project at the repo root. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the independence rule, the
full system architecture, and the phase-by-phase build plan.

**Status:** Phase 1 (Architecture + Database + Authentication) complete. Content
strategy/generation, the scheduler/queue, social OAuth, and publishing land in
the phases that follow — see the architecture doc for the roadmap. Nothing in
this codebase fakes those capabilities in the meantime: the dashboard says so
explicitly rather than pretending.

## Stack

React 19 + TypeScript + Vite · FastAPI (Python 3.11) · PostgreSQL 16 via
SQLAlchemy 2 (async) + Alembic · Redis + Celery (from Phase 3) · JWT access
tokens + rotated httpOnly-cookie refresh tokens. Rationale for each choice is
in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#3-chosen-stack-per-section-25-of-the-spec).

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env: at minimum set JWT_SECRET_KEY and POSTGRES_PASSWORD.
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000 (docs at `/docs` outside production)
- Postgres migrations run automatically on backend container start
  (`backend/docker-entrypoint.sh`).

## Quick start (local, no Docker)

Requires PostgreSQL 16 and Redis running locally.

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
createdb socialpilot        # and socialpilot_test for the test suite
cp ../.env.example .env     # edit DATABASE_URL etc. for your local Postgres
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Testing

```bash
# Backend: unit + integration (real Postgres, no mocked DB) — 59 tests
cd backend
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/socialpilot_test \
  pytest -q

# Frontend: type-check + build
cd frontend
npm run build

# Frontend: end-to-end (drives a real browser against the real dev servers —
# start `npm run dev` and the backend first, in separate terminals)
cd frontend
npm run test:e2e
```

The backend suite covers password/JWT/CSRF unit tests, the full auth API
(register/login/refresh/logout/change-password), tenant isolation, RBAC,
migration up/down round-trips, rate limiting, and a real concurrency test that
proves refresh-token rotation has exactly one winner under a race (see
`backend/tests/integration/test_race_conditions.py`).

## Project layout

```
socialpilot-ai/
├── backend/        FastAPI app — see backend structure in docs/ARCHITECTURE.md
├── frontend/        React + TS + Vite SPA
├── docker-compose.yml
├── .env.example
└── docs/ARCHITECTURE.md
```

## Security notes (Phase 1 scope)

- Passwords hashed with Argon2id.
- Access tokens: short-lived JWT, Bearer header only, kept in memory on the
  client (never in localStorage).
- Refresh tokens: opaque, hashed at rest, httpOnly + Secure + SameSite=Strict
  cookie, rotated on every use; reuse of an already-rotated token revokes the
  whole session chain.
- CSRF: double-submit cookie required on cookie-authenticated endpoints
  (`/auth/refresh`, `/auth/logout`).
- Tenant isolation: every org-scoped endpoint resolves membership through
  `app/api/deps.py::require_org_member`; a non-member gets the same 404 as a
  nonexistent org (no existence-enumeration leak).
- Rate limiting on auth endpoints (`slowapi`, Redis-backed in production).
- Security headers on every response (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS in prod).
- Audit log (`audit_logs` table) records auth events, including failed logins
  and refresh-token reuse detection.
