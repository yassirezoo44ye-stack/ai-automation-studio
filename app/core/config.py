"""
Central configuration: reads all environment variables once at import time.
Every other module imports from here — no scattered os.getenv() calls.
"""
import os
import sys
import uuid
from pathlib import Path

import stripe as _stripe

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print(
        "FATAL: DATABASE_URL is not set. "
        "Set it to a PostgreSQL connection string and restart.",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Session tokens ────────────────────────────────────────────────────────────
SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")
if not SESSION_SECRET:
    print(
        "FATAL: SESSION_SECRET is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and set it in your environment.",
        file=sys.stderr,
    )
    sys.exit(1)
TOKEN_TTL: int = 3600 * 24 * 30  # 30 days

# ── Stripe ────────────────────────────────────────────────────────────────────
_stripe.api_key          = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID: str       = os.getenv("STRIPE_PRICE_ID", "")  # legacy flat $/mo trial gate
APP_URL: str               = os.getenv("APP_URL", "http://localhost:8000")

# Org-scoped tiered plans (Enterprise is contact-sales — no Stripe price).
STRIPE_PRICE_ID_STARTER: str = os.getenv("STRIPE_PRICE_ID_STARTER", "")
STRIPE_PRICE_ID_PRO: str     = os.getenv("STRIPE_PRICE_ID_PRO", "")
STRIPE_PRICE_ID_TEAM: str    = os.getenv("STRIPE_PRICE_ID_TEAM", "")

# ── Filesystem ────────────────────────────────────────────────────────────────
# Root of the project (the directory that contains main.py).
_PROJECT_ROOT = Path(__file__).parent.parent.parent

WORKSPACES: Path = Path(os.getenv("WORKSPACES_DIR", str(_PROJECT_ROOT / "workspaces")))
DIST_DIR: Path   = _PROJECT_ROOT / "dist_packages"

# ── Seeded single-tenant identities ──────────────────────────────────────────
# The platform is currently single-tenant at the DB level: all legacy data
# (projects, agents, runs) is owned by this fixed user.  Tasks and future
# resources use owner_email for real multi-tenancy.
USER_ID: uuid.UUID         = uuid.UUID("00000000-0000-0000-0000-000000000000")
DEMO_PROJECT_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# ── Public API prefixes (no auth token required) ──────────────────────────────
PUBLIC_PREFIXES: tuple = (
    "/api/auth/",
    "/api/subscription/",
    "/api/stripe/",
    "/api/health/",
    "/health",
)

# ── Environment ───────────────────────────────────────────────────────────────
# Read live via functions (not cached at import time, unlike the constants
# above) so tests can toggle ENVIRONMENT with monkeypatch/os.environ without
# reloading this module — same rationale as ObservabilityConfig's live reads
# (app/core/observability/config.py). Unknown/unset values are treated as
# "production": anything that gates on is_development() (e.g. the feature-gate
# dev bypass, app/billing/feature_gate.py) fails closed by default, so a
# missing or misspelled ENVIRONMENT var can never accidentally relax a
# production deployment.
def get_environment() -> str:
    return os.getenv("ENVIRONMENT", "production").strip().lower()


def is_development() -> bool:
    return get_environment() == "development"
