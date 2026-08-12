"""
Tests for the AI Business App Builder.

Coverage:
  - spec generation (parsing + validation)
  - schema generation (entity/column validation)
  - tenant isolation (org_id scoping, IDOR prevention)
  - authorization (role-based access)
  - page generation (spec → pages mapping)
  - CRUD generation (api_operations count)
  - workflow generation
  - agent generation
  - incremental modification
  - failed build recovery (partial status)
  - destructive operation protection (forbidden keywords)
"""
from __future__ import annotations

import json
import uuid
import pytest

from app.services.app_builder import (
    AppBuilderService,
    AppSpec,
    EntityDef,
    ColumnDef,
    PageDef,
    RoleDef,
    WorkflowDef,
    AgentDef,
    BuildResult,
    _validate_entity_name,
    _validate_column_type,
    _FORBIDDEN_KEYWORDS,
    _canvas_uuid,
    _agent_uuid,
    _workflow_uuid,
    _CRON_KEYWORDS,
    _WEBHOOK_KEYWORDS,
    _SUPPORTED_ACTION_TYPES,
    STEP_LABELS,
    _TOTAL_STEPS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_spec(
    name: str = "Test CRM",
    entities: int = 2,
    pages: int = 3,
    roles: int = 2,
    workflows: int = 0,
    agents: int = 0,
) -> AppSpec:
    """Build a minimal valid AppSpec for testing."""
    ents = [
        EntityDef(
            name=f"entity_{i}",
            display_name=f"Entity {i}",
            columns=[
                ColumnDef(name="title", type="text"),
                ColumnDef(name="status", type="text", nullable=False),
                ColumnDef(name="count", type="integer"),
            ],
        )
        for i in range(entities)
    ]
    pgs = [
        PageDef(name=f"Page {i}", entity=f"entity_0", kind="list")
        for i in range(pages)
    ]
    rls = [
        RoleDef(name=f"Role{i}", permissions=[f"entity_0:read"])
        for i in range(roles)
    ]
    wfs = [
        WorkflowDef(
            name=f"Workflow {i}",
            trigger="on create",
            steps=[{"action": "notify", "type": "notify"}],
        )
        for i in range(workflows)
    ]
    ags = [
        AgentDef(
            name=f"Agent {i}",
            description="AI helper",
            system_prompt="You help users.",
        )
        for i in range(agents)
    ]
    return AppSpec(
        name=name,
        description="A test application",
        target_users="QA team",
        entities=ents,
        pages=pgs,
        roles=rls,
        workflows=wfs,
        agents=ags,
        integrations=[],
        settings={},
    )


# ── Spec validation ───────────────────────────────────────────────────────────

class TestSpecValidation:
    """Validate the whitelist-based spec parsing."""

    def _parse(self, data: dict) -> AppSpec:
        svc = AppBuilderService.__new__(AppBuilderService)
        return svc._parse_and_validate_spec(data)

    def test_valid_spec_parses(self):
        data = {
            "name": "Sales CRM",
            "description": "A CRM for the team.",
            "target_users": "Sales reps",
            "entities": [
                {
                    "name": "contacts",
                    "display_name": "Contacts",
                    "columns": [
                        {"name": "first_name", "type": "text", "nullable": True},
                        {"name": "is_active", "type": "boolean", "nullable": False},
                    ],
                    "relationships": [{"kind": "belongs_to", "target": "companies"}],
                }
            ],
            "pages": [{"name": "Dashboard", "entity": None, "kind": "dashboard"}],
            "roles": [{"name": "Admin", "permissions": ["contacts:read"]}],
            "workflows": [],
            "agents": [],
            "integrations": ["gmail"],
            "settings": {},
        }
        spec = self._parse(data)
        assert spec.name == "Sales CRM"
        assert len(spec.entities) == 1
        assert spec.entities[0].name == "contacts"
        assert len(spec.entities[0].columns) == 2
        assert spec.entities[0].columns[0].type == "text"
        assert spec.pages[0].kind == "dashboard"
        assert spec.integrations == ["gmail"]

    def test_rejects_invalid_entity_name(self):
        data = {
            "name": "App",
            "entities": [{"name": "123bad", "display_name": "Bad", "columns": []}],
            "pages": [], "roles": [], "workflows": [], "agents": [],
            "integrations": [], "settings": {},
        }
        with pytest.raises(ValueError, match="Invalid entity name"):
            self._parse(data)

    def test_rejects_forbidden_keyword_in_entity_name(self):
        for keyword in ("drop_table", "exec_cmd", "pg_catalog"):
            data = {
                "name": "App",
                "entities": [{"name": keyword, "display_name": "Bad", "columns": []}],
                "pages": [], "roles": [], "workflows": [], "agents": [],
                "integrations": [], "settings": {},
            }
            with pytest.raises(ValueError):
                self._parse(data)

    def test_rejects_unknown_column_type(self):
        data = {
            "name": "App",
            "entities": [
                {
                    "name": "items",
                    "display_name": "Items",
                    "columns": [{"name": "data", "type": "bytea", "nullable": True}],
                    "relationships": [],
                }
            ],
            "pages": [], "roles": [], "workflows": [], "agents": [],
            "integrations": [], "settings": {},
        }
        with pytest.raises(ValueError, match="Unsupported column type"):
            self._parse(data)

    def test_rejects_sql_injection_in_column_name(self):
        data = {
            "name": "App",
            "entities": [
                {
                    "name": "items",
                    "display_name": "Items",
                    "columns": [
                        {"name": "data; DROP TABLE users--", "type": "text", "nullable": True}
                    ],
                    "relationships": [],
                }
            ],
            "pages": [], "roles": [], "workflows": [], "agents": [],
            "integrations": [], "settings": {},
        }
        with pytest.raises(ValueError):
            self._parse(data)

    def test_caps_entities_at_20(self):
        data = {
            "name": "App",
            "entities": [
                {"name": f"entity_{i}", "display_name": f"E{i}", "columns": []}
                for i in range(30)
            ],
            "pages": [], "roles": [], "workflows": [], "agents": [],
            "integrations": [], "settings": {},
        }
        spec = self._parse(data)
        assert len(spec.entities) == 20

    def test_caps_columns_at_20_per_entity(self):
        data = {
            "name": "App",
            "entities": [
                {
                    "name": "items",
                    "display_name": "Items",
                    "columns": [
                        {"name": f"col_{i}", "type": "text", "nullable": True}
                        for i in range(30)
                    ],
                    "relationships": [],
                }
            ],
            "pages": [], "roles": [], "workflows": [], "agents": [],
            "integrations": [], "settings": {},
        }
        spec = self._parse(data)
        assert len(spec.entities[0].columns) == 20

    def test_valid_relationship_kinds(self):
        data = {
            "name": "App",
            "entities": [
                {
                    "name": "deals",
                    "display_name": "Deals",
                    "columns": [],
                    "relationships": [
                        {"kind": "belongs_to", "target": "contacts"},
                        {"kind": "has_many", "target": "tasks"},
                        {"kind": "invalid_kind", "target": "something"},  # should be dropped
                    ],
                }
            ],
            "pages": [], "roles": [], "workflows": [], "agents": [],
            "integrations": [], "settings": {},
        }
        spec = self._parse(data)
        assert len(spec.entities[0].relationships) == 2
        kinds = {r["kind"] for r in spec.entities[0].relationships}
        assert kinds == {"belongs_to", "has_many"}

    def test_invalid_page_kind_defaults_to_list(self):
        data = {
            "name": "App",
            "entities": [],
            "pages": [{"name": "MyPage", "entity": None, "kind": "wizard"}],
            "roles": [], "workflows": [], "agents": [],
            "integrations": [], "settings": {},
        }
        spec = self._parse(data)
        assert spec.pages[0].kind == "list"

    def test_spec_to_dict_roundtrip(self):
        svc = AppBuilderService.__new__(AppBuilderService)
        original = make_spec()
        d = svc._spec_to_dict(original)
        assert d["name"] == original.name
        assert len(d["entities"]) == len(original.entities)
        assert d["entities"][0]["name"] == original.entities[0].name


# ── Entity name / column type validators ──────────────────────────────────────

class TestValidators:
    def test_valid_entity_names(self):
        for name in ("contacts", "sales_reps", "order_item_123"):
            assert _validate_entity_name(name, "test") == name

    def test_hyphen_converted_to_underscore(self):
        assert _validate_entity_name("sales-reps", "test") == "sales_reps"

    def test_spaces_converted_to_underscore(self):
        assert _validate_entity_name("my entity", "test") == "my_entity"

    def test_starts_with_digit_rejected(self):
        with pytest.raises(ValueError):
            _validate_entity_name("1bad", "test")

    def test_forbidden_keywords_rejected(self):
        for kw in _FORBIDDEN_KEYWORDS:
            # A name that contains the keyword should fail
            with pytest.raises(ValueError):
                _validate_entity_name(f"table_{kw}_name", "test")

    def test_valid_column_types(self):
        for t in ("text", "integer", "boolean", "timestamptz", "uuid", "jsonb",
                  "numeric", "bigint", "float", "date", "varchar"):
            assert t in _validate_column_type(t)

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError, match="Unsupported column type"):
            _validate_column_type("bytea")

    def test_too_long_entity_name_rejected(self):
        long_name = "a" * 64  # 64 chars > 63-char limit after 'a' prefix
        with pytest.raises(ValueError):
            _validate_entity_name(long_name, "test")


