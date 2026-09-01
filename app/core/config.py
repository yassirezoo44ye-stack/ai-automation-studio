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
TOKEN_TTL: int = 60 * 20  # 20 minutes — sub_token is re-minted on every /refresh
# call (see refresh_token() in app/routers/auth_users.py) alongside the access
# token, so a short TTL costs nothing in practice but bounds how long a
# captured sub_token stays valid after logout/expiry. Was 30 days; that let a
# leaked sub_token (XSS, log leak, shared device) outlive Logout/Logout-all by
# weeks since neither endpoint touches it — see docs/SUB_TOKEN_P0_DECISION.md
# (Option A: mitigation, not full logout-binding — Option C tracked separately).

# ── Stripe ────────────────────────────────────────────────────────────────────
_stripe.api_key          = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID: str       = os.getenv("STRIPE_PRICE_ID", "")  # legacy flat $/mo trial gate
APP_URL: str               = os.getenv("APP_URL", "http://localhost:8000")
# Comma-separated additional CORS origins (e.g. a Vercel-hosted frontend)
# beyond the single primary APP_URL — the backend itself is served from a
# different host than the browser origin in a split frontend/backend setup.
EXTRA_CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("EXTRA_CORS_ORIGINS", "").split(",") if o.strip()
]

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

# ── Platform admins ───────────────────────────────────────────────────────────
# Comma-separated allowlist of emails permitted to hold the "admin" API-key
# scope (app/routers/api_keys_router.py's create_key, app/routers/
# organizations.py's create_org_api_key). That scope bypasses
# require_api_key(scopes=["admin"]) gates on genuinely dangerous endpoints
# (marketplace publisher trust, usage_api's admin views) — both key-creation
# paths previously accepted "admin" from any caller with zero check they
# were actually a platform admin, since account/org creation are both
# self-service. Empty by default: fails closed, matching is_development()'s
# rationale below — an unconfigured deployment grants nobody "admin" rather
# than granting everybody.
ADMIN_EMAILS: frozenset[str] = frozenset(
    e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
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
