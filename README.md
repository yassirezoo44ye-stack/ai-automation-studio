# Axon — AI Automation Studio

A production-grade SaaS platform for AI automation, developer tools, and social content management.

**Stack:** React 19 · TypeScript · Vite · FastAPI · PostgreSQL · asyncpg · Stripe · Anthropic Claude

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
│   ├── routers/            # 15 FastAPI endpoint suites
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
| Alembic migrations | Version-controlled schema; safe zero-downtime deploys |
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

# 2. Run database migrations
alembic upgrade head

# 3. Start backend
python app_main.py

# 4. Frontend (separate terminal)
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
| `STRIPE_PRICE_ID` | ✅ (billing) | Stripe Price ID for the subscription plan |
| `APP_URL` | ✅ (prod) | Public URL of the app e.g. `https://axon.example.com` |
| `WORKSPACES_DIR` | Optional | Override workspace storage path (default: `./workspaces`) |
| `PORT` | Optional | HTTP port (default: `8000`) |

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

# New migration
alembic revision -m "add_feature_table"
alembic upgrade head
alembic downgrade -1   # rollback one step
```

### Frontend

```bash
npm run dev          # Vite dev server on :3000
npm run typecheck    # tsc --noEmit
npm run lint         # ESLint (zero warnings)
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

Test files:
- `tests/test_helpers.py` — token auth, rate limiting, project ID resolution
- `tests/test_auth.py` — auth module unit tests
- `tests/test_security.py` — rate limiter unit tests
- `tests/test_runtime.py` — runtime module smoke tests

### Frontend

```bash
npm test               # Run once
npm run test:watch     # Watch mode
```

Test files:
- `src/renderer/__tests__/theme.test.ts` — theme persistence
- `src/renderer/__tests__/utils.test.ts` — utility functions

---

## Deployment

### Render / Railway / Fly.io

1. Set all required environment variables in the platform dashboard.
2. Connect your repo — the platform will use `Dockerfile` for builds.
3. Set the health-check path to `/health`.
4. Run migrations on first deploy: add a pre-deploy command `alembic upgrade head`.

Config files for each platform:
- **Render:** `render.yaml`
- **Railway:** `railway.toml`
- **Fly.io:** `fly.toml`

### CI/CD (GitHub Actions)

`.github/workflows/ci.yml` runs on every push/PR:

1. **Backend** — Python syntax check + pytest unit tests
2. **Frontend** — TypeScript check + ESLint + Vite production build
3. **Docker** — Multi-stage image build (no push on PR; push on main when configured)

---

## API Reference

Full interactive docs available at `/docs` (Swagger UI) and `/redoc` when the server is running.

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

## Contributing

1. Fork the repo and create a feature branch.
2. Follow the code style — run `npm run lint` and `ruff check app/` before pushing.
3. Add tests for new backend behavior.
4. Submit a PR — CI runs automatically.

---

## License

MIT