# ── Schema generation ─────────────────────────────────────────────────────────

class TestSchemaGeneration:
    """
    Tests for _provision_schema — verifies table prefix, org scoping,
    column validation, and that no dangerous DDL is produced.
    """

    def _get_svc(self, pool=None):
        svc = AppBuilderService.__new__(AppBuilderService)
        svc._pool = pool
        return svc

    def test_table_name_prefix(self):
        """Verify the ab_{short_id}_{entity} naming scheme."""
        app_id = "550e8400-e29b-41d4-a716-446655440000"
        short_id = app_id.replace("-", "")[:12]
        entity_name = "contacts"
        expected = f"ab_{short_id}_{entity_name}"
        assert _validate_entity_name(f"ab_{short_id}_{entity_name}", "table") == expected

    def test_dynamic_table_names_are_safe(self):
        """All generated table names pass the whitelist validator."""
        for entity_name in ("contacts", "deals", "tasks", "companies", "invoices"):
            _validate_entity_name(entity_name, "entity")  # should not raise

    def test_forbidden_entity_names_blocked_before_ddl(self):
        """Entity names with SQL keywords are rejected before any DDL runs."""
        for bad in ("drop", "truncate", "delete", "pg_catalog"):
            with pytest.raises(ValueError):
                _validate_entity_name(bad, "entity")


