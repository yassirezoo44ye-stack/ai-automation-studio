"""
Compatibility shim — DO NOT launch this module as a server.

The live entry point is app_main.py. This file exists solely so that
tests/test_helpers.py can import the pure-logic helpers under their
legacy underscore names without being changed.

All logic now lives in the proper app/ modules.
"""
# ── Re-exports for test_helpers.py ────────────────────────────────────────────

from app.core.auth import make_token as _make_token
from app.core.auth import verify_token as _verify_token
from app.core.auth import owner_email as _owner_email
from app.core.config import SESSION_SECRET, TOKEN_TTL as _TOKEN_TTL
from app.core.rate_limit import check_rate_limit as _check_rate_limit
from app.core.rate_limit import rl_store as _rl_store
from app.core.helpers import resolve_project_id as _resolve_project_id
from app.core.helpers import sanitize_name as _sanitize
from app.core.helpers import next_due_date as _next_due_date
from app.core.helpers import anthropic_error_message as _anthropic_error_message

# DEMO_PROJECT_ID used by _resolve_project_id internally; exposed for test assertions
from app.core.config import DEMO_PROJECT_ID
