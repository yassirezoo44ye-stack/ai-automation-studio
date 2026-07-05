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
from app.runtime import registry as runtime_registry
from app.runtime import capabilities as runtime_capabilities
from app.routers import (
    agents, build, chat, design, health, inference, package, projects,
    runtime, social, stats, subscriptions, tasks, youtube,
)
from app.routers import auth_users
from app.routers import orchestrator as orchestrator_router

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
    yield
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
    configure_logging()
    app = FastAPI(title="Axon", version="1.0.0", lifespan=lifespan)

    # ── Exception handlers ──────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        detail = "; ".join(
            f"{' -> '.join(str(l) for l in e['loc'])}: {e['msg']}" for e in errors
        )
        return JSONResponse(status_code=422, content={"detail": detail, "errors": errors})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        import asyncpg as _asyncpg
        category = "db" if isinstance(exc, (_asyncpg.exceptions.PostgresError, OSError)) else "app"
        record_error(category)
        print(f"UNHANDLED ERROR on {request.url.path}: {exc}", file=sys.stderr)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

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
        allow_headers=["Content-Type", "Authorization", "X-Sub-Token", "X-Request-Id"],
    )

    # ── Static frontend ─────────────────────────────────────────────────────
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

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def spa_fallback(full_path: str):
        index = DIST / "index.html"
        if index.exists():
            return HTMLResponse(
                index.read_text(encoding="utf-8"),
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
        return HTMLResponse("Not found", status_code=404)

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

    # ── Routers ─────────────────────────────────────────────────────────────
    app.include_router(auth_users.router)
    app.include_router(orchestrator_router.router)
    for r in (health, subscriptions, chat, stats, projects, build,
              agents, tasks, social, youtube, package, design, runtime, inference):
        app.include_router(r.router)

    return app