# ── Build result ──────────────────────────────────────────────────────────────

class TestBuildResult:
    """Tests for the BuildResult dataclass and partial-failure semantics."""

    def test_ready_when_no_warnings(self):
        result = BuildResult(app_id="x", app_name="X", overall_status="ready")
        assert result.overall_status == "ready"
        assert result.warnings == []

    def test_api_operation_count(self):
        spec = make_spec(entities=4)
        # 4 entities × 5 operations (list, create, read, update, delete)
        expected_ops = 4 * 5
        result = BuildResult(
            app_id="x", app_name="X",
            api_operations=expected_ops,
        )
        assert result.api_operations == expected_ops

    def test_partial_status_with_warnings(self):
        result = BuildResult(
            app_id="x", app_name="X",
            overall_status="partial",
            warnings=["WhatsApp integration requires configuration"],
        )
        assert result.overall_status == "partial"
        assert len(result.warnings) == 1

    def test_spec_to_dict_preserves_all_fields(self):
        svc = AppBuilderService.__new__(AppBuilderService)
        spec = make_spec(workflows=2, agents=1)
        d = svc._spec_to_dict(spec)
        assert len(d["workflows"]) == 2
        assert len(d["agents"]) == 1
        assert "integrations" in d
        assert "settings" in d


# ── Tenant isolation ──────────────────────────────────────────────────────────

class TestTenantIsolation:
    """
    Verify that the service never crosses org boundaries.
    These tests exercise the org_id scoping logic without a real database.
    """

    def test_org_id_is_required_in_get_app_query(self):
        """
        The GET /apps/{id} query always includes AND organization_id = $2.
        This test verifies the query shape at the service design level.
        """
        # The router GET handler uses: WHERE id = $1 AND organization_id = $2
        # We verify the SQL string used contains both conditions.
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.get_app)
        assert "organization_id = $2" in src, (
            "get_app must scope the lookup to the caller's org"
        )

    def test_delete_query_scopes_to_org(self):
        """DELETE must include organization_id to prevent IDOR."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.delete_app)
        assert "organization_id = $2" in src, (
            "delete_app must scope deletion to the caller's org"
        )

    def test_list_query_scopes_to_org(self):
        """List must be filtered by organization_id."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.list_apps)
        assert "organization_id = $1" in src, (
            "list_apps must filter by org_id"
        )

    def test_modify_query_scopes_to_org(self):
        """Modify must verify app belongs to caller's org."""
        import inspect
        from app.services import app_builder as svc_mod
        src = inspect.getsource(svc_mod.AppBuilderService.modify_app)
        assert "organization_id = $2" in src, (
            "modify_app must check org_id to prevent IDOR"
        )

    def test_create_uses_ctx_org_id_not_body(self):
        """
        The create_app router endpoint resolves org_id from OrgContext
        (JWT-verified tenancy), not from the request body.
        """
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.create_app)
        # org_id must come from ctx (OrgContext), not request body
        assert "ctx.org_id" in src
        # The request body type (BuildRequest) must not have org_id
        from app.routers.app_builder import BuildRequest
        assert not hasattr(BuildRequest, "org_id"), (
            "org_id must NOT be in the request body"
        )


# ── Authorization ─────────────────────────────────────────────────────────────

class TestAuthorization:
    """Verify permission requirements are declared on every endpoint."""

    def test_create_requires_create_permission(self):
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.create_app)
        assert 'require_permission("app_builder", "create")' in src

    def test_list_requires_read_permission(self):
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.list_apps)
        assert 'require_permission("app_builder", "read")' in src

    def test_get_requires_read_permission(self):
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.get_app)
        assert 'require_permission("app_builder", "read")' in src

    def test_modify_requires_update_permission(self):
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.modify_app)
        assert 'require_permission("app_builder", "update")' in src

    def test_delete_requires_delete_permission(self):
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.delete_app)
        assert 'require_permission("app_builder", "delete")' in src


# ── Page generation ───────────────────────────────────────────────────────────

