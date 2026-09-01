# P0 decision: `sub_token` is not revoked by logout / logout-all

Status: **Option A implemented (2026-09-01)** — mitigation shipped, real fix still pending.
`TOKEN_TTL` (`app/core/config.py`) cut from 30 days to 20 minutes; `refresh_token()`
(`app/routers/auth_users.py`) now re-mints `sub_token` alongside `access_token` on every
`/refresh` call; frontend `doRefresh()` (`AuthContext.tsx`) stores the re-minted token.
Verified: 180 security tests, 64 auth-lifecycle/OAuth tests, 8 frontend AuthContext tests,
clean `tsc` — no regressions. **A captured `sub_token` is now valid for at most ~20 minutes
instead of up to 30 days**, but Logout/Logout-all still don't actively revoke it (it just
expires fast on its own) — that's still true statelessness, not real logout-binding.

**Option B vs Option C is still an open decision, not yet made** — this file's own
recommendation (Option C, via the existing Redis/cache adapter) stands unless you decide
otherwise. Nothing below this line has changed; it still describes the un-implemented
full-fix options.

## What's actually true (verified against current code, not assumed)

- `app/core/auth.py::make_token()` mints a stateless, HMAC-SHA256-signed, base64url JSON
  blob (`{"e": email, "exp": now+TOKEN_TTL, "trial": bool, "dr": int}`). `TOKEN_TTL =
  3600*24*30` (30 days) — `app/core/config.py`.
- `verify_token()` checks only the HMAC signature and `exp`. **No DB or session lookup at
  all** — that's the whole point of this token (see its own module docstring: "derive
  per-user identity without a DB lookup on every request").
- It is minted at exactly two call sites, both in `app/routers/auth_users.py`, both
  immediately after a `user_sessions` row is created for the same login:
  - `_finish_login()` (password login), line ~263
  - `_make_oauth_session()` (Google/Microsoft/GitHub login), line ~916
- `api_auth_middleware` (`app/factory.py`) and `owner_email()`/`owner_user_id()`
  (`app/core/auth.py`) accept a valid `sub_token` via `X-Sub-Token` exactly like a JWT
  `Authorization: Bearer` — same trust level, same access.
- `logout()` and `logout_all()` (`app/routers/auth_users.py`) only ever run `DELETE FROM
  user_sessions WHERE refresh_token=$1` / `WHERE user_id=$1`. Confirmed via
  `inspect.getsource()` — **neither touches or even references `sub_token` in any way.**

**Consequence**: a `sub_token` captured at any point (XSS, log leak, malicious extension,
shared device, etc.) remains a fully valid credential for up to 30 days, completely
unaffected by the user clicking Logout, Logout-all, or a password reset. This is a real
P0 — session/credential revocation is a basic security expectation and it silently
doesn't work for this half of the dual-auth system.

## Why this isn't fixed inline

`sub_token` is stateless by design specifically to avoid a DB hit on every request. Any
fix that makes it revocable makes it *not stateless* for at least logout-checking
purposes — that's a real, if small, architectural change to how the token is verified
(`verify_token()` today takes no `conn` and is synchronous; `owner_email()` is sync too
and is called from many routers). It also touches every call site that imports
`owner_email`/`owner_user_id` (`tasks.py`, `stats.py`, `design.py`, `agents.py`,
`commands_api.py`, `build.py`, `projects.py`, `inference.py`, `planning_api.py`,
`chat.py`, `runtime_api.py`, `package.py`, `rate_limit.py`). That's exactly the kind of
change Section 20 says to propose, not silently execute.

## Three options, cheapest to most complete

### Option A — shrink the blast radius, no code beyond a constant (mitigation, not a fix)
Drop `TOKEN_TTL` from 30 days to something close to the access-token lifetime (e.g. 15–60
min), and let the frontend's existing `scheduleRefresh()` cycle silently re-mint
`sub_token` alongside every `/refresh` call the same way it already gets a new
`access_token`. Zero schema change, zero new DB/Redis dependency, ships in one line plus
one small addition to `_finish_login`'s counterpart on the refresh path.
**Does not achieve real logout-binding** — a captured token is still valid, just for
minutes instead of weeks. Cheapest, weakest.

### Option B — Postgres column, `tokens_invalidated_at` on `users`
Add a nullable `users.tokens_invalidated_at TIMESTAMPTZ` (additive migration, no data
loss). `logout()`/`logout_all()` set it to `NOW()`. Add an `iat` claim to the token
payload; `owner_email()`/`owner_user_id()` become async, take a `conn`, and reject if
`iat < tokens_invalidated_at`. **Fully correct**, but reintroduces a DB round-trip on
every sub_token-authenticated request (the exact cost the token was designed to avoid)
and requires touching every caller's signature — the largest blast radius of the three.

### Option C — reuse the existing Redis/cache adapter (recommended)
`app/core/cache/redis_adapter.py`'s `RedisAdapter` (`get_redis()`) is already live in
this codebase (OAuth exchange codes, presence, cache invalidation) and already
degrades to an in-process TTL dict when `REDIS_URL` isn't set — no new infra dependency
either way.
- Add an `iat` claim to the sub_token payload (needed by all three options).
- On `logout()`/`logout_all()`: `await redis.set(f"tok_invalid_after:{user_id}",
  str(now_ts), ttl=TOKEN_TTL)`.
- `owner_email()`/`owner_user_id()` become async (they mostly already are, or are always
  called from an async route handler) and do one `await redis.get(...)` — sub-millisecond
  against real Redis, in-memory-dict-speed against the fallback — then compare `iat`
  against it.
- Optional: cache the "not invalidated" fast path in-process for a few seconds per user
  to avoid a lookup on literally every request if this ever becomes hot-path-sensitive.

This is the one that matches your stated preference — session/logout-bound using a
structure that already exists in this codebase, no new migration, no new infra. The real
cost is still touching `owner_email()`/`owner_user_id()` call sites to await the new
async signature (mechanical, but it's ~13 files).

## Recommendation

Option C. Option A is worth shipping regardless of what happens with B/C — it's a
strict, independent risk reduction with no downside, and can land same-day once
approved. Option B only makes sense if Redis is being removed from the stack for some
other reason (it is not).

**Waiting on your decision before writing any of this** — flagged per Section 20 as an
authentication-architecture change, not something to execute silently.
