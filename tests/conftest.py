"""
Set required environment variables BEFORE any test file imports main.py.
main.py calls sys.exit(1) at module-load time if DATABASE_URL is missing,
so conftest.py (loaded first by pytest) sets a dummy value to prevent that.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test_axon")
os.environ.setdefault(
    "SESSION_SECRET",
    "ci-test-secret-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
)

# Import the real application package graph up front. Some test modules
# (e.g. test_leads.py) install bare `types.ModuleType` stubs for app.* modules
# that are not yet in sys.modules; if they get there first, every later import
# of the real module (test_routing.py → app.factory) fails during collection
# and aborts the whole run. Loading the app first means those guards see the
# real modules and leave them alone.
import app.factory  # noqa: E402,F401