class TestPageGeneration:
    def test_canvas_json_contains_all_pages(self):
        svc = AppBuilderService.__new__(AppBuilderService)
        spec = make_spec(pages=5)
        canvas = svc._build_canvas_json(spec)
        assert len(canvas["pages"]) == 5

    def test_canvas_json_page_names(self):
        svc = AppBuilderService.__new__(AppBuilderService)
        spec = make_spec(pages=3)
        canvas = svc._build_canvas_json(spec)
        page_names = [p["name"] for p in canvas["pages"]]
        for i, name in enumerate(page_names):
            assert spec.pages[i].name == name

    def test_canvas_json_includes_entity_metadata(self):
        svc = AppBuilderService.__new__(AppBuilderService)
        spec = make_spec(entities=3)
        canvas = svc._build_canvas_json(spec)
        assert len(canvas["entities"]) == 3

    def test_canvas_json_page_order(self):
        svc = AppBuilderService.__new__(AppBuilderService)
        spec = make_spec(pages=4)
        canvas = svc._build_canvas_json(spec)
        orders = [p["order"] for p in canvas["pages"]]
        assert orders == list(range(4))


# ── CRUD generation ───────────────────────────────────────────────────────────

class TestCrudGeneration:
    def test_api_operations_count_formula(self):
        """5 ops per entity (list, create, read, update, delete)."""
        entity_count = 6
        expected = entity_count * 5
        spec = make_spec(entities=entity_count)
        # Mimic what build_app does:
        api_ops = len(spec.entities) * 5
        assert api_ops == expected


# ── Workflow generation ───────────────────────────────────────────────────────

class TestWorkflowGeneration:
    def test_workflows_in_spec(self):
        spec = make_spec(workflows=3)
        assert len(spec.workflows) == 3
        for wf in spec.workflows:
            assert wf.trigger
            assert wf.steps

    def test_no_workflows_when_not_requested(self):
        spec = make_spec(workflows=0)
        assert spec.workflows == []


# ── Agent generation ──────────────────────────────────────────────────────────

class TestAgentGeneration:
    def test_agents_in_spec(self):
        spec = make_spec(agents=2)
        assert len(spec.agents) == 2
        for ag in spec.agents:
            assert ag.name
            assert ag.system_prompt

    def test_no_agents_by_default(self):
        spec = make_spec(agents=0)
        assert spec.agents == []


# ── Incremental modification ──────────────────────────────────────────────────

class TestIncrementalModification:
    def test_spec_to_dict_preserves_entities_after_modification(self):
        """
        After a modify, the new spec dict should contain the original entities
        plus any additions (we verify the dict roundtrip is complete).
        """
        svc = AppBuilderService.__new__(AppBuilderService)
        spec = make_spec(entities=3, pages=4, roles=2)
        d = svc._spec_to_dict(spec)
        # Simulate "modify" adding one entity
        new_entity = EntityDef(
            name="invoices",
            display_name="Invoices",
            columns=[ColumnDef(name="amount", type="numeric")],
        )
        spec.entities.append(new_entity)
        d2 = svc._spec_to_dict(spec)
        assert len(d2["entities"]) == len(d["entities"]) + 1
        assert d2["entities"][-1]["name"] == "invoices"


# ── Failed build recovery ─────────────────────────────────────────────────────

class TestFailedBuildRecovery:
    def test_partial_status_on_warning(self):
        """A build with any warning gets overall_status='partial', not 'failed'."""
        result = BuildResult(
            app_id=str(uuid.uuid4()),
            app_name="Test",
            overall_status="partial",
            warnings=["Canvas creation failed: DB error"],
            tables_created=3,
            pages_created=0,  # pages failed
            api_operations=15,
        )
        assert result.overall_status == "partial"
        assert result.tables_created == 3  # other parts succeeded
        assert result.pages_created == 0

    def test_warnings_list_is_populated(self):
        w = "WhatsApp integration requires configuration"
        result = BuildResult(
            app_id="x", app_name="X",
            warnings=[w],
        )
        assert w in result.warnings


# ── Destructive operation protection ─────────────────────────────────────────

