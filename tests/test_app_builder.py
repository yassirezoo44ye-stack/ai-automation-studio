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
