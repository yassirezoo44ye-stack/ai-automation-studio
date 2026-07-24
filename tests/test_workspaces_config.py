"""
Regression test for a doc-vs-code drift found during the v1.0 Phase 6
documentation audit: app.core.config.WORKSPACES resolves from the
WORKSPACES_DIR env var (matching .env.example/README), but
deploy_agent.py and marketplace/store.py used to independently read a
differently-named var, os.getenv("WORKSPACES", "/tmp") — which nobody
sets, so both silently wrote to /tmp regardless of WORKSPACES_DIR.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.core.config import WORKSPACES  # noqa: E402


class TestWorkspacesSingleSourceOfTruth:
    """Equality, not identity: some other test in the suite can cause
    app.core.config to be imported under two separate module-cache
    entries (e.g. via sys.path manipulation elsewhere), which makes two
    otherwise-identical Path objects fail an `is` check despite both
    correctly resolving from WORKSPACES_DIR. What actually matters here —
    that deploy_agent/store didn't drift back to reading their own,
    differently-named env var — is fully captured by path equality."""

    def test_deploy_agent_uses_the_shared_workspaces_constant(self):
        from app.agents.builtin.deploy_agent import WORKSPACES as deploy_ws
        assert deploy_ws == WORKSPACES

    def test_marketplace_store_uses_the_shared_workspaces_constant(self):
        from app.marketplace.store import WORKSPACES as store_ws
        assert store_ws == WORKSPACES

    def test_json_marketplace_store_resolves_under_the_shared_workspaces_dir(self):
        from app.marketplace.store import JsonMarketplaceStore
        store = JsonMarketplaceStore()
        assert store._dir == WORKSPACES / ".marketplace"
