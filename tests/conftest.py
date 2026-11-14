"""
Set required environment variables BEFORE any test file imports main.py.
main.py calls sys.exit(1) at module-load time if DATABASE_URL is missing,
so conftest.py (loaded first by pytest) sets a dummy value to prevent that.

Module pre-loading
──────────────────
test_leads.py calls _register_stubs() at module level with `if not in sys.modules`
guards so it only replaces modules that have not yet been imported.  Because conftest
is loaded before any test file is collected, we pre-load the real implementations
here.  That ensures the stubs in test_leads.py do NOT replace them, which would
break every other test that relies on the real OrgContext, ws.router, etc.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test_axon")
os.environ.setdefault(
    "SESSION_SECRET",
    "ci-test-secret-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
)

# Pre-load real implementations so test_leads.py stubs cannot replace them.
# These imports are safe: the modules do not connect to a DB at import time.
import app.tenancy            # noqa: E402,F401 — needs env vars set above
import app.tenancy.context    # noqa: E402,F401
import app.routers.ws         # noqa: E402,F401
import app.core.notifications          # noqa: E402,F401
import app.core.notifications.service  # noqa: E402,F401
import app.core.db            # noqa: E402,F401
import app.core.jobs          # noqa: E402,F401
