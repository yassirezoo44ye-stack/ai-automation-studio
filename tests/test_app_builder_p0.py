"""
P0 App Builder Integration Tests

P0-A  Connect AppSpec to the existing code-gen build path
P0-B  Replace fake API generation with real CRUD route stubs
P0-C  Fix false runtime states (READY / PREVIEW / RUNNING / STOPPED / ERROR)

Tests:
  AB-P0-01  _build_prompt_with_spec injects spec inside <validated_app_spec> tags
  AB-P0-02  _build_prompt_with_spec returns raw prompt when spec_context is empty
  AB-P0-03  _build_prompt_with_spec preserves the original prompt verbatim
  AB-P0-04  _generate_crud_routes returns required top-level keys
  AB-P0-05  _generate_crud_routes produces exactly 5 ops per entity
  AB-P0-06  _generate_crud_routes total_entities matches spec entity count
  AB-P0-07  _generate_crud_routes encodes LIST route with org_id WHERE clause
  AB-P0-08  _generate_crud_routes encodes IDOR guard in READ route
  AB-P0-09  _generate_crud_routes encodes IDOR guard in UPDATE route
  AB-P0-10  _generate_crud_routes encodes IDOR guard in DELETE route
  AB-P0-11  _generate_crud_routes table name includes short app_id and entity name
  AB-P0-12  _generate_crud_routes "routes" list has all 5 HTTP verbs
  AB-P0-13  Step 3 in _run_build_pipeline uses _generate_crud_routes (structural)
  AB-P0-14  Step 3 no longer uses the fake len(entities)*5 expression (structural)
  AB-P0-15  RuntimePanel.tsx exports "preview" in RuntimeState union
  AB-P0-16  AppBuilderPage.tsx sets runtimeState to "preview" on html SSE event
  AB-P0-17  AppSidebar "Live" badge is conditional on runtimeState (P0-C structural)
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _src(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _parse(rel: str) -> ast.Module:
    return ast.parse(_src(rel))


def _make_spec(n_entities: int = 2) -> "SimpleNamespace":
    """Build a minimal AppSpec-like namespace for unit-testing _generate_crud_routes."""
    entities = []
    for i in range(n_entities):
        col = SimpleNamespace(name=f"field_{i}", type="text")
        entity = SimpleNamespace(
            name=f"entity_{i}",
            display_name=f"Entity {i}",
            columns=[col],
        )
        entities.append(entity)
    return SimpleNamespace(
        name="Test App",
        entities=entities,
        pages=[SimpleNamespace(name="Dashboard")],
        roles=[SimpleNamespace(name="admin")],
    )


# ── P0-A: _build_prompt_with_spec ─────────────────────────────────────────────

def test_spec_injection_wraps_in_xml_tags():
    """AB-P0-01: spec context is wrapped in <validated_app_spec> XML."""
    from app.routers.build import _build_prompt_with_spec
    spec_ctx = '{"entities": []}'
    result = _build_prompt_with_spec("Build a CRM", spec_ctx)
    assert "<validated_app_spec>" in result
    assert "</validated_app_spec>" in result
    assert spec_ctx in result


def test_spec_injection_empty_returns_raw_prompt():
    """AB-P0-02: empty spec_context returns the prompt unchanged."""
    from app.routers.build import _build_prompt_with_spec
    prompt = "Build an HR portal"
    assert _build_prompt_with_spec(prompt, "") == prompt


def test_spec_injection_preserves_original_prompt():
    """AB-P0-03: original prompt text appears in injected output."""
    from app.routers.build import _build_prompt_with_spec
    prompt = "Build a booking system for a clinic"
    result = _build_prompt_with_spec(prompt, '{"entities": []}')
    assert prompt in result


# ── P0-B: _generate_crud_routes ──────────────────────────────────────────────

def test_crud_routes_returns_required_keys():
    """AB-P0-04: return dict has routers, total_operations, total_entities."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(2)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    assert "routers" in result
    assert "total_operations" in result
    assert "total_entities" in result


def test_crud_routes_five_ops_per_entity():
    """AB-P0-05: exactly 5 operations per entity."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(3)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    assert result["total_operations"] == 15  # 3 entities × 5 ops
    for router in result["routers"]:
        assert router["operations"] == 5


def test_crud_routes_total_entities():
    """AB-P0-06: total_entities matches spec entity count."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(4)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    assert result["total_entities"] == 4


def test_crud_routes_list_has_org_id_where():
    """AB-P0-07: LIST route enforces organization_id in WHERE clause."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(1)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    code = result["routers"][0]["code"]
    assert "organization_id" in code
    assert "WHERE" in code or "where" in code.lower()


def test_crud_routes_read_has_idor_guard():
    """AB-P0-08: READ route checks both organization_id and item id."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(1)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    code = result["routers"][0]["code"]
    # The SELECT must check BOTH org and item id to prevent IDOR
    assert "organization_id" in code
    assert "item_id" in code or "id=$2" in code or "id = $2" in code