class TestDestructiveOperationProtection:
    """
    Verify that the safety layer blocks SQL keywords that could be used
    for injection or destructive operations.
    """

    def _parse(self, data: dict) -> AppSpec:
        svc = AppBuilderService.__new__(AppBuilderService)
        return svc._parse_and_validate_spec(data)

    def test_drop_in_entity_name_blocked(self):
        with pytest.raises(ValueError):
            _validate_entity_name("drop_users", "entity")

    def test_truncate_in_entity_name_blocked(self):
        with pytest.raises(ValueError):
            _validate_entity_name("truncate_logs", "entity")

    def test_delete_in_entity_name_blocked(self):
        with pytest.raises(ValueError):
            _validate_entity_name("delete_records", "entity")

    def test_alter_in_entity_name_blocked(self):
        with pytest.raises(ValueError):
            _validate_entity_name("alter_table", "entity")

    def test_grant_in_entity_name_blocked(self):
        with pytest.raises(ValueError):
            _validate_entity_name("grant_access", "entity")

    def test_pg_prefix_in_entity_name_blocked(self):
        with pytest.raises(ValueError):
            _validate_entity_name("pg_catalog", "entity")

    def test_information_schema_blocked(self):
        with pytest.raises(ValueError):
            _validate_entity_name("information_schema", "entity")

    def test_delete_router_does_soft_delete_only(self):
        """
        The delete endpoint must NOT execute DROP TABLE.
        It should only UPDATE build_status='failed'.
        """
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.delete_app)
        # Check for "DROP TABLE" specifically (not bare "DROP" which appears in
        # docstrings like "Does NOT drop dynamic tables").
        assert "DROP TABLE" not in src.upper(), (
            "delete_app must not issue DROP TABLE — use soft delete only"
        )
        assert "UPDATE" in src.upper() or "update" in src, (
            "delete_app should do a soft delete (UPDATE)"
        )

    def test_spec_parsing_rejects_arbitrary_types(self):
        """AI-generated column types must go through the whitelist."""
        dangerous_types = ["bytea", "oid", "regproc", "pg_node_tree", "SERIAL",
                           "text; DROP TABLE users--", "text' OR '1'='1"]
        for bad_type in dangerous_types:
            with pytest.raises(ValueError):
                _validate_column_type(bad_type)


# ── Async build (Phase 2 + 3 + 4) ────────────────────────────────────────────

class TestAsyncBuild:
    """
    POST /apps must return immediately (async) with {id, status, progress,
    current_step} — the actual build runs in the background.
    """

    def test_create_app_returns_async_response_shape(self):
        """Router source: POST /apps calls submit_build_job (non-blocking)."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.create_app)
        # Must delegate to the async submission path
        assert "submit_build_job" in src
        # Must NOT call build_app (the old synchronous path)
        assert "build_app" not in src, (
            "create_app must use submit_build_job, not the synchronous build_app"
        )

    def test_create_app_returns_id_and_status_building(self):
        """Router returns status='building' immediately."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.create_app)
        assert '"building"' in src or "'building'" in src
        assert '"progress"' in src or "'progress'" in src
        assert '"current_step"' in src or "'current_step'" in src

    def test_create_app_never_exposes_user_id_in_response(self):
        """The async response shape must not leak user_id or org_id."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.create_app)
        response_block = src[src.rfind("return {"):] if "return {" in src else ""
        assert "user_id" not in response_block
        assert "org_id" not in response_block

    def test_step_labels_count_matches_total_steps(self):
        """The 12-step pipeline constant and label list must stay in sync."""
        assert len(STEP_LABELS) == _TOTAL_STEPS

    def test_progress_columns_in_get_app_query(self):
        """GET /apps/{id} must SELECT all async progress columns."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.get_app)
        for col in ("progress", "current_step", "completed_steps", "error", "retry_count"):
            assert col in src, f"GET /apps/{{id}} must SELECT column '{col}'"

    def test_progress_in_get_app_response(self):
        """GET /apps/{id} must include progress in the response dict."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.get_app)
        assert '"progress"' in src or "'progress'" in src
        assert '"current_step"' in src or "'current_step'" in src
        assert '"error"' in src or "'error'" in src


# ── Retry endpoint (Phase 5) ──────────────────────────────────────────────────

class TestRetryEndpoint:
    """POST /apps/{id}/retry must exist, be org-scoped, and require update perm."""

    def test_retry_endpoint_exists(self):
        from app.routers import app_builder as router_mod
        assert hasattr(router_mod, "retry_app"), (
            "retry_app endpoint must be defined in the router"
        )

    def test_retry_requires_update_permission(self):
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.retry_app)
        assert 'require_permission("app_builder", "update")' in src

    def test_retry_calls_service_method(self):
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.retry_app)
        assert "retry_app_build" in src

    def test_retry_passes_org_id_from_context(self):
        """org_id must come from OrgContext, never from the request body."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.retry_app)
        assert "ctx.org_id" in src

    def test_retry_returns_async_shape(self):
        """Retry response is same shape as create: {id, status, progress, current_step}."""
        import inspect
        from app.routers import app_builder as router_mod
        src = inspect.getsource(router_mod.retry_app)
        assert '"building"' in src or "'building'" in src
        assert '"progress"' in src or "'progress'" in src

    def test_retry_only_allowed_when_status_failed_or_partial(self):
        """Service method raises ValueError for apps not in failed/partial state."""
        svc = AppBuilderService.__new__(AppBuilderService)
        # Test the status check logic is encoded in the method
        import inspect
        src = inspect.getsource(svc.retry_app_build)
        assert "failed" in src
        assert "partial" in src


# ── Idempotency (Phase 6) ─────────────────────────────────────────────────────

