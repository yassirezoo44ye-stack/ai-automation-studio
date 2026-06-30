"""
Central configuration: reads all environment variables once at import time.
Every other module imports from here — no scattered os.getenv() calls.
"""
import os
import sys
import uuid
import secrets
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
SESSION_SECRET: str = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
if not os.getenv("SESSION_SECRET"):
    print(
        "WARNING: SESSION_SECRET not set — tokens will invalidate on every restart. "
        "Set SESSION_SECRET in your environment.",
        file=sys.stderr,
    )
TOKEN_TTL: int = 3600 * 24 * 30  # 30 days

# ── Stripe ────────────────────────────────────────────────────────────────────
_stripe.api_key          = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID: str       = os.getenv("STRIPE_PRICE_ID", "")
APP_URL: str               = os.getenv("APP_URL", "http://localhost:8000")

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
    "/api/subscription/",
    "/api/stripe/",
    "/api/health/",
    "/health",
)
