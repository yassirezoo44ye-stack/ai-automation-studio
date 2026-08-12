"""Domain-level exceptions. Routers translate these into HTTP responses.

Keeping these framework-agnostic means services/repositories never import FastAPI,
which keeps business logic testable and reusable from Celery workers later.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all expected/business errors."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ValidationDomainError(DomainError):
    pass


class AuthenticationError(DomainError):
    """Invalid credentials, expired/invalid/missing token."""


class AuthorizationError(DomainError):
    """Authenticated, but not allowed to perform this action."""


class RateLimitedError(DomainError):
    pass


class ConfigurationError(DomainError):
    """A feature is unreachable because required configuration (e.g. an AI
    provider API key) is missing — never faked, always surfaced clearly."""