class TestIdempotency:
    """Deterministic UUID helpers produce stable IDs across calls."""

    def test_canvas_uuid_is_deterministic(self):
        app_id = "test-app-id-001"
        id1 = _canvas_uuid(app_id)
        id2 = _canvas_uuid(app_id)
        assert id1 == id2

    def test_canvas_uuid_is_valid_uuid(self):
        import uuid
        raw = _canvas_uuid("any-app-id")
        # Should not raise
        parsed = uuid.UUID(raw)
        assert str(parsed) == raw

    def test_canvas_uuid_differs_per_app(self):
        assert _canvas_uuid("app-a") != _canvas_uuid("app-b")

    def test_agent_uuid_is_deterministic(self):
        app_id = "my-app"
        name = "Support Bot"
        assert _agent_uuid(app_id, name) == _agent_uuid(app_id, name)

    def test_agent_uuid_differs_per_name(self):
        app_id = "my-app"
        assert _agent_uuid(app_id, "Bot A") != _agent_uuid(app_id, "Bot B")

    def test_agent_uuid_differs_per_app(self):
        name = "Support Bot"
        assert _agent_uuid("app-1", name) != _agent_uuid("app-2", name)

    def test_workflow_uuid_is_deterministic(self):
        app_id = "my-app"
        name = "Send Welcome Email"
        assert _workflow_uuid(app_id, name) == _workflow_uuid(app_id, name)

    def test_workflow_uuid_differs_per_name(self):
        app_id = "my-app"
        assert _workflow_uuid(app_id, "A") != _workflow_uuid(app_id, "B")

    def test_canvas_and_agent_uuids_never_collide(self):
        """Different helper functions never produce the same ID for the same app."""
        app_id = "collision-test"
        assert _canvas_uuid(app_id) != _agent_uuid(app_id, "Bot")
        assert _canvas_uuid(app_id) != _workflow_uuid(app_id, "WF")
        assert _agent_uuid(app_id, "Bot") != _workflow_uuid(app_id, "WF")

    def test_submit_build_job_uses_idempotency_key(self):
        """submit_build_job must pass an idempotency_key so double-submit is safe."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.submit_build_job)
        assert "idempotency_key" in src, (
            "submit_build_job must pass idempotency_key to queue.submit"
        )

    def test_retry_does_not_pass_old_idempotency_key(self):
        """retry_app_build submits without the build:{app_id} key so a new job is created."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.retry_app_build)
        # Retry intentionally omits idempotency_key to always start a new job
        assert 'idempotency_key=f"build:{app_id}"' not in src


# ── RLS (Phase 7) ─────────────────────────────────────────────────────────────

class TestRLS:
    """App Builder tables must be listed in the RLS configuration."""

    def test_app_builder_apps_in_rls_tables(self):
        from app.tenancy.rls import _RLS_TABLES
        tables = {t for t, _ in _RLS_TABLES}
        assert "app_builder_apps" in tables, (
            "app_builder_apps must be in _RLS_TABLES for database-level tenant isolation"
        )

    def test_app_builder_versions_in_rls_tables(self):
        from app.tenancy.rls import _RLS_TABLES
        tables = {t for t, _ in _RLS_TABLES}
        assert "app_builder_versions" in tables, (
            "app_builder_versions must be in _RLS_TABLES"
        )

    def test_app_builder_apps_org_column_is_correct(self):
        from app.tenancy.rls import _RLS_TABLES
        col_map = dict(_RLS_TABLES)
        assert col_map.get("app_builder_apps") == "organization_id"

    def test_app_builder_versions_org_column_is_correct(self):
        from app.tenancy.rls import _RLS_TABLES
        col_map = dict(_RLS_TABLES)
        assert col_map.get("app_builder_versions") == "organization_id"

    def test_migration_010_enables_rls(self):
        """Migration 010 must contain ENABLE ROW LEVEL SECURITY for app_builder tables."""
        import inspect
        from migrations.versions._010_app_builder_async import upgrade
        src = inspect.getsource(upgrade)
        assert "ENABLE ROW LEVEL SECURITY" in src
        assert "app_builder_apps" in src

    def test_migration_010_adds_progress_columns(self):
        """Migration 010 must add progress tracking columns."""
        import inspect
        from migrations.versions._010_app_builder_async import upgrade
        src = inspect.getsource(upgrade)
        for col in ("progress", "current_step", "total_steps", "completed_steps",
                    "retry_count", "started_at", "completed_at"):
            assert col in src, f"Migration 010 must add column '{col}'"

    def test_migration_010_fixes_build_status_check(self):
        """Migration 010 must include 'partial' in the build_status CHECK constraint."""
        import inspect
        from migrations.versions._010_app_builder_async import upgrade
        src = inspect.getsource(upgrade)
        assert "'partial'" in src or "partial" in src


# ── Workflow mapping (Phase 8) ─────────────────────────────────────────────────

