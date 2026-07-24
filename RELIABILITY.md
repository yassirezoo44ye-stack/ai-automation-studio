# Reliability

## v1.0 Phase 4: Reliability Testing

Audited error-handling robustness around outbound network calls and
existing failure-recovery test coverage.

### Fixed: OAuth callbacks leaked raw 500s on a provider network failure

`app/routers/auth_users.py`'s three OAuth callback handlers
(`google_oauth_callback`, `microsoft_oauth_callback`,
`github_oauth_callback`) each make 2-3 sequential `httpx.AsyncClient()`
calls to the provider (token exchange, userinfo) but only ever branched
on HTTP status codes — a connection error or timeout reaching Google/
Microsoft/GitHub (network blip, provider outage) had no `try/except` and
propagated as an unhandled exception, surfacing to the browser as a raw
500 instead of a clean OAuth-failure redirect/response. Confirmed via
direct `python -c` inspection that httpx 0.28.1's default timeout is
already 5.0s (not unbounded) — the bug was poor error *surfacing*, not a
hang risk.

Fixed by wrapping each handler's `async with _httpx.AsyncClient() as
client:` block in `try/except httpx.RequestError`, raising a shared
`_oauth_provider_unreachable(provider)` → `HTTPException(502, ...)`
helper — the same shape `build.py`'s live-preview proxy already uses for
its own `httpx.ConnectError`/`httpx.TimeoutException` handling, so this
now matches an established codebase convention rather than inventing a
new one.

`tests/test_api_auth.py::TestOAuthCallbackProviderUnreachable` (4 tests)
regression-tests this: a fake `httpx.AsyncClient` that raises
`ConnectError` on every call proves each of the 3 providers now returns
a clean 502 instead of a 500, plus one test confirming the pre-existing
CSRF-state-mismatch 400 still fires first and isn't swallowed by the new
handling. Verified via revert-and-fail: reverting the fix makes exactly
the 3 provider tests fail with `500 != 502`; the CSRF test is unaffected
either way.

### Audited, no change needed

Every other `httpx.AsyncClient(`/`httpx.Client(` call site app-wide was
checked for the same gap (network-level failure only handled via
HTTP-status branching, no `try/except`):

- `app/routers/build.py` (live-preview proxy) — already has
  `except httpx.ConnectError` / `except httpx.TimeoutException` with
  clean `HTTPException` responses.
- `app/services/alerting.py` (webhook delivery) — already wrapped in a
  broad `except Exception` by design; delivery is documented best-effort
  and must never affect the alerting tick loop.
- `app/marketplace/security.py` (OSV.dev dependency scan) — already
  wrapped; a scan failure degrades to `passed=True` with an explicit
  "skipped, provider unreachable" finding rather than blocking install.
- `app/integrations/oauth.py` (Integration SDK's OAuth helper,
  `exchange_code_for_token`/`refresh_access_token`) — has the same
  missing-`try/except` shape as the original auth_users.py bug, but has
  **zero callers anywhere in the codebase** (SDK infrastructure laid
  down for future integration providers, not yet wired to a router). Not
  fixed this phase: there is no live, triggerable path through it today,
  and hardening unreached code speculatively is exactly the kind of
  padding this audit is trying to avoid. Flagged here so the gap is
  known before the first real caller is wired up.
- `app/core/ai/providers/openrouter.py`, `app/core/ai/providers/local.py`
  — calls happen behind the AI gateway's circuit breaker + per-provider
  retry (`app/core/reliability.py`), which already treats connection
  failures as breaker-trip signals; no bare unhandled-exception path.

### Existing failure-recovery test coverage (inventoried, not modified)

Already covers real reliability surfaces from earlier mandates — no gap
found in what they exercise:

- `tests/test_integrations.py::TestRetry` — Integration SDK sync-engine
  retry/backoff behavior.
- `tests/test_sandbox.py::TestCrashRecovery` — sandbox worker one-shot
  respawn-on-crash (plugin gap 5).
- `tests/test_workflow.py::TestRetry` — workflow engine step retry.

### Known constraints (documented previously, unchanged)

`PERFORMANCE.md`'s "Known single-instance constraints" section already
covers WebSocket fan-out, process-manager ports, and circuit-breaker
state being per-instance — those are scaling constraints, not
reliability bugs, and are out of this phase's scope.
