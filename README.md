# Axon — AI Automation Studio

A production-grade SaaS platform for AI automation, developer tools, and social content management.

**Stack:** React 19 · TypeScript · Vite · FastAPI · PostgreSQL · asyncpg · Redis (optional) · Stripe · Anthropic Claude · OpenAI / OpenRouter / local models (optional)

---

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Development](#development)
- [Testing](#testing)
- [Deployment](#deployment)
- [API Reference](#api-reference)

---

## Architecture

```
axon/
├── app/                    # FastAPI backend
│   ├── core/               # Config, auth, DB pool, logging, security, middleware
│   ├── execution/          # Runtime engine + pluggable drivers (Node, Python, static)
│   ├── routers/            # 40 FastAPI endpoint suites (auth, billing, marketplace,
│   │                       #   plugins, sandbox, AI routing, observability, ...)
│   └── runtime/            # Tool discovery, capability flags, preflight, diagnostics
├── migrations/             # Alembic database migrations
├── src/renderer/           # React 19 frontend (Electron-compatible)
│   ├── features/           # ai · dev · home · settings · social
│   ├── shared/             # hooks · icons · ui · utils · types
│   └── components/layout/  # AppLayout · Sidebar · CommandPalette
├── tests/                  # Backend unit + integration tests
├── Dockerfile              # Multi-stage: Node 20 build → Python 3.11 runtime
└── docker-compose.yml      # Local dev: app + PostgreSQL 16
```

### Key design decisions

| Decision | Rationale |
|---|---|
| HMAC-signed tokens (no JWT lib) | Zero runtime dependency; tokens carry email+expiry+trial in one cookie/header |
| AsyncPG (no ORM) | Maximum async throughput; full control over query plans |
| Idempotent schema init at startup | `app.factory.lifespan()` runs `init_db()`/`init_*_schema()` on every boot — see [Schema management](#schema-management) |
| Feature-boundary barrel exports | Cross-feature imports go through `features/<name>/index.ts` only |
| SSE streaming | Real-time build/run/AI output without WebSocket overhead |
| Unified runtime registry | Single source of truth for tool detection across build, package, execution |

---

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Fill in DATABASE_URL, SESSION_SECRET, ANTHROPIC_API_KEY, STRIPE_* in .env
docker compose up --build
```

Open `http://localhost:8000`.

### Manual

**Prerequisites:** Python 3.11+, Node 20+, PostgreSQL 16+

```bash
# 1. Backend
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
# Edit .env

# 2. Start backend — schema is created/updated automatically on startup,
#    no separate migration step needed (see Schema management below)
python app_main.py

# 3. Frontend (separate terminal)
npm install
npm run dev     # http://localhost:3000 (proxied to :8000 for API)
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string — `postgresql://user:pass@host:5432/db` |
| `SESSION_SECRET` | ✅ | 64+ hex chars for HMAC token signing. **Generate with:** `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ANTHROPIC_API_KEY` | ✅ | API key from console.anthropic.com |
| `STRIPE_SECRET_KEY` | ✅ (billing) | Stripe secret key (`sk_live_…` or `sk_test_…`) |
| `STRIPE_WEBHOOK_SECRET` | ✅ (billing) | Webhook endpoint secret from Stripe Dashboard |
| `STRIPE_PRICE_ID` | ✅ (billing) | Stripe Price ID for the legacy flat subscription plan |
| `STRIPE_PRICE_ID_STARTER/PRO/TEAM` | ✅ (org billing) | Stripe Price IDs for the org-scoped tiered plans |
| `APP_URL` | ✅ (prod) | Public URL of the app e.g. `https://axon.example.com` |
| `WORKSPACES_DIR` | Optional | Override workspace storage path (default: `./workspaces`) |
| `PORT` | Optional | HTTP port (default: `8000`) |

This table covers what's required to boot and take payments. `.env.example`
is the source of truth for the full list, including optional integrations
(email/SMTP, Redis, OpenRouter/local AI models, OAuth providers, database
pool tuning, sandbox/Docker, observability) — every var there has an
inline comment explaining what it does and its default.

> **Security:** Never commit `.env` to Git. Use your deployment platform's secrets manager for production values.

---

## Development

### Backend

```bash
# Lint
ruff check app/

# Type check (via pyright or mypy)
python -m py_compile app/**/*.py

# Tests
pytest tests/ -v
```

### Schema management

Alembic is present in the repo but is **not** how schema changes actually
ship — `alembic history` fails past migration `001` (later migrations use
a different, non-Alembic `up(conn)/down(conn)` shape). The real mechanism
is the idempotent `init_db()`/`ensure_*_table()`/`init_*_schema()` calls
`app.factory.lifespan()` runs on every startup: add your new
`CREATE TABLE IF NOT EXISTS`/`ALTER TABLE` statements to the relevant
`init_*_schema()` function and restart the app. See `DEPLOYMENT.md` →
"Schema/migration safety" for the full rationale.

### Frontend

```bash
npm run dev          # Vite dev server on :3000
npm run typecheck    # tsc --noEmit
npm run lint         # ESLint
npm run lint:strict  # ESLint, zero warnings — what CI enforces
npm run lint:fix     # Auto-fix
npm run test         # Vitest unit tests
npm run build        # Production build → dist/
```

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Cmd/Ctrl + K` | Open command palette |
| `Cmd/Ctrl + /` | Toggle sidebar |
| `Esc` | Close modals |

---

## Testing

### Backend

```bash
pytest tests/ -v --tb=short
```

~28 files under `tests/`, one per subsystem (helpers, auth, rate limiting,
runtime, workflow, marketplace, plugins, sandbox, AI routing,
observability, ...). Security-regression tests specifically live under
`tests/security/` (auth, authz, tenant isolation, prompt injection, rate
limiting, API/provider/webhook security, cross-layer attack chains —
one file per category) — see `2.7 Security Testing` in the codebase's
security work for how that suite is organized.

### Frontend

```bash
npm test               # Run once
npm run test:watch     # Watch mode
```

Test files under `src/renderer/__tests__/`: `theme.test.ts` (theme
persistence), `utils.test.ts` (utility functions), `navigation.test.tsx`
(routing/sidebar navigation).

---

## Deployment

### Render / Railway / Fly.io

1. Set all required environment variables in the platform dashboard.
2. Connect your repo — the platform will use `Dockerfile` for builds.
3. Set the health-check path to `/health`.
4. No pre-deploy migration command needed — schema init runs
   automatically on app startup (see [Schema management](#schema-management)).

Config files for each platform:
- **Render:** `render.yaml`
- **Railway:** `railway.toml`
- **Fly.io:** `fly.toml`

### CI/CD (GitHub Actions)

`.github/workflows/ci.yml` jobs:

1. **backend** — ruff lint, `pytest` against a real Postgres service
   container, schema-init check, dependency + secret scans
2. **frontend** — typecheck, `lint:strict` (zero warnings), vitest, Vite
   production build
3. **docker** — multi-stage image build
4. **deploy** — on push to `main` only: triggers the Render deploy
5. **smoke-test** — post-deploy `GET /health/deep` check
6. **release** — version bump, `CHANGELOG.md` entry, GitHub release

See `DEPLOYMENT.md` for the full pipeline rationale and `ROLLBACK.md` for
the manual rollback procedure (automatic rollback-on-failed-health-check
isn't implemented — documented gap, not an oversight).

---

## API Reference

**`/docs` (Swagger UI) and `/redoc`, generated from the live route table
when the server is running, are the authoritative and complete API
reference.** The routes below are a curated subset — the commonly-used
ones — not an exhaustive list; the backend has 40 router modules covering
billing, marketplace, plugins, sandbox execution, AI routing,
observability, notifications, and more that aren't enumerated here.

### Health

```
GET  /health                   — Quick liveness probe
GET  /api/health/full          — Detailed health + runtime registry
GET  /api/runtime/capabilities — Detected tool capabilities
GET  /api/runtime/registry     — Full runtime tool versions
```

### Auth / Subscription

```
POST /api/subscription/checkout  — Create Stripe checkout session
POST /api/subscription/verify    — Verify subscription token
POST /api/stripe/webhook         — Stripe webhook handler
```

### Chat / AI

```
POST /run/stream                           — Streaming Claude chat (SSE)
POST /run                                  — Synchronous Claude chat
GET  /api/conversations                    — List conversations
POST /api/conversations                    — Create conversation
GET  /api/conversations/{id}/messages      — Get messages
DELETE /api/conversations/{id}             — Delete conversation
GET  /api/search?q=                        — Full-text search
GET  /api/export/conversations/{id}        — Export as Markdown
```

### Projects

```
GET    /api/projects          — List projects
POST   /api/projects          — Create project
PUT    /api/projects/{id}     — Update project
DELETE /api/projects/{id}     — Delete project
```

### Agents

```
GET    /api/agents              — List agents
POST   /api/agents              — Create agent
PUT    /api/agents/{id}         — Update agent
DELETE /api/agents/{id}         — Delete agent
POST   /api/agents/{id}/chat/stream — Agent chat (SSE)
```

### Tasks

```
GET    /api/tasks               — List tasks
POST   /api/tasks               — Create task
PUT    /api/tasks/{id}          — Update task
DELETE /api/tasks/{id}          — Delete task
POST   /api/tasks/from-conversation/{id} — Extract tasks from conversation
```

### Build / Dev

```
POST /api/build                    — Trigger build
POST /api/build/stream             — Streaming build (SSE)
GET  /api/projects/{id}/files      — List project files
POST /api/projects/{id}/files      — Upload file
GET  /api/projects/{id}/files/{path} — Download file
POST /api/projects/{id}/sync       — Sync workspace
```

### Social

```
POST /api/social/generate/stream   — AI social caption generation (SSE)
POST /api/youtube/info             — YouTube video metadata
POST /api/youtube/transcript       — Extract transcript
POST /api/youtube/analyze/stream   — AI analysis (SSE)
```

### Stats / Analytics

```
GET /api/stats            — Aggregated usage stats
GET /api/stats/timeseries — Time-series data
GET /api/agent-runs       — Agent run history
GET /api/usage-logs       — Detailed usage logs
```

---

## Security

- **HMAC-SHA256** token authentication — no session store required
- **Rate limiting** — sliding window per `(user_email, IP)` on all AI endpoints
- **Security headers** — CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- **Input validation** — Pydantic v2 on all request bodies; max lengths enforced
- **Path traversal protection** — workspace filesystem access checks canonical paths
- **SQL injection** — all queries use asyncpg parameterized statements
- **No `shell=True`** — all subprocesses use `asyncio.create_subprocess_exec`

---

## Related documentation

- [`PERFORMANCE.md`](PERFORMANCE.md) — latency/throughput budgets, DB pool
  and cache tuning, load testing, known scaling constraints
- [`RELIABILITY.md`](RELIABILITY.md) — outbound-call error handling audit,
  what's covered by existing crash/retry tests
- [`OBSERVABILITY.md`](OBSERVABILITY.md) — what's traced/logged/metriced/
  alertable and where the gaps were before they were closed
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — CI/CD pipeline, schema-management
  reality (see [Schema management](#schema-management) above), environments
- [`ROLLBACK.md`](ROLLBACK.md) — manual rollback procedure
- [`CHANGELOG.md`](CHANGELOG.md) — auto-generated per release by the
  `release` CI job; empty until the first tagged release

## Contributing

1. Fork the repo and create a feature branch.
2. Follow the code style — run `npm run lint:strict` and `ruff check app/` before pushing (CI enforces both).
3. Add tests for new backend behavior.
4. Submit a PR — CI runs automatically.

---

## License

MIT
