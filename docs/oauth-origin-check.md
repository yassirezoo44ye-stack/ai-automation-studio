# OAuth origin verification

The frontend requests `/api/auth/oauth-config` before social login. Its public
`origin` is derived from backend `APP_URL`, the same base used to build each
provider callback. Navigation then starts directly at that origin, avoiding a
Vercel-proxied start that sets a host-only cookie on Vercel while the callback
arrives on Render.

Deploy the backend endpoint before the frontend. `APP_URL` must be the HTTPS
backend origin without a path; provider consoles must allow the corresponding
`/api/auth/{google|github|microsoft}/callback` URL. `FRONTEND_URL` remains the
frontend origin for the final session exchange redirect. The endpoint exposes
only the public origin and disables caching; no credentials are returned.

Manual verification on a preview with real provider configuration:
1. Begin from the library or login screen; choose each provider separately.
2. Confirm the browser navigates to the canonical backend before the provider.
3. Complete login and verify the final Flow signed-in state.
4. Reject missing/mismatched binding cookies, replayed callbacks and expired state.
5. Simulate configuration lookup failure and verify a readable error without navigation.

This patch does not change state lifetime or remove cookie binding. Shared Redis
is still required for reliable cross-worker state storage. An in-process cache
loses state on restart and cannot share it across workers. No state tokens,
cookies, authorization codes or credentials should be copied into reports.
