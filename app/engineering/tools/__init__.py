"""
Engineering Tool Registry — all typed tools available to Claude.

Every tool in this package is:
  - typed (explicit input/output schema)
  - allowlisted (only tools defined here can be called)
  - permission-checked (minimum role enforced before execution)
  - org-scoped (credentials loaded by org_id from CredentialStore)
  - audited (every call logged to activity_logs)
  - evidence-producing (EvidenceStore.record() called on every result)

Tool categories and minimum roles:
  READ        → viewer    (read-only inspection)
  ANALYZE     → developer (schema/data analysis)
  WRITE       → operator  (data modification)
  DEPLOY      → admin     (trigger deployments — approval-gated)
  DESTRUCTIVE → owner     (merge/delete — always approval-gated)

Import tool modules to trigger registration in the gateway registry.
ALL_TOOLS (tool_name → async fn) lives in gateway.py to avoid
circular imports — importing this package makes it fully populated.
"""
# Importing each module triggers its _register_*_tools() call at module load,
# which populates both the ToolRegistry and gateway.ALL_TOOLS.
# Order doesn't matter (no inter-module dependencies between tool files).
from app.engineering.tools import github_tools   # noqa: F401
from app.engineering.tools import render_tools   # noqa: F401
from app.engineering.tools import vercel_tools   # noqa: F401
from app.engineering.tools import sentry_tools   # noqa: F401
from app.engineering.tools import database_tools  # noqa: F401

# Re-export the canonical dicts for inspection / tests
from app.engineering.tools.github_tools   import GITHUB_TOOLS    # noqa: F401
from app.engineering.tools.render_tools   import RENDER_TOOLS    # noqa: F401
from app.engineering.tools.vercel_tools   import VERCEL_TOOLS    # noqa: F401
from app.engineering.tools.sentry_tools   import SENTRY_TOOLS    # noqa: F401
from app.engineering.tools.database_tools import DATABASE_TOOLS  # noqa: F401

# ALL_TOOLS is populated by the imports above; reference it from gateway
from app.engineering.tools.gateway import ALL_TOOLS  # noqa: F401

__all__ = [
    "ALL_TOOLS",
    "GITHUB_TOOLS",
    "RENDER_TOOLS",
    "VERCEL_TOOLS",
    "SENTRY_TOOLS",
    "DATABASE_TOOLS",
]
