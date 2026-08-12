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

**Status:** Phase 1 (Architecture + Database + Authentication) and Phase 2
(Content Strategy + AI Generation) complete. The scheduler/queue, social
OAuth, and publishing land in the phases that follow — see the architecture
doc for the roadmap. Nothing in this codebase fakes those capabilities in the
meantime: the dashboard says so explicitly rather than pretending, and no
social-platform posting or scheduling exists yet.

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

## Content Strategy + AI Generation (Phase 2)

An authenticated org member (owner/admin/editor — viewers are read-only) can:

1. **Define a content strategy** — business description, target audience,
   goals, tone, language, brand voice — at `/content/strategy`. A strategy is
   scoped to one organization and can have any number of **content pillars**
   (recurring themes, e.g. "AI Tools", "Case Studies").
2. **Generate content** at `/content/generate` — pick a saved strategy,
   optionally a pillar/platform/tone/language override, then either:
   - **Generate Ideas** — a batch of post concepts (title, hook, concept,
     pillar, suggested platform, CTA), or
   - **Generate Post** — one complete post (hook, body, CTA, hashtags,
     platform, a suggested media concept — no image/video is generated).
   Every generation call — success or failure — is persisted as a
   `ContentGeneration` audit record; a failed AI call is never silently
   retried as a fake success, it comes back as `status: "failed"` with the
   real error.
3. **Save, regenerate, and browse** — save a generated idea/post to the
   library, regenerate a post from the same inputs, and browse/edit/delete
   saved content at `/content/library` (filter by platform, edit body/status,
   delete).

**Not in Phase 2 — do not expect these yet:** publishing to any social
platform, OAuth connections, scheduling, queues/workers, analytics, or
autonomous agents. Generated content is saved to the library only; nothing
leaves this system.

### AI provider configuration

Generation goes through a small `AIProvider` abstraction
(`backend/app/services/ai/`) so the backend never talks to a specific vendor
API directly, and API keys never reach the frontend or get stored in the
database:

| Env var | Purpose |
|---|---|
| `AI_PROVIDER` | `anthropic` (default) or `mock` (deterministic, no network — dev/CI/E2E only, refused in production) |
| `AI_API_KEY` | Provider API key. Unset → generation endpoints return `503` with a clear "not configured" message; never a fake response. |
| `AI_MODEL` | Model identifier (default `claude-sonnet-4-5`) |
| `AI_GENERATION_RATE_LIMIT` | Per-IP rate limit on the two `/generate/*` endpoints (default `20/minute`) |

For local development without a paid key, run the backend with
`AI_PROVIDER=mock` — content generation still works end-to-end against
obviously-canned, deterministic output.

## Testing

```bash
# Backend: unit + integration (real Postgres, no mocked DB) — 113+ tests
cd backend
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/socialpilot_test \
  pytest -q

# Frontend: type-check + build
cd frontend
npm run build

# Frontend: unit tests (vitest + jsdom)
cd frontend
npm run test

# Frontend: end-to-end (drives a real browser against the real dev servers —
# start the backend and `npm run dev` first, in separate terminals)
cd frontend
npm run test:e2e            # Phase 1 — auth flow

# Content E2E requires no real AI key: start the backend with AI_PROVIDER=mock
AI_PROVIDER=mock uvicorn app.main:app --port 8000   # backend
npm run dev                                          # frontend, separate terminal
npm run test:e2e:content    # Phase 2 — strategy -> generate -> save -> library -> reload
```

The backend suite covers password/JWT/CSRF unit tests, the full auth API
(register/login/refresh/logout/change-password), tenant isolation, RBAC,
migration up/down round-trips, rate limiting, a real concurrency test that
proves refresh-token rotation has exactly one winner under a race (see
`backend/tests/integration/test_race_conditions.py`), and — for Phase 2 —
strategy/pillar/generation/item CRUD, cross-tenant isolation, RBAC on
mutations, and AI-provider behavior (mock provider, missing-key config error,
unsupported provider, production guard against `AI_PROVIDER=mock`) using
dependency-injected fake/mock providers, never a real API call.

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

## Security notes (Phase 2 additions)

- Every content route requires org membership via the same
  `require_org_member`/`require_role` dependencies as Phase 1 — strategies,
  pillars, generations, and items are always looked up filtered by
  `organization_id`, and a cross-tenant request gets a 404, not a 403 (no
  existence-enumeration). See `tests/integration/test_content_strategy.py`
  and `test_content_item.py`'s `TestContentTenantIsolation` classes.
- Mutating a strategy/pillar/item requires owner/admin/editor; viewers are
  read-only (`CONTENT_ROLES`).
- The AI provider abstraction reads `AI_API_KEY` from the server environment
  only — it is never accepted from the client, never stored in the database,
  and never included in any API response or log line.
- AI generation is rate-limited per IP (`AI_GENERATION_RATE_LIMIT`) separately
  from auth endpoints.
- Generated content is treated as **untrusted user-adjacent data**, not
  trusted markup: the frontend renders it as plain text (React's default JSX
  escaping) and never via `dangerouslySetInnerHTML`. The backend does not
  attempt to sanitize/strip HTML server-side either — it stores exactly what
  was generated/edited and relies on the frontend never rendering it as
  markup.
- The strategy context passed to the AI model is wrapped with an explicit
  system-prompt boundary telling the model that organization-supplied text is
  business data, not instructions to the model itself — a basic prompt
  injection mitigation, not a guarantee (see
  `ContentGenerationService._SYSTEM_PREAMBLE`).
- Every generation call (success or failure) and every strategy/item
  create/delete is written to the existing `audit_logs` table.