def test_crud_routes_update_has_idor_guard():
    """AB-P0-09: UPDATE route checks organization_id to prevent cross-tenant writes."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(1)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    code = result["routers"][0]["code"]
    assert "UPDATE" in code
    assert "organization_id" in code


def test_crud_routes_delete_has_idor_guard():
    """AB-P0-10: DELETE route checks organization_id to prevent cross-tenant deletes."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(1)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    code = result["routers"][0]["code"]
    assert "DELETE" in code
    assert "organization_id" in code


def test_crud_routes_table_name_format():
    """AB-P0-11: table name is ab_{short_app_id}_{entity_name}."""
    from app.services.app_builder import _generate_crud_routes
    app_id = "test1234-aaaa-bbbb-cccc-ddddeeeeffffgg"
    spec = _make_spec(1)
    result = _generate_crud_routes(app_id, spec)
    short_id = app_id.replace("-", "")[:8]
    entity_name = spec.entities[0].name
    expected_table = f"ab_{short_id}_{entity_name}"
    assert result["routers"][0]["table"] == expected_table
    assert expected_table in result["routers"][0]["code"]


def test_crud_routes_five_http_verbs():
    """AB-P0-12: each router entry lists all 5 CRUD verb names."""
    from app.services.app_builder import _generate_crud_routes
    spec = _make_spec(1)
    result = _generate_crud_routes("aaaabbbb-cccc-dddd-eeee-ffffffffffff", spec)
    routes = result["routers"][0]["routes"]
    for verb in ("LIST", "CREATE", "READ", "UPDATE", "DELETE"):
        assert verb in routes, f"Missing {verb!r} in routes list"


def test_step3_uses_generate_crud_routes():
    """AB-P0-13: _run_build_pipeline Step 3 calls _generate_crud_routes (structural)."""
    src = _src("app/services/app_builder.py")
    assert "_generate_crud_routes" in src, (
        "_generate_crud_routes must be called in app_builder.py Step 3"
    )
    # Verify it is referenced inside the pipeline function (not just defined)
    tree = _parse("app/services/app_builder.py")
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_generate_crud_routes"
    ]
    assert len(calls) >= 1, "_generate_crud_routes must be called at least once"


def test_step3_no_longer_fake():
    """AB-P0-14: Step 3 does not use the bare ``len(spec.entities) * 5`` expression."""
    src = _src("app/services/app_builder.py")
    # The fake line was:  result.api_operations = len(spec.entities) * 5  # list, create...
    # After P0-B it must not appear as the primary (non-fallback) assignment.
    # We allow it in comments and in exception handlers (fallback), but the
    # main (non-exception) path must go through _generate_crud_routes.
    # Simple check: the old verbatim fake line is gone.
    assert 'result.api_operations = len(spec.entities) * 5  # list, create, read, update, delete' not in src, (
        "The fake 'len(spec.entities) * 5' line must be removed from the main Step 3 path"
    )


# ── P0-C: Runtime state / badge ──────────────────────────────────────────────

def test_runtime_state_includes_preview():
    """AB-P0-15: RuntimePanel.tsx RuntimeState union includes 'preview'."""
    src = _src("src/renderer/features/app-builder/components/RuntimePanel.tsx")
    assert '"preview"' in src, (
        'RuntimeState union in RuntimePanel.tsx must include "preview"'
    )


def test_html_event_sets_preview_not_running():
    """AB-P0-16: the html SSE event handler sets runtimeState to 'preview', not 'running'."""
    src = _src("src/renderer/features/app-builder/AppBuilderPage.tsx")
    # Find the case "html": block and verify it sets "preview"
    # The block is identifiable by the Blob creation on the next line
    html_block_idx = src.find('case "html":')
    assert html_block_idx != -1, 'case "html": not found in AppBuilderPage.tsx'
    # Extract ~300 chars after the case label
    html_block = src[html_block_idx: html_block_idx + 400]
    assert 'setRuntimeState("preview")' in html_block, (
        'html SSE handler must call setRuntimeState("preview"), not "running"'
    )
    assert 'setRuntimeState("running")' not in html_block, (
        'html SSE handler must NOT call setRuntimeState("running") — that is a false state'
    )


def test_live_badge_conditional_on_runtime_state():
    """AB-P0-17: AppSidebar renders Live badge only when runtimeState === 'running'."""
    src = _src("src/renderer/features/app-builder/AppBuilderPage.tsx")
    # The badge must be inside a conditional on runtimeState
    # We check that the statusLive key appears near a runtimeState check
    live_badge_idx = src.find('statusLive')
    assert live_badge_idx != -1, 'statusLive key not found'
    # Look back up to 400 chars before statusLive for the conditional
    context_before = src[max(0, live_badge_idx - 400): live_badge_idx]
    assert 'runtimeState === "running"' in context_before, (
        'Live badge must be wrapped in runtimeState === "running" condition (P0-C)'
    )
    # And there must be a matching "preview" badge
    assert 'statusPreview' in src, (
        'AppBuilderPage.tsx must render statusPreview badge for the "preview" state'
    )
    assert 'runtimeState === "preview"' in src, (
        'AppBuilderPage.tsx must have runtimeState === "preview" condition for the preview badge'
    )
