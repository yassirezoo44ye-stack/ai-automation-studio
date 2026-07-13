"""
FastAPI application factory.
Centralises app creation, middleware, lifespan, static files, and router registration
so the entry point (app_main.py or main.py) stays lean.
"""
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import stripe
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth import verify_token
from app.core.config import (
    APP_URL, DATABASE_URL, DIST_DIR, PUBLIC_PREFIXES, WORKSPACES,
)
from app.core.db import init_db, set_pool, get_pool, ensure_agents_table, ensure_tasks_table, ensure_audit_table
from app.core.logging import configure_logging
from app.core.middleware import AccessLogMiddleware, RequestIdMiddleware
from app.core.maintenance import maintenance_loop, process_cleanup_loop, record_error
from app.core.rate_limit import check_rate_limit
from app.billing import QuotaExceeded
from app.runtime import registry as runtime_registry
from app.runtime import capabilities as runtime_capabilities
from app.routers import (
    agents, build, chat, design, health, inference, package, projects,
    runtime, social, stats, subscriptions, tasks, youtube,
)
from app.routers import auth_users
from app.routers import orchestrator as orchestrator_router
from app.routers import runtime_api as runtime_api_router
from app.routers import commands_api as commands_api_router
from app.routers import kernel_api as kernel_api_router
from app.routers import agent_os_api as agent_os_api_router
from app.routers import planning_api   as planning_api_router
from app.routers import diagnostics_api as diagnostics_api_router
from app.routers import marketplace      as marketplace_router
from app.routers import arabic_api       as arabic_api_router
from app.routers import workflow_api     as workflow_api_router
from app.routers import jobs_api         as jobs_api_router
from app.routers import api_keys_router  as api_keys_router_mod
from app.routers import ws               as ws_router
from app.routers import metrics          as metrics_router
from app.routers import organizations    as organizations_router
from app.routers import usage_api        as usage_api_router
from app.routers import org_billing      as org_billing_router
from app.routers import ai_router_api    as ai_router_api_router
from app.routers import events_api       as events_api_router
from app.routers import plugins          as plugins_router
from app.routers import sandbox          as sandbox_router

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    set_pool(pool)
    async with pool.acquire() as conn:
        await init_db(conn)
    await ensure_agents_table()
    await ensure_tasks_table()
    await ensure_audit_table()
    WORKSPACES.mkdir(exist_ok=True)
    DIST_DIR.mkdir(exist_ok=True)
    (DIST_DIR / "zips").mkdir(exist_ok=True)
    await runtime_registry.discover()
    runtime_capabilities.compute()
    # Initialize AI Platform with DB pool
    from app.core.ai.platform import platform as ai_platform
    ai_platform.init(pool)
    maintenance_task = asyncio.create_task(maintenance_loop())
    cleanup_task     = asyncio.create_task(process_cleanup_loop())

    # ── Enterprise multi-tenancy + usage + org-billing schemas ─────────────
    from app.tenancy import init_tenancy_schema
    from app.billing import (
        init_usage_schema, init_subscription_plans_schema, init_invoices_schema,
        init_payment_methods_schema, init_billing_events_schema,
        init_coupons_schema, init_credits_schema, get_plan_service,
    )
    from app.billing.subscriptions import init_org_subscriptions_schema
    from app.core.api_keys import init_api_keys_schema
    async with pool.acquire() as conn:
        await init_tenancy_schema(conn)
        await init_subscription_plans_schema(conn)
        await init_usage_schema(conn)
        await init_org_subscriptions_schema(conn)
        await init_api_keys_schema(conn)
        await init_invoices_schema(conn)
        await init_payment_methods_schema(conn)
        await init_billing_events_schema(conn)
        await init_coupons_schema(conn)
        await init_credits_schema(conn)
    await get_plan_service(pool).refresh_cache()

    # ── AI usage ledger — references organizations (tenancy block above)
    # and users/conversations (init_db above). AI Routing consolidation:
    # this is the single persisted cost/token source of truth.
    from app.ai import init_ai_usage_schema
    async with pool.acquire() as conn:
        await init_ai_usage_schema(conn)

    # ── Marketplace store (PostgreSQL primary, JSON fallback) ──────────────
    from app.marketplace import init_marketplace_store
    await init_marketplace_store(pool)

    # ── Production Marketplace: categories/publishers/dependencies/assets/
    # changelog/downloads. Publishers must init after marketplace_items
    # exists (it ALTERs that table to add publisher_id) — init_marketplace_
    # store already ran above, so ordering is safe.
    from app.marketplace import (
        init_categories_schema, init_publishers_schema, init_dependencies_schema,
        init_assets_schema, init_changelog_schema, init_downloads_schema,
    )
    async with pool.acquire() as conn:
        await init_categories_schema(conn)
        await init_publishers_schema(conn)
        await init_dependencies_schema(conn)
        await init_assets_schema(conn)
        await init_changelog_schema(conn)
        await init_downloads_schema(conn)

    # ── Plugin SDK & Extension Framework — references marketplace_items,
    # so must init after the marketplace block above.
    from app.plugins import init_plugins_schema
    async with pool.acquire() as conn:
        await init_plugins_schema(conn)

    # ── Agent Sandbox — references plugin_installations, so must init
    # after the Plugin SDK block above.
    from app.sandbox import init_sandbox_schema
    async with pool.acquire() as conn:
        await init_sandbox_schema(conn)

    # ── Scoped Row Level Security (defense-in-depth on tenancy tables) ─────
    from app.tenancy import enable_scoped_rls
    async with pool.acquire() as conn:
        await enable_scoped_rls(conn)

    # ── Event bus (Redis Streams when available) ────────────────────────────
    from app.core.events import get_event_bus
    await get_event_bus().connect()

    # ── Redis cache adapter ─────────────────────────────────────────────────
    from app.core.cache import get_redis
    cache = await get_redis()

    # ── Background job queue (Redis-backed when available) ──────────────────
    from app.core.jobs import get_job_queue
    get_job_queue(cache=cache)

    # ── Autonomous background services ──────────────────────────────────────
    from app.services.registry import get_service_registry
    svc_registry = get_service_registry()
    svc_registry.start_all()

    # ── Semantic memory — initialize pgvector tier ──────────────────────────
    from app.memory.semantic import get_semantic_memory
    await get_semantic_memory(pool=pool)

    # ── Arabic NLU — wire gateway if available ───────────────────────────────
    from app.ai.arabic_nlu import get_arabic_nlu
    try:
        from app.ai.gateway import get_gateway
        get_arabic_nlu(gateway=get_gateway())
    except Exception:
        get_arabic_nlu()  # heuristic-only mode

    # ── Boot AgentKernel (registers health probes via observability layer) ──
    from app.agents.kernel import get_agent_kernel
    get_agent_kernel()   # ensures boot() is called once

    # ── Register DB health probe ────────────────────────────────────────────
    from app.core.observability.health import get_health_registry, HealthStatus, ProbeResult
    async def probe_db() -> ProbeResult:
        try:
            p = get_pool()
            async with p.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return ProbeResult(name="database", status=HealthStatus.HEALTHY,
                               message="PostgreSQL OK")
        except Exception as exc:
            return ProbeResult(name="database", status=HealthStatus.UNHEALTHY,
                               message=str(exc))
    get_health_registry().register("database", probe_db, critical=True, timeout_s=5.0)

    yield

    # ── Shutdown ────────────────────────────────────────────────────────────
    svc_registry.stop_all()
    maintenance_task.cancel()
    cleanup_task.cancel()
    await pool.close()


