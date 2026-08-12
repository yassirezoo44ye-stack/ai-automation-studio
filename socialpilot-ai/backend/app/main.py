"""FastAPI application factory."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    DomainError,
    NotFoundError,
    RateLimitedError,
    ValidationDomainError,
)
from app.core.logging import configure_logging, get_logger
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import limiter

settings = get_settings()

_ERROR_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ValidationDomainError: 422,
    AuthenticationError: 401,
    AuthorizationError: 403,
    RateLimitedError: 429,
    ConfigurationError: 503,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(json_logs=settings.is_production, level="DEBUG" if settings.debug else "INFO")
    logger = get_logger(__name__)
    settings.validate_for_production()
    logger.info("startup", environment=settings.environment, app=settings.app_name)
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)
    # No SlowAPIMiddleware: `@limiter.limit(...)` on individual routes (see
    # api/v1/auth.py) is self-contained and doesn't need it. Adding it would
    # reintroduce a `BaseHTTPMiddleware` layer — see middleware.py docstring.

    for exc_type, status_code in _ERROR_STATUS_MAP.items():
        app.add_exception_handler(exc_type, _make_domain_error_handler(status_code))

    app.include_router(api_router, prefix=settings.api_prefix)

    return app


def _make_domain_error_handler(status_code: int):
    async def _handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return _handler


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again later."})


app = create_app()
