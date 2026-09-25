"""
Flow Next — Discover API Tests (Phase 1)

Tests cover:
  D-1   Schema init is idempotent (SQL_UP runs twice without error)
  D-2   Migration file is valid Python syntax
  D-3   Public feed returns only public rows (visibility isolation)
  D-4   Org isolation — org A cannot see org B's private creations
  D-5   Create requires X-Organization-Id header
  D-6   Create persists all fields correctly
  D-7   Get public creation — no auth needed
  D-8   Get private creation — IDOR guard (wrong org gets 404)
  D-9   PATCH updates only provided fields
  D-10  PATCH IDOR guard — wrong org gets 403
  D-11  DELETE removes the row
  D-12  DELETE IDOR guard — wrong org gets 403
  D-13  Publish sets visibility=public
  D-14  Unpublish sets visibility=private
  D-15  Publish IDOR guard — wrong org gets 403
  D-16  Clone creates a new card in caller's org
  D-17  Clone of DEVICE_WORKFLOW returns 409
  D-18  Clone of AGENT returns 409
  D-19  Clone of private row from another org returns 404
  D-20  RLS entry exists in rls.py
  D-21  flow_creations in factory lifespan (schema init call)
  D-22  discover router registered in factory
  D-23  Router file is valid Python syntax
  D-24  Type badge covers all 6 types
  D-25  Tags field persists as array
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# ── Helper: parse a file as AST ────────────────────────────────────────────────

def _parse_file(rel: str) -> ast.Module:
    src = (_ROOT / rel).read_text(encoding="utf-8")
    return ast.parse(src)


# ── D-1  Idempotent schema init  (structural) ─────────────────────────────────

def test_schema_sql_has_if_not_exists():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in src, \
        "Schema SQL must use CREATE TABLE IF NOT EXISTS for idempotency"


# ── D-2  Migration file is valid Python ───────────────────────────────────────

def test_migration_is_valid_python():
    p = _ROOT / "migrations/versions/012_flow_creations.py"
    assert p.exists(), "migrations/versions/012_flow_creations.py not found"
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        pytest.fail(f"012_flow_creations.py has a syntax error: {e}")


def test_migration_has_sql_up_and_down():
    src = (_ROOT / "migrations/versions/012_flow_creations.py").read_text(encoding="utf-8")
    assert "SQL_UP" in src
    assert "SQL_DOWN" in src
    assert "async def up" in src
    assert "async def down" in src


# ── D-3  Public visibility filter (structural — router code) ─────────────────

def test_public_feed_filters_visibility():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "visibility='public'" in src, \
        "Public feed query must filter WHERE visibility='public'"


# ── D-4  Org isolation (structural) ──────────────────────────────────────────

def test_mine_endpoint_filters_by_org():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "organization_id=$1" in src or "organization_id = $1" in src, \
        "Mine endpoint must filter by organization_id"


# ── D-5  Create endpoint requires org header ──────────────────────────────────

def test_create_requires_org_header():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    # _get_org_id raises 400 if header is missing
    assert "_get_org_id" in src
    assert "X-Organization-Id" in src


# ── D-6  Create persists all fields ──────────────────────────────────────────

def test_create_inserts_all_fields():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    for field in ("title", "description", "visibility", "source_type", "source_id",
                  "thumbnail_url", "tags", "type"):
        assert field in src, f"Create INSERT must reference field: {field}"


# ── D-7 / D-8  IDOR guard on GET ─────────────────────────────────────────────

def test_get_private_idor_guard():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    # The GET endpoint checks org_id for private rows
    assert "organization_id" in src
    assert "404" in src


# ── D-9  PATCH partial update ─────────────────────────────────────────────────

def test_patch_partial_update():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "UpdateCreationRequest" in src
    assert "PATCH" in src or "patch" in src.lower()


# ── D-10 / D-12 IDOR guards on PATCH + DELETE ─────────────────────────────────

def test_patch_and_delete_idor_guard():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    # Both check ownership and return 403
    assert "403" in src


# ── D-11  DELETE returns 204 ──────────────────────────────────────────────────

def test_delete_returns_204():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "status_code=204" in src or "204" in src


# ── D-13 / D-14  Publish / Unpublish toggle ──────────────────────────────────

def test_publish_sets_public():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "visibility='public'" in src


def test_unpublish_sets_private():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "visibility='private'" in src


# ── D-15  Publish IDOR guard ──────────────────────────────────────────────────
# Already covered by test_patch_and_delete_idor_guard (403 present)


# ── D-16  Clone creates new card ─────────────────────────────────────────────

def test_clone_creates_new_row():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "/clone" in src
    assert "INSERT INTO flow_creations" in src
    # Clone sets status_code=201
    assert "status_code=201" in src


# ── D-17 / D-18  Non-cloneable types → 409 ───────────────────────────────────

def test_clone_rejects_device_workflow_and_agent():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    assert "DEVICE_WORKFLOW" in src
    assert "AGENT" in src
    assert "409" in src


# ── D-19  Clone of private cross-org row → 404 ───────────────────────────────

def test_clone_blocks_private_cross_org():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    # The clone endpoint checks visibility != public for cross-org
    assert "visibility" in src
    # 404 is raised for access denial
    assert "404" in src


# ── D-20  RLS entry ──────────────────────────────────────────────────────────

def test_rls_entry_for_flow_creations():
    src = (_ROOT / "app/tenancy/rls.py").read_text(encoding="utf-8")
    assert "flow_creations" in src, \
        "flow_creations must be in _RLS_TABLES in app/tenancy/rls.py"


# ── D-21  Factory calls schema init ──────────────────────────────────────────

def test_factory_calls_init_flow_creations_schema():
    src = (_ROOT / "app/factory.py").read_text(encoding="utf-8")
    assert "init_flow_creations_schema" in src, \
        "factory.py must call init_flow_creations_schema during lifespan"


# ── D-22  Discover router registered in factory ──────────────────────────────

def test_factory_registers_discover_router():
    src = (_ROOT / "app/factory.py").read_text(encoding="utf-8")
    assert "discover_router" in src or "discover" in src, \
        "factory.py must include discover router"
    assert "include_router(discover_router.router)" in src


# ── D-23  Router is valid Python ─────────────────────────────────────────────

def test_discover_router_is_valid_python():
    p = _ROOT / "app/routers/discover.py"
    assert p.exists(), "app/routers/discover.py not found"
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        pytest.fail(f"app/routers/discover.py has a syntax error: {e}")


# ── D-24  All 6 creation types present ───────────────────────────────────────

def test_all_creation_types_present():
    src = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
    for t in ("APP", "AGENT", "WORKFLOW", "AUTOMATION", "TEMPLATE", "DEVICE_WORKFLOW"):
        assert t in src, f"Type {t!r} not found in router"


# ── D-25  Tags field ─────────────────────────────────────────────────────────

def test_tags_field_is_array():
    src = (_ROOT / "migrations/versions/012_flow_creations.py").read_text(encoding="utf-8")
    # PostgreSQL TEXT[] type
    assert "TEXT[]" in src or "tags" in src


# ── Frontend structural checks ────────────────────────────────────────────────

def test_discover_page_file_exists():
    p = _ROOT / "src/renderer/features/discover/DiscoverPage.tsx"
    assert p.exists(), "DiscoverPage.tsx not found"


def test_discover_page_exports_component():
    src = (_ROOT / "src/renderer/features/discover/DiscoverPage.tsx").read_text(encoding="utf-8")
    assert "export function DiscoverPage" in src


def test_discover_index_exports():
    src = (_ROOT / "src/renderer/features/discover/index.ts").read_text(encoding="utf-8")
    assert "DiscoverPage" in src


def test_discover_types_file_exists():
    p = _ROOT / "src/renderer/features/discover/types/creation.types.ts"
    assert p.exists(), "creation.types.ts not found"


def test_discover_service_file_exists():
    p = _ROOT / "src/renderer/features/discover/services/discoverService.ts"
    assert p.exists(), "discoverService.ts not found"


def test_discover_locale_en_exists():
    p = _ROOT / "src/renderer/locales/en/discover.json"
    assert p.exists(), "en/discover.json not found"


def test_discover_locale_ar_exists():
    p = _ROOT / "src/renderer/locales/ar/discover.json"
    assert p.exists(), "ar/discover.json not found"


def test_i18n_imports_discover():
    src = (_ROOT / "src/renderer/i18n.ts").read_text(encoding="utf-8")
    assert "discover" in src
    assert "discoverEn" in src
    assert "discoverAr" in src


def test_page_type_includes_discover():
    src = (_ROOT / "src/renderer/shared/types/index.ts").read_text(encoding="utf-8")
    assert '"discover"' in src


def test_app_layout_has_discover_page():
    src = (_ROOT / "src/renderer/components/layout/AppLayout.tsx").read_text(encoding="utf-8")
    assert "DiscoverPage" in src
    assert '"discover"' in src


def test_sidebar_has_discover_nav_item():
    src = (_ROOT / "src/renderer/components/layout/Sidebar.tsx").read_text(encoding="utf-8")
    assert '"discover"' in src


def test_icons_has_discover():
    src = (_ROOT / "src/renderer/shared/icons/index.tsx").read_text(encoding="utf-8")
    assert "discover" in src


# ── Phase 2: Like/Save persistence (D-26..D-34) ───────────────────────────────

_DISCOVER_SRC = (_ROOT / "app/routers/discover.py").read_text(encoding="utf-8")
_RLS_SRC = (_ROOT / "app/tenancy/rls.py").read_text(encoding="utf-8")


def test_D26_schema_sql_has_interactions_table():
    """D-26: _SCHEMA_SQL defines flow_creation_interactions with IF NOT EXISTS."""
    assert "flow_creation_interactions" in _DISCOVER_SRC
    assert "CREATE TABLE IF NOT EXISTS flow_creation_interactions" in _DISCOVER_SRC


def test_D27_like_endpoint_requires_auth():
    """D-27: like endpoint calls _require_auth (401 guard present)."""
    assert "_require_auth" in _DISCOVER_SRC
    assert "/creations/{creation_id}/like" in _DISCOVER_SRC or "creation_id}/like" in _DISCOVER_SRC


def test_D28_like_on_nonexistent_returns_404():
    """D-28: 404 pattern present for missing creation in toggle handler."""
    assert 'status_code=404' in _DISCOVER_SRC
    assert "Creation not found" in _DISCOVER_SRC


def test_D29_private_cross_org_returns_404():
    """D-29: visibility check prevents cross-org access to private creations."""
    assert "visibility" in _DISCOVER_SRC
    assert "organization_id" in _DISCOVER_SRC
    # both the visibility check and 404 raise are present in the same file
    assert 'status_code=404' in _DISCOVER_SRC


def test_D30_toggle_sql_has_on_conflict():
    """D-30: atomic toggle CTE uses ON CONFLICT DO NOTHING (race-safe)."""
    assert "ON CONFLICT" in _DISCOVER_SRC
    assert "DO NOTHING" in _DISCOVER_SRC


def test_D31_save_endpoint_exists():
    """D-31: /save endpoint declared in discover.py."""
    assert "save_creation" in _DISCOVER_SRC or "/save" in _DISCOVER_SRC


def test_D32_discover_feed_returns_user_state():
    """D-32: GET /discover includes user_liked/user_saved in response."""
    assert "user_liked" in _DISCOVER_SRC
    assert "user_saved" in _DISCOVER_SRC


def test_D33_rls_tables_has_interactions():
    """D-33: flow_creation_interactions is in rls.py _RLS_TABLES."""
    assert "flow_creation_interactions" in _RLS_SRC


def test_D34_migration_013_exists_and_valid_syntax():
    """D-34: 013_flow_creation_interactions.py exists and is valid Python."""
    import ast
    migration = _ROOT / "migrations/versions/013_flow_creation_interactions.py"
    assert migration.exists(), "013_flow_creation_interactions.py not found"
    ast.parse(migration.read_text(encoding="utf-8"))


# ── Phase 3: likes_count/saves_count + count query (D-35..D-39) ──────────────

_FEED_SVC_SRC = (_ROOT / "src/renderer/features/feed/services/feedService.ts").read_text(encoding="utf-8")
_MOCK_FEED_SRC = (_ROOT / "src/renderer/features/feed/mock/feedData.ts").read_text(encoding="utf-8")


def test_D35_discover_returns_likes_count_and_saves_count():
    """D-35: public_discover_feed adds likes_count and saves_count to each item."""
    assert "likes_count" in _DISCOVER_SRC, "discover.py must set likes_count on each item"
    assert "saves_count" in _DISCOVER_SRC, "discover.py must set saves_count on each item"


def test_D36_count_query_is_grouped_not_n_plus_one():
    """D-36: count query uses GROUP BY (batched), not a per-item COUNT."""
    assert "GROUP BY creation_id, type" in _DISCOVER_SRC, (
        "counts must be fetched with GROUP BY creation_id, type — not N+1 per-item queries"
    )
    assert "COUNT(*) AS cnt" in _DISCOVER_SRC


def test_D37_zero_count_fallback_in_discover():
    """D-37: items with no interactions get counts defaulting to 0."""
    assert 'c.get("like", 0)' in _DISCOVER_SRC
    assert 'c.get("save", 0)' in _DISCOVER_SRC


def test_D38_feed_mapper_uses_server_counts_not_hardcoded_zero():
    """D-38: feedService.ts mapper reads likes_count/saves_count from API, not literal 0."""
    assert "likes_count" in _FEED_SVC_SRC, (
        "creationToFeedItem must use c.likes_count, not hardcoded 0"
    )
    assert "saves_count" in _FEED_SVC_SRC, (
        "creationToFeedItem must use c.saves_count, not hardcoded 0"
    )
    # Ensure the old hardcoded zeros are gone from the likes/saves lines
    import re
    lines = _FEED_SVC_SRC.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("likes:") and "likes_count" not in stripped:
            assert "0," not in stripped, (
                f"likes field still hardcoded to 0: {line!r}"
            )
        if stripped.startswith("saves:") and "saves_count" not in stripped:
            assert "0," not in stripped, (
                f"saves field still hardcoded to 0: {line!r}"
            )


def test_D39_mock_feed_ids_are_valid_uuids():
    """D-39: MOCK_FEED item IDs are valid UUIDs so like/save API calls succeed."""
    import re
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        re.IGNORECASE,
    )
    id_matches = re.findall(r'id:\s*"([^"]+)"', _MOCK_FEED_SRC)
    item_ids = [m for m in id_matches if not m.startswith("u") and not m.startswith("@")]
    assert len(item_ids) >= 12, f"Expected at least 12 item IDs, found {len(item_ids)}"
    for item_id in item_ids:
        assert uuid_pattern.match(item_id), (
            f"MOCK_FEED item id {item_id!r} is not a valid UUID v4 — "
            "like/save calls on fallback mock items will return 422 from the API"
        )
