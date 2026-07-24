# Observability

## v1.0 Phase 5: Observability Completeness

A prior mandate built the full stack: OTel bridge, manual spans at
chokepoints, correlation-ID middleware, consolidated health endpoints (11
probes), a `MetricsRegistry` (system/AI/workflow/marketplace/billing/
sandbox), log-level + sensitive-data masking, an audit-log API, and
`AlertingService` (admin-configurable `alert_rules` against
`MetricsRegistry`/`HealthRegistry`, generic `gauge_above` /
`counter_rate_above` / `health_unhealthy` rule types).

This phase checked whether code added *after* that stack — the Phase 2
security-hardening rate limiting and the Phase 4 OAuth-callback fix — was
actually wired into it, not whether the stack itself works.

### Fixed: rate-limit rejections were completely invisible

A 429 is a 4xx, so it never incremented `http_errors_total` (5xx-only) —
grepping "rate_limit"/"rl_store" across every observability module
returned nothing. `require_rate_limit`, `require_rate_limit_async`, and
`ai_rate_limit` (`app/core/rate_limit.py`) raised their `HTTPException`
with zero log line and zero metric. Concretely: a sustained
cost-exposure attack against `ai_rate_limit` — the limiter that exists
specifically to bound AI spend — would produce 429s to the attacker and
*nothing* in any dashboard, log, or alert.

Fixed with a shared `_record_rejection(key_prefix, ip)` helper, called
from all three rejection points: logs `log.warning(...)` and increments
a new `rate_limit_rejections_total` counter (`app/core/observability/
metrics.py`). Because `AlertingService`'s rule engine is already generic
over anything in `MetricsRegistry`, closing the loop needed one line: a
new default rule, `("Elevated rate-limit rejections",
"counter_rate_above", "rate_limit_rejections_total", 20.0)` in
`app/services/alerting.py`'s `_DEFAULT_RULES` — set above the 5.0
threshold used for `http_errors_total`/`workflow_runs_failed` since a
few 429s from ordinary bursty traffic on a shared endpoint isn't abuse;
a sustained pattern is. This also resolves the gap the code's own
comment used to name explicitly ("auth failure rate ... doesn't have a
wired metric yet").

`tests/test_rate_limit.py::TestRateLimitObservability` (3 tests)
regression-tests this — verified via revert-and-fail: reverting
`rate_limit.py`+`metrics.py` makes exactly the 2 increment-on-429 tests
fail, while the "does not increment when allowed" test is unaffected.

### Fixed: OAuth callback failures logged only as generic access-log noise

`_oauth_provider_unreachable()` and the CSRF-state-mismatch raise in
`app/routers/auth_users.py` (added/touched in Phase 4) had no
`log.warning`. Confirmed `app/factory.py`'s catch-all `Exception`
handler never fires for `HTTPException` — FastAPI's built-in handler
takes precedence — so the only server-side trace of "Google OAuth is
down" was an undifferentiated `AccessLogMiddleware` line with no
provider name or failure reason. `http_errors_total` *does* still
increment generically for the 502 case (any 5xx does, via
`record_http()`), so this wasn't a zero-signal gap like rate limiting —
just a no-diagnostic-context one. Added `log.warning` with
provider/exception context to `_oauth_provider_unreachable()` and
IP context to the CSRF-mismatch path in `_verify_oauth_state()`.

### Audited, no change needed

- Correlation-ID middleware (`RequestIdMiddleware`) wraps every router
  including `auth_users`, unconditionally — confirmed no exclusion.
- `/health/deep` and friends don't probe Google/Microsoft/GitHub OAuth
  reachability — correct: those are user-initiated, browser-driven
  flows, not backend dependencies the app calls on its own, so they
  don't belong in the dependency-health probe list.
- `MetricsRegistry`'s existing categories (AI/workflow/marketplace/
  billing/sandbox/system) already have live increment call sites; only
  rate limiting was pre-registered-but-never-incremented dead weight.

### Known, deliberately unaddressed

`AlertingService.init_alert_schema()` only seeds `_DEFAULT_RULES` into
`alert_rules` when the table is empty (fresh DB) — the new rule added
here won't retroactively appear on an already-deployed instance's table.
This is pre-existing behavior for every rule ever added to that list,
not something this phase changed; an already-running deployment needs
the rule inserted manually (or via the admin API) the same way any
earlier addition would have.
