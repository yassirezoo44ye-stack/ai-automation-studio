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
