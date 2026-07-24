# Performance, Scalability & Reliability

## Budgets

| Target | Budget | Enforced by |
|---|---|---|
| API P95 latency (non-AI) | < 250ms | `scripts/load_test.py` (run against a live server) |
| Workflow/job scheduling | < 50ms | `tests/test_performance.py` (CI) |
| AI routing overhead (breaker decision) | < 20ms | `tests/test_performance.py` — measured <10µs per decision |
| DB queries | < 100ms P95 | `DB_COMMAND_TIMEOUT_S` bounds the worst case; hot tables verified indexed |
| Memory growth | stable | `system_metrics` service gauges + Observability page |

## What this phase changed

- **DB pool** (`app/factory.py`): sizes env-tunable (`DB_POOL_MIN`/
  `DB_POOL_MAX`, defaults 2/10), every query bounded by
  `DB_COMMAND_TIMEOUT_S` (60s default), org-scoped acquisition fails fast
  after `DB_ACQUIRE_TIMEOUT_S` (10s) instead of queueing forever. Note:
  `DB_POOL_MAX × instance_count` must stay under the Postgres plan's
  connection ceiling. asyncpg caches prepared statements per connection
  automatically — no extra layer was added. All 19 hot tables were
  audit-verified to have indexes matching their real WHERE clauses
  (`usage_limits`'s five-column PK covers its one lookup exactly).
- **Cache** (`app/core/cache/invalidation.py`, new): `cached()`
  get-or-compute on the existing Redis-or-local adapter, applied to the
  two verified uncached hot reads — org settings (5 min TTL) and
  marketplace listings (60s TTL, dropped by every catalog mutation).
  `invalidate()/invalidate_prefix()` also broadcast on a pub/sub channel;
  `on_invalidate()` listeners keep purely in-process caches (the plan
  catalog) coherent across instances. `role_permissions` needs no listener
  — it is seeded at startup and never mutated at runtime.
- **Job queue** (`app/core/jobs/queue.py`): priorities (high/normal/low),
  retries with exponential backoff (`max_retries`), dead-letter list +
  `requeue()`, delayed jobs (`run_at`), and a handler registry whose
  scheduler dispatches under a `JOB_WORKERS` (default 10) worker-pool
  semaphore. All additive — existing `submit()/run()` callers unchanged.
- **Reliability** (`app/core/reliability.py`, new): the circuit breaker's
  state machine moved here from `app/ai/circuit_breaker.py` (which
  re-exports it — zero AI call-site changes) plus `Bulkhead`: hot
  endpoints (`chat /run(/stream)` → `ai` limit 32, `build
  /api/build(/stream)` → `build` limit 8) shed load with 503 +
  Retry-After when saturated instead of queueing unbounded work.
  Streaming handlers hold their slot for the whole stream. Limits:
  `BULKHEAD_<NAME>_LIMIT` env vars.
- **Event-loop hygiene**: `build_agent.py`'s 300s-blocking
  `subprocess.run` → `asyncio.create_subprocess_exec` (it was freezing
  every request on the server for the duration of a build); WS broadcast
  fan-out is now parallel (`asyncio.gather`) so one slow client can't
  head-of-line-block the rest.

## v1.0 Phase 3 Performance Review (post-Security-Hardening)

Audited every module touched by the 11-commit Security Hardening phase for
regressions, plus re-ran the budgets above.

- **Fixed:** `app/core/rate_limit.py`'s `rl_store` (the in-process rate-
  limit fallback) had no eviction — `check_rate_limit()` only ever trimmed
  a key's own timestamp list, never removed the key itself once empty.
  One dict entry accumulates per distinct IP (factory.py's global
  middleware alone) or per user+IP (`ai_rate_limit`), forever, for the
  life of the process — unbounded growth on a long-running server. This
  predates this phase, but the Rate Limiting fix in Security Hardening
  made it materially worse: it consolidated `app/core/security.py` (which
  used to run its own periodic GC sweep) into a re-export shim over this
  module, so five more routers' worth of traffic lost that mitigation.
  Fixed by porting the same periodic-sweep pattern into the now-canonical
  module (`_maybe_gc`, 5-minute cadence, evicts keys whose entire window
  has aged out) — `tests/test_rate_limit.py::TestRlStoreGarbageCollection`
  regression-tested (reverting the fix makes the eviction test fail).
- **Audited, no change needed:** the ownership check added to 10
  `/api/projects/{id}/*` routes in the same phase (`_require_project_owner`)
  adds two sequential indexed point-lookups per request
  (`users.email` is `UNIQUE NOT NULL`, auto-indexed by Postgres;
  `projects.id` is the PK) — single-digit milliseconds, well inside the
  documented DB budget. Not combined into one JOIN query: the two-query
  shape already matches this codebase's established `owner_user_id()` +
  `resolve_project_id()` convention used everywhere else, and merging
  it would be a speculative micro-optimization outside what this review
  found any evidence of needing.
- Re-ran `tests/test_performance.py` (circuit breaker, bulkhead, job
  queue, cache-hit-path budgets) — all still pass unchanged.

## Load testing

- `tests/test_performance.py` — deterministic overhead tests, run in CI.
- `scripts/load_test.py` — closed-loop concurrent load against a live
  server with budget pass/fail. Run locally or against staging:
  `python scripts/load_test.py --users 50 --requests 20`.
- **Honesty note**: "100,000 concurrent users" cannot be validated on a
  single dev machine, and a saturated CI runner cannot hold wall-clock
  SLOs — CI runs the overhead tests; the load script is for real
  environments. Scaling past one instance is designed for (below) but the
  claim stops at what was measured.

## Known single-instance constraints (documented, not yet built)

Render currently runs one instance. Before scaling horizontally:

1. **WebSocket fan-out** (`app/routers/ws.py`): connections live in one
   process. Design: publish broadcast frames on a Redis pub/sub channel
   (the adapter's `publish/subscribe` added this phase already supports
   it); every instance relays to its local connections.
2. **Process manager ports** (`app/execution/process_mgr.py`):
   `_used_ports` is per-instance. Fine while project preview processes
   run on the instance that owns them; a shared allocator (Redis SETNX)
   is needed only if previews move to shared hosts.
3. **Circuit breaker state** (`app/core/reliability.py`): per-instance.
   Acceptable — each instance discovers a failing provider within
   `failure_threshold` calls; sharing state via Redis is an optimization,
   not a correctness need.
4. **Rate limiting**: already Redis-backed when `REDIS_URL` is set.

## Read replicas / partitioning

No second database exists today. The code is compatible when needed:
`DATABASE_URL` is the single injection point; a read-replica URL would be
introduced as a second pool for the read-heavy paths (marketplace listing,
analytics queries). Partitioning candidates (by `created_at`):
`ai_usage_log`, `usage_events`, `activity_logs`, `alert_history` — all
already indexed on `(org, created_at)` patterns that survive partitioning.
Not implemented — no breaking schema changes in this phase.