# ── Middleware ─────────────────────────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS: 1 year, include subdomains — tells browsers to always use HTTPS.
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        # unsafe-eval removed. unsafe-inline kept for Vite-injected styles (style-src only).
        # script-src does not include unsafe-inline — Vite bundles all JS externally.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.stripe.com https://checkout.stripe.com; "
            "frame-src https://checkout.stripe.com https://js.stripe.com blob:; "
            "font-src 'self' data:;"
        )
        return response


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
    app = FastAPI(title="Axon", version="1.0.0", lifespan=lifespan)

    # ── OpenTelemetry — auto-instruments HTTP request/response spans.
    # get_tracer() (app/core/observability/tracer.py) sets the global
    # TracerProvider before this runs, so these auto-created spans land in
    # the same ring buffer /api/diagnostics/traces* already reads from —
    # one tracer, not a second parallel one. Gated by OBS_TRACING_ENABLED
    # (default on) so it can be disabled without a code change.
    if os.getenv("OBS_TRACING_ENABLED", "true").lower() != "false":
        from app.core.observability.tracer import get_tracer
        get_tracer()  # registers the global TracerProvider first
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)

    # ── Exception handlers ──────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        detail = "; ".join(
            f"{' -> '.join(str(l) for l in e['loc'])}: {e['msg']}" for e in errors
        )
        return JSONResponse(status_code=422, content={"detail": detail, "errors": errors})

    @app.exception_handler(QuotaExceeded)
    async def quota_exceeded_handler(request: Request, exc: QuotaExceeded):
        return JSONResponse(
            status_code=429,
            content={
                "detail": str(exc), "error": "quota_exceeded",
                "metric": exc.metric, "used": exc.used, "limit": exc.limit,
            },
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        import asyncpg as _asyncpg
        category = "db" if isinstance(exc, (_asyncpg.exceptions.PostgresError, OSError)) else "app"
        record_error(category)
        print(f"UNHANDLED ERROR on {request.url.path}: {exc}", file=sys.stderr)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    # ── Tenant context (single source of truth for X-Organization-Id) ──────
    # Extracts the header once into request.state.org_id. This never grants
    # or denies anything — real membership enforcement stays entirely in
    # OrgContext/org_context (app/tenancy/context.py), which does its own DB
    # check. This middleware only avoids re-parsing the same header in every
    # place that wants the raw org id (e.g. metrics_middleware below).
    @app.middleware("http")
    async def tenant_context_middleware(request: Request, call_next):
        request.state.org_id = request.headers.get("X-Organization-Id")
        return await call_next(request)

    # ── Prometheus metrics collection ───────────────────────────────────────
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        import time as _time
        t0       = _time.perf_counter()
        response = await call_next(request)
        duration = _time.perf_counter() - t0
        # Collapse dynamic path segments so cardinality stays low
        path = request.url.path
        for seg in path.split("/"):
            if seg and (len(seg) > 20 or (seg.count("-") > 2)):
                path = path.replace(seg, "{id}")
                break
        try:
            from app.routers.metrics import record_http
            record_http(request.method, path, response.status_code, duration)
        except Exception:
            pass
        # Best-effort org-scoped API request metering — fire-and-forget so a
        # Redis/DB hiccup never adds latency or fails the actual request.
        # Falls back to a direct header read if tenant_context_middleware
        # hasn't run yet on this request (Starlette middleware order isn't
        # load-bearing here — both paths read the same header).
        org_id = getattr(request.state, "org_id", None) or request.headers.get("X-Organization-Id")
        if org_id and path.startswith("/api/"):
            async def _meter():
                try:
                    from app.billing import get_usage_service
                    await get_usage_service().record(org_id, "api_requests", 1)
                except Exception:
                    pass
            asyncio.create_task(_meter())
        return response

    # ── Global rate limiting (before auth, protects public endpoints too) ──
    @app.middleware("http")
    async def global_rate_limit_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            ip = (
                request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or (request.client.host if request.client else "unknown")
            )
            if not check_rate_limit(f"global:{ip}", max_calls=300, window=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — please slow down."},
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)

    # ── Auth middleware (pure ASGI — doesn't buffer SSE) ───────────────────
    @app.middleware("http")
    async def api_auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not any(path.startswith(p) for p in PUBLIC_PREFIXES):
            sub_token = (
                request.headers.get("X-Sub-Token") or
                request.cookies.get("sub_token", "")
            )
            bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()

            if sub_token and verify_token(sub_token):
                pass  # valid subscription token
            else:
                # Fall back to JWT — registered users who logged in via the
                # new auth system are authorized even without a sub_token.
                from app.core.jwt_utils import decode_access_token
                import jwt as _jwt
                try:
                    if not bearer:
                        raise ValueError("no bearer")
                    decode_access_token(bearer)
                except Exception:
                    return JSONResponse(status_code=401, content={"detail": "Subscription required"})
        return await call_next(request)

    # ── CORS + security headers ─────────────────────────────────────────────
    _cors_origins = (
        [APP_URL] if APP_URL and APP_URL != "http://localhost:8000"
        else ["http://localhost:5173", "http://localhost:8000", "http://127.0.0.1:8000"]
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Sub-Token", "X-Request-Id", "X-Organization-Id"],
    )

    # ── Static frontend (non-catch-all assets first) ────────────────────────
    DIST = Path(__file__).parent.parent / "dist"
    if DIST.exists() and (DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/", response_class=HTMLResponse)
    async def root():
        index = DIST / "index.html"
        content = index.read_text(encoding="utf-8") if index.exists() else (
            "<h1>◈ Axon — Backend Running</h1><p><a href='/docs'>API Docs</a></p>"
        )
        return HTMLResponse(content, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    @app.get("/manifest.json")
    async def serve_manifest():
        for f in (DIST / "manifest.json", Path(__file__).parent.parent / "public" / "manifest.json"):
            if f.exists():
                return Response(f.read_text(encoding="utf-8"), media_type="application/manifest+json")
        from fastapi import HTTPException
        raise HTTPException(404)

    @app.get("/sw.js")
    async def serve_sw():
        for f in (DIST / "sw.js", Path(__file__).parent.parent / "public" / "sw.js"):
            if f.exists():
                return Response(f.read_text(encoding="utf-8"), media_type="application/javascript")
        from fastapi import HTTPException
        raise HTTPException(404)

    @app.get("/icon-{size}.png")
    async def serve_icon(size: str):
        from fastapi import HTTPException
        if size not in ("192", "512"):
            raise HTTPException(404)
        for f in (DIST / f"icon-{size}.png", Path(__file__).parent.parent / "public" / f"icon-{size}.png"):
            if f.exists():
                return Response(f.read_bytes(), media_type="image/png")
        raise HTTPException(404)

    # ── API Routers (must be registered BEFORE the SPA catch-all) ───────────
    app.include_router(auth_users.router)
    app.include_router(orchestrator_router.router)
    app.include_router(runtime_api_router.router)
    app.include_router(commands_api_router.router)
    app.include_router(kernel_api_router.router)
    app.include_router(agent_os_api_router.router)
    app.include_router(planning_api_router.router)
    app.include_router(diagnostics_api_router.router)
    app.include_router(marketplace_router.router)
    app.include_router(marketplace_router.admin_router)
    app.include_router(arabic_api_router.router)
    app.include_router(workflow_api_router.router)
    app.include_router(jobs_api_router.router)
    app.include_router(api_keys_router_mod.router)
    app.include_router(ws_router.router)
    app.include_router(metrics_router.router)
    app.include_router(organizations_router.router)
    app.include_router(usage_api_router.router)
    app.include_router(org_billing_router.router)
    app.include_router(ai_router_api_router.router)
    app.include_router(events_api_router.router)
    app.include_router(plugins_router.router)
    app.include_router(sandbox_router.router)
    for r in (health, subscriptions, chat, stats, projects, build,
              agents, tasks, social, youtube, package, design, runtime, inference):
        app.include_router(r.router)

    # ── SPA catch-all (MUST be last — only reached if no API route matched) ─
    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def spa_fallback(full_path: str):
        index = DIST / "index.html"
        if index.exists():
            return HTMLResponse(
                index.read_text(encoding="utf-8"),
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
        return HTMLResponse("Not found", status_code=404)

    return app