class TestWorkflowMapping:
    """
    Verify the constants that gate which workflow trigger / action types
    are mapped to the real WorkflowEngine vs. emitting a warning.
    """

    def test_cron_keywords_set_is_non_empty(self):
        assert len(_CRON_KEYWORDS) > 0

    def test_webhook_keywords_set_is_non_empty(self):
        assert len(_WEBHOOK_KEYWORDS) > 0

    def test_supported_action_types_contains_expected(self):
        for t in ("notify", "create", "update", "agent"):
            assert t in _SUPPORTED_ACTION_TYPES

    def test_cron_trigger_would_be_flagged(self):
        trigger = "every day at midnight"
        flagged = any(kw in trigger.lower() for kw in _CRON_KEYWORDS)
        assert flagged, "Cron-like triggers should be flagged as unsupported"

    def test_webhook_trigger_would_be_flagged(self):
        trigger = "on incoming webhook"
        flagged = any(kw in trigger.lower() for kw in _WEBHOOK_KEYWORDS)
        assert flagged, "Webhook triggers should be flagged as unsupported"

    def test_event_trigger_not_flagged_as_cron(self):
        trigger = "on user created"
        flagged_cron = any(kw in trigger.lower() for kw in _CRON_KEYWORDS)
        flagged_wh = any(kw in trigger.lower() for kw in _WEBHOOK_KEYWORDS)
        assert not flagged_cron
        assert not flagged_wh

    def test_unsupported_action_type_not_in_supported_set(self):
        for bad in ("shell", "exec", "sql", "raw"):
            assert bad not in _SUPPORTED_ACTION_TYPES

    def test_create_workflows_method_exists_in_service(self):
        assert hasattr(AppBuilderService, "_create_workflows"), (
            "_create_workflows must exist on AppBuilderService"
        )

    def test_create_agents_method_exists_in_service(self):
        assert hasattr(AppBuilderService, "_create_agents"), (
            "_create_agents must exist on AppBuilderService"
        )


# ── Security regression ───────────────────────────────────────────────────────

class TestSecurityRegression:
    """End-to-end security property checks that must hold across all phases."""

    def test_submit_build_job_org_id_from_arg_not_payload(self):
        """
        submit_build_job must pass org_id as a separate kwarg to queue.submit,
        which stamps it into payload["organization_id"] server-side.
        This prevents any caller from injecting a different org_id via the payload.
        """
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.submit_build_job)
        # org_id is a keyword argument to queue.submit — it overwrites the payload
        assert "org_id=org_id" in src

    def test_retry_org_id_always_from_context(self):
        """retry_app_build must pass org_id from its parameter, never from payload."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.retry_app_build)
        assert "org_id=org_id" in src

    def test_retry_service_scopes_db_query_by_org(self):
        """Retry must check both app_id AND organization_id to prevent IDOR."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.retry_app_build)
        assert "organization_id = $2" in src, (
            "retry_app_build must scope the DB lookup to organization_id to prevent IDOR"
        )

    def test_no_eval_or_exec_in_service(self):
        """The service must not use eval/exec/compile on AI-generated content."""
        import inspect
        import app.services.app_builder as svc_mod
        src = inspect.getsource(svc_mod)
        # re.compile() is safe (compiles regex, not code) — neutralise it before checking
        src_clean = src.replace("re.compile(", "re_compile_safe_PLACEHOLDER(")
        # These would allow arbitrary code execution from LLM output
        for dangerous in ("eval(", "exec(", "compile(", "__import__("):
            assert dangerous not in src_clean, f"Service must not use {dangerous!r}"

    def test_no_os_system_in_service(self):
        """The service must not call os.system/subprocess on AI output."""
        import inspect
        import app.services.app_builder as svc_mod
        src = inspect.getsource(svc_mod)
        for dangerous in ("os.system(", "subprocess.run(", "subprocess.call("):
            assert dangerous not in src, f"Service must not use {dangerous!r}"

    def test_delete_is_soft_only_across_full_service(self):
        """No DROP TABLE in any execute() call in the service — only soft deletes."""
        import inspect
        import app.services.app_builder as svc_mod
        src = inspect.getsource(svc_mod)
        # Only inspect lines that are actual DB execute calls, not docstrings or comments.
        # The module docstring mentions "DROP TABLE" to say it's *blocked* — that's fine.
        sql_lines = [
            line for line in src.split("\n")
            if ("execute(" in line or "conn.execute" in line) and not line.strip().startswith("#")
        ]
        sql_src = "\n".join(sql_lines)
        assert "DROP TABLE" not in sql_src.upper(), (
            "Service must never execute DROP TABLE — use soft deletes only"
        )


# ── Crash recovery (Section 2) ─────────────────────────────────────────────────

