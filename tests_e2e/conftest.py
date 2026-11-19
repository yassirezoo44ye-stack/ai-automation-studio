"""End-to-end HTTP tests against the real app, real auth and real PostgreSQL.

Run separately from the unit suite, against an EMPTY database that nothing
else uses (the app's real lifespan() creates the schema in it):

    FLOW_E2E_DATABASE_URL=postgresql://test:test@localhost:5432/flow_e2e \
        python -m pytest tests_e2e -v

Only synthetic data is created (example.com addresses, generated names).
No email is sent without SMTP_HOST, and no payment provider is called.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

_DSN = os.getenv("FLOW_E2E_DATABASE_URL")

if _DSN:
    # app.core.config reads DATABASE_URL once, at import time.
    os.environ["DATABASE_URL"] = _DSN
    os.environ.setdefault("SESSION_SECRET", "e2e-session-secret-" + "x" * 48)
    os.environ.pop("SMTP_HOST", None)          # console email only
    os.environ.pop("STRIPE_SECRET_KEY", None)  # never reach Stripe


def pytest_collection_modifyitems(config, items):
    if _DSN:
        return
    skip = pytest.mark.skip(reason="set FLOW_E2E_DATABASE_URL to an empty database to run E2E tests")
    for item in items:
        item.add_marker(skip)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_transport():
    """One real app (lifespan) per test session.

    Several services cache the DB pool in module-level singletons, so the
    app must not be started twice in one process, exactly as in production
    where one process runs one lifespan.
    """
    import httpx
    from app.factory import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        yield httpx.ASGITransport(app=app)
