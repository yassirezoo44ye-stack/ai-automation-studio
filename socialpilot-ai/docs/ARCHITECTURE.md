# SocialPilot AI — Architecture

> **Independence notice:** SocialPilot AI is a standalone product that lives in the
> `socialpilot-ai/` directory of this repository purely as a matter of convenience for
> hosting. It does **not** import, depend on, extend, or share a runtime with the
> `Flow` codebase that occupies the repository root (`app/`, `src/`, `agentos.py`,
> etc.). No module under `socialpilot-ai/` may `import` anything from outside
> `socialpilot-ai/`. Treat this directory as its own repository root: its own
> dependency lockfiles, its own Docker image, its own CI job, its own database.

## 1. Product

SocialPilot AI turns a natural-language instruction ("post about AI every hour for
3 days on X and LinkedIn") into a running, unattended content operation: strategy →
generation → quality gate → scheduling → publishing → analytics → optimization.

## 2. High-level architecture

```
                                   ┌─────────────────────┐
                                   │   Frontend (SPA)    │
                                   │ React + TS + Vite    │
                                   └──────────┬───────────┘
                                              │ HTTPS / JSON (Bearer JWT)
                                   ┌──────────▼───────────┐
                                   │      API Layer        │
                                   │ FastAPI (backend/app) │
                                   │ - authn/authz          │
                                   │ - request validation   │
                                   │ - tenant scoping        │
                                   └──────────┬───────────┘
                                              │
                     ┌────────────────────────┼─────────────────────────┐
                     │                         │                         │
           ┌─────────▼─────────┐   ┌───────────▼───────────┐  ┌─────────▼─────────┐
           │ Application        │   │ AI Service (provider   │  │ Scheduler          │
           │ Services            │   │ abstraction)            │  │ (DB-backed cron/   │
           │ - strategy          │   │ - text/image/video      │  │  interval jobs)    │
           │ - content           │   │   generation             │  └─────────┬─────────┘
           │ - automation        │   │ - quality gate            │            │
           │ - calendar          │   └────────────────────────┘            ▼
           │ - analytics         │                              ┌─────────────────────┐
           └─────────┬─────────┘                                │ Queue (Redis)        │
                     │                                          │ + Celery workers      │
                     │                                          └─────────┬─────────────┘
                     │                                                    │
                     │                                          ┌─────────▼─────────────┐
                     │                                          │ Publishing Worker      │
                     │                                          │ - idempotency          │
                     │                                          │ - retry/backoff        │
                     │                                          └─────────┬─────────────┘
                     │                                                    │
                     │                                          ┌─────────▼─────────────┐
                     │                                          │ Social Providers        │
                     │                                          │ (Facebook/IG/X/LinkedIn/│
                     │                                          │  TikTok/YouTube)         │
                     │                                          │ each behind a common     │
                     │                                          │ SocialProvider interface │
                     │                                          └─────────────────────────┘
                     │
           ┌─────────▼─────────┐
           │ PostgreSQL 16       │
           │ (asyncpg + SQLAlchemy 2 async ORM, Alembic migrations)
           └─────────────────────┘
```

The frontend never talks to the database, the queue, or social platforms directly —
only to the API layer. Business logic lives in `app/services/*`, not in routers and
not in the frontend.

## 3. Chosen stack (per section 25 of the spec)

| Layer | Choice | Why |
|---|---|---|
| Frontend | React 19 + TypeScript + Vite | fast dev loop, typed, matches spec |
| Backend | Python 3.11 + FastAPI | async-first, OpenAPI out of the box, spec default |
| ORM | SQLAlchemy 2.0 (async) + Alembic | 15+ related tables across 10 phases — a typed ORM + migration tool pays for itself immediately; raw SQL would not scale across this many joins/tenancy filters safely |
| DB driver | asyncpg | fastest async Postgres driver for Python |
| Database | PostgreSQL 16 | spec default |
| Queue/Scheduler | Redis + Celery (celery beat for periodic dispatch, celery worker for publishing) | production-grade, horizontally scalable, survives process restarts, has native retry/backoff |
| Auth | Short-lived JWT access token (Bearer, in-memory on client) + opaque refresh token (httpOnly, Secure, SameSite=Strict cookie, hashed at rest, rotated on use) | avoids storing long-lived secrets in JS-reachable storage; refresh flow is CSRF-hardened with SameSite=Strict + double-submit token |
| Password hashing | Argon2id (`passlib[argon2]`) | modern default, resistant to GPU cracking |
| AI provider | Provider abstraction (`app/providers/ai/*`) supporting Anthropic/OpenAI-compatible backends via `AI_PROVIDER`/`AI_API_KEY` env vars | no invented APIs; real key required to actually generate content |
| Social providers | Provider abstraction (`app/providers/social/*`), one class per platform implementing a common `SocialProvider` interface, real OAuth 2.0 + official REST APIs only | matches "no scraping, no fake publishing" requirement |
| Storage | S3-compatible (`app/services/storage.py`, boto3), pluggable | media library, phase 5 |
| Tests | pytest + pytest-asyncio + httpx.AsyncClient against a real Postgres test database | integration tests exercise real SQL, not mocks, for schema/tenancy correctness |

## 4. Tenancy & RBAC model

- `organizations` is the tenant boundary. Every domain-owned row (content, automations,
  social accounts, media, analytics, audit logs) carries `organization_id`.
- `organization_members` joins `users` ↔ `organizations` with a `role` enum:
  `owner`, `admin`, `editor`, `viewer`.
- Every authenticated request that touches tenant data resolves
  `(current_user, organization_id)` → `OrganizationMember` via
  `app/api/deps.py::require_org_member`, and every repository query filters by
  `organization_id` explicitly — there is no "trust the frontend" path. This is what
  the tenant-isolation tests in `tests/integration/test_tenant_isolation.py` assert.
- `require_role(*roles)` is a FastAPI dependency used to gate mutating endpoints
  (e.g. only `owner`/`admin` can invite members or delete the org).

## 5. Delivery phases (this repo will grow in this order)

1. **Architecture + Database + Authentication** ← this PR
2. Content Strategy + AI Generation
3. Automation + Scheduler + Queue
4. Social OAuth + Publishing Engine
5. Media + Video Pipeline
6. Calendar + Dashboard
7. Analytics + Optimization
8. Security Hardening
9. Testing (continuous, but a dedicated hardening pass)
10. Production Deployment

Each phase ends with: migrations applied cleanly from zero, `pytest` green, a diff
review, and a commit scoped to that phase.

## 6. Directory layout

```
socialpilot-ai/
├── backend/
│   ├── app/
│   │   ├── core/            # settings, db session, security, logging, rate limiting
│   │   ├── models/          # SQLAlchemy ORM models (one file per aggregate)
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── repositories/    # data-access layer (tenant-scoped queries)
│   │   ├── services/        # business logic (auth, org, audit, ...)
│   │   ├── providers/       # ai/* and social/* pluggable provider interfaces
│   │   ├── workers/         # Celery app + tasks (phase 3+)
│   │   ├── api/v1/          # FastAPI routers, thin — validation + service calls only
│   │   └── main.py          # app factory, middleware, exception handlers
│   ├── alembic/              # migrations
│   ├── tests/{unit,integration}
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/                 # React + TS + Vite SPA
├── docker-compose.yml        # postgres + redis + backend + frontend, local/prod-shaped
├── .env.example
└── docs/ARCHITECTURE.md      # this file
```
