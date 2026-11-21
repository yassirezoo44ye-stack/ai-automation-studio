# Free tools with user-funded compute — implementation audit

Status: isolated feature branch; not deployed, merged, or wired to live billing.

## Verified existing integration points
- `app/ai/gateway.py`: central AI gateway; currently routes via platform registry.
- `app/core/ai/registry/registry.py`: registry selects environment-configured providers.
- `app/core/ai/providers/local.py`: supports OpenAI-compatible local servers
  configured through server-side `LOCAL_MODEL_BASE_URL`.
- `app/routers/ai_router_api.py`: existing model, provider, budget and usage endpoints.

## Key risks and required changes
1. Environment-level credentials are **not** per-user BYOK.
2. A server's localhost is not a browser user's laptop.
3. Never accept arbitrary user-supplied model URLs from the backend without
   an SSRF-safe design and explicit trust boundaries.
4. Never silently fall back to platform-funded AI when BYOK/local fails.
5. Encrypt per-user secrets using a dedicated managed key, restrict reads to
   verified principals, and redact logs, traces, errors, and telemetry.
6. Preserve existing billing and subscription behavior until migration is
   approved; never automatically grant unlimited compute.
7. Build a mutually authenticated outbound local-agent channel with
   short-lived credentials, capability restrictions and cancellation.
8. Enforce concurrency, storage and network quotas independently of AI tokens.

## Implemented in this branch
- Pure, fail-closed compute selection policy.
- Unit tests for mode selection, explicit authorization, and absence of
  platform fallback.

## Pending
- Identity-bound encrypted credential storage and revocation.
- Scoped provider adapters and gateway integration, including streaming.
- Local agent enrollment, protocol, device trust and lifecycle.
- Free-plan entitlement migration and resource budgets.
- End-to-end, isolation, security and regression tests.

No API endpoints or production paths have been modified.