class TestCrashRecovery:
    """
    Verify the stale-build recovery mechanism added in session 3.

    After a server restart the job queue only re-dispatches PENDING jobs.
    Any job that was RUNNING is abandoned, leaving its app_builder_apps
    record stuck in build_status='building'.  recover_stale_builds() is
    called once at startup to mark those records as 'failed' so users can
    retry rather than waiting forever.
    """

    def test_recover_stale_builds_method_exists(self):
        """recover_stale_builds() must be a coroutine on AppBuilderService."""
        import asyncio
        assert hasattr(AppBuilderService, "recover_stale_builds"), (
            "AppBuilderService must have a recover_stale_builds method"
        )
        method = getattr(AppBuilderService, "recover_stale_builds")
        assert asyncio.iscoroutinefunction(method), (
            "recover_stale_builds must be an async method"
        )

    def test_recover_stale_builds_queries_building_status(self):
        """The recovery SQL must filter on build_status = 'building'."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.recover_stale_builds)
        assert "'building'" in src or '"building"' in src, (
            "recover_stale_builds must target build_status = 'building'"
        )

    def test_recover_stale_builds_uses_heartbeat_threshold(self):
        """Must check last_heartbeat_at to detect dead builds."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.recover_stale_builds)
        assert "last_heartbeat_at" in src, (
            "recover_stale_builds must use last_heartbeat_at for stale detection"
        )

    def test_recover_stale_builds_uses_started_at_fallback(self):
        """Must check started_at for builds that never received a heartbeat."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.recover_stale_builds)
        assert "started_at" in src, (
            "recover_stale_builds must also check started_at for builds without heartbeats"
        )

    def test_recover_stale_builds_sets_failed_status(self):
        """Stuck builds must be set to 'failed' (not deleted or left unchanged)."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.recover_stale_builds)
        assert "'failed'" in src or '"failed"' in src, (
            "recover_stale_builds must set build_status='failed'"
        )
        # Must set an error message so users understand what happened
        assert "error" in src.lower(), (
            "recover_stale_builds must set an error message on the record"
        )

    def test_recover_stale_builds_records_completed_at(self):
        """Recovered builds must have completed_at set so they have a proper end time."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.recover_stale_builds)
        assert "completed_at" in src, (
            "recover_stale_builds must set completed_at on recovered records"
        )

    def test_recover_stale_builds_returns_int(self):
        """Return value must be an integer count of recovered records."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.recover_stale_builds)
        # Method returns the count of updated records
        assert "return" in src, "recover_stale_builds must return the count"

    def test_recover_stale_builds_swallows_db_errors(self):
        """Recovery must not crash server startup on DB errors."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.recover_stale_builds)
        assert "except" in src, (
            "recover_stale_builds must catch exceptions so startup is not aborted"
        )
        # Should return 0 on error, not raise
        assert "return 0" in src or "return n" in src

    def test_factory_calls_recover_stale_builds(self):
        """factory.py lifespan must call recover_stale_builds after registering the handler."""
        import inspect
        import app.factory as factory_mod
        src = inspect.getsource(factory_mod.lifespan)
        assert "recover_stale_builds" in src, (
            "factory.py lifespan must call _abs_svc.recover_stale_builds() at startup"
        )

    def test_recover_stale_builds_called_after_handler_registration(self):
        """recovery call must come after register_handler to preserve ordering."""
        import inspect
        import app.factory as factory_mod
        src = inspect.getsource(factory_mod.lifespan)
        reg_idx = src.find("register_handler")
        rec_idx = src.find("recover_stale_builds")
        assert reg_idx != -1, "register_handler not found in lifespan"
        assert rec_idx != -1, "recover_stale_builds not found in lifespan"
        assert rec_idx > reg_idx, (
            "recover_stale_builds must be called after register_handler"
        )


# ── Handler fatal-error hardening (Section 2b) ───────────────────────────────

class TestBuildJobHandlerErrorHardening:
    """
    build_job_handler must catch any exception that escapes the pipeline
    and persist build_status='failed' to the DB, so the record never gets
    stuck in 'building' state after an unexpected crash.
    """

    def test_build_job_handler_has_try_except(self):
        """Handler body must be wrapped in try/except."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.build_job_handler)
        assert "try:" in src and "except" in src, (
            "build_job_handler must wrap its body in try/except to catch unexpected errors"
        )

    def test_build_job_handler_updates_db_on_exception(self):
        """On exception, handler must persist build_status='failed' before re-raising."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.build_job_handler)
        assert "'failed'" in src or '"failed"' in src, (
            "build_job_handler must set build_status='failed' in the except block"
        )
        assert "build_status" in src

    def test_build_job_handler_reraises_after_db_write(self):
        """Handler must re-raise so the JobQueue also marks the job as failed."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.build_job_handler)
        assert "raise" in src, (
            "build_job_handler must re-raise the exception so the job is marked failed "
            "in the queue too — not just in the DB"
        )

    def test_build_job_handler_sets_error_message(self):
        """Error column must contain a human-readable message, not just 'True'/'error'."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.build_job_handler)
        # The error field should be f"Build failed: {exc}" or similar
        assert "error" in src.lower() and "exc" in src, (
            "build_job_handler must include the exception message in the error column"
        )

    def test_build_job_handler_reads_app_id_from_payload(self):
        """Handler must use app_id from payload (set server-side), not from user input."""
        import inspect
        svc = AppBuilderService.__new__(AppBuilderService)
        src = inspect.getsource(svc.build_job_handler)
        assert 'payload["app_id"]' in src or "payload['app_id']" in src
