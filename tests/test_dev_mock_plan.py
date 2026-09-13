"""
Tests for DevMockProvider plan-based multi-file generation.

Coverage:
  - _select_template routes to plan-based generator when <approved_plan> XML present
  - _build_from_plan produces correct files for a typical e-commerce plan
  - Plan with pages generates one JS file per page
  - Plan with db_tables generates data/schema.sql
  - Plan with api_routes generates api/routes.json
  - No plan → falls back to keyword-based templates (backward-compat)
  - build.py BuildRequest accepts optional plan field
  - _build_prompt_with_plan injects plan XML correctly
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _file_names(output: str) -> list[str]:
    """Extract all <<FILE: path>>> paths from a dev_mock output string."""
    return re.findall(r"<<<FILE: ([^>]+)>>>", output)


def _ecommerce_plan() -> dict:
    """A realistic plan for 'متجر إلكتروني' (e-commerce store)."""
    return {
        "name": "E-Commerce Store",
        "description": "An online store with product catalog and shopping cart",
        "tech_stack": {"frontend": "HTML/CSS/JS", "backend": "FastAPI", "database": "PostgreSQL"},
        "pages": ["Home", "Products", "Cart", "Checkout", "Orders"],
        "database_tables": ["products", "orders", "order_items", "customers"],
        "api_routes": ["/api/products", "/api/orders", "/api/cart"],
        "agents": ["Product Recommendation Agent"],
        "workflows": ["Order placed → Send confirmation email"],
        "integrations": ["Stripe", "SendGrid"],
        "complexity": "moderate",
        "estimated_files": 12,
    }


# ── _build_from_plan ──────────────────────────────────────────────────────────

class TestBuildFromPlan(unittest.TestCase):

    def test_ecommerce_plan_produces_minimum_7_files(self):
        """E-commerce plan must yield ≥ 7 files (prev: 2)."""
        from app.ai.providers.dev_mock import _build_from_plan
        result = _build_from_plan("متجر إلكتروني", _ecommerce_plan())
        files = _file_names(result)
        self.assertGreaterEqual(len(files), 7, f"Expected ≥7 files, got {len(files)}: {files}")

    def test_always_includes_required_files(self):
        """index.html, styles.css, app.js, README.md must always be present."""
        from app.ai.providers.dev_mock import _build_from_plan
        result = _build_from_plan("متجر إلكتروني", _ecommerce_plan())
        files = _file_names(result)
        for required in ("index.html", "styles.css", "app.js", "README.md"):
            self.assertIn(required, files, f"Missing required file: {required}")

    def test_one_js_file_per_page(self):
        """Each page in the plan should have a corresponding pages/<slug>.js."""
        from app.ai.providers.dev_mock import _build_from_plan
        plan = _ecommerce_plan()
        result = _build_from_plan("store", plan)
        files = _file_names(result)
        page_files = [f for f in files if f.startswith("pages/")]
        self.assertEqual(
            len(page_files), len(plan["pages"]),
            f"Expected {len(plan['pages'])} page files, got {len(page_files)}: {page_files}",
        )

    def test_db_tables_generate_schema_sql(self):
        """When db_tables present → data/schema.sql must be in output."""
        from app.ai.providers.dev_mock import _build_from_plan
        result = _build_from_plan("store", _ecommerce_plan())
        files = _file_names(result)
        self.assertIn("data/schema.sql", files)

    def test_schema_sql_contains_table_names(self):
        """data/schema.sql must contain CREATE TABLE for each db_table."""
        from app.ai.providers.dev_mock import _build_from_plan
        result = _build_from_plan("store", _ecommerce_plan())
        schema_match = re.search(
            r"<<<FILE: data/schema\.sql>>>([\s\S]*?)<<<ENDFILE>>>", result
        )
        self.assertIsNotNone(schema_match, "data/schema.sql block not found")
        schema_sql = schema_match.group(1)
        for table in _ecommerce_plan()["database_tables"]:
            self.assertIn(table.lower(), schema_sql.lower(), f"Table {table!r} not in schema.sql")

    def test_api_routes_generate_routes_json(self):
        """When api_routes present → api/routes.json must be in output."""
        from app.ai.providers.dev_mock import _build_from_plan
        result = _build_from_plan("store", _ecommerce_plan())
        files = _file_names(result)
        self.assertIn("api/routes.json", files)

    def test_routes_json_is_valid_json(self):
        """api/routes.json content must parse as valid JSON."""
        from app.ai.providers.dev_mock import _build_from_plan
        result = _build_from_plan("store", _ecommerce_plan())
        routes_match = re.search(
            r"<<<FILE: api/routes\.json>>>([\s\S]*?)<<<ENDFILE>>>", result
        )
        self.assertIsNotNone(routes_match, "api/routes.json block not found")
        routes_data = json.loads(routes_match.group(1))
        self.assertIn("routes", routes_data)
        self.assertGreater(len(routes_data["routes"]), 0)

    def test_no_db_tables_skips_schema(self):
        """Plan with empty db_tables must NOT produce data/schema.sql."""
        from app.ai.providers.dev_mock import _build_from_plan
        plan = {**_ecommerce_plan(), "database_tables": []}
        result = _build_from_plan("app", plan)
        files = _file_names(result)
        self.assertNotIn("data/schema.sql", files)

    def test_no_api_routes_skips_routes_json(self):
        """Plan with empty api_routes must NOT produce api/routes.json."""
        from app.ai.providers.dev_mock import _build_from_plan
        plan = {**_ecommerce_plan(), "api_routes": []}
        result = _build_from_plan("app", plan)
        files = _file_names(result)
        self.assertNotIn("api/routes.json", files)

    def test_meta_block_present_and_valid(self):
        """Output must end with a valid <<<META>>> block."""
        from app.ai.providers.dev_mock import _build_from_plan
        result = _build_from_plan("store", _ecommerce_plan())
        meta_match = re.search(r"<<<META>>>([\s\S]*?)<<<ENDMETA>>>", result)
        self.assertIsNotNone(meta_match, "META block not found")
        meta = json.loads(meta_match.group(1))
        self.assertIn("description", meta)
        self.assertEqual(meta.get("language"), "html")

    def test_plan_with_no_pages_defaults_to_home(self):
        """Plan with empty pages list must produce at least pages/home.js."""
        from app.ai.providers.dev_mock import _build_from_plan
        plan = {**_ecommerce_plan(), "pages": []}
        result = _build_from_plan("app", plan)
        files = _file_names(result)
        # Must produce at least one page file
        page_files = [f for f in files if f.startswith("pages/")]
        self.assertGreater(len(page_files), 0)


# ── _select_template: plan routing ───────────────────────────────────────────

class TestSelectTemplatePlanRouting(unittest.TestCase):

    def _plan_prompt(self, plan: dict, user_prompt: str = "ابنِ متجر إلكتروني") -> str:
        """Wrap a plan in the <approved_plan> XML that build.py generates."""
        return (
            f"<approved_plan>\n{json.dumps(plan)}\n</approved_plan>\n\n"
            f"Build this application: {user_prompt}"
        )

    def test_plan_prompt_triggers_plan_generator(self):
        """<approved_plan> XML in prompt must bypass keyword templates."""
        from app.ai.providers.dev_mock import _select_template
        result = _select_template(self._plan_prompt(_ecommerce_plan()))
        files = _file_names(result)
        # Must produce at least 7 files (not the old 2-file ecommerce template)
        self.assertGreaterEqual(len(files), 7, f"Got {len(files)} files: {files}")

    def test_no_plan_xml_falls_back_to_keyword(self):
        """Prompt without <approved_plan> must use keyword-based template."""
        from app.ai.providers.dev_mock import _select_template
        result = _select_template("ابنِ متجر إلكتروني")
        files = _file_names(result)
        # Old keyword template produces exactly 2 files
        self.assertEqual(len(files), 2, f"Expected 2 keyword-template files, got {len(files)}")
        self.assertIn("index.html", files)
        self.assertIn("README.md", files)

    def test_malformed_plan_json_falls_back_gracefully(self):
        """Malformed JSON inside <approved_plan> → fallback to keyword templates."""
        from app.ai.providers.dev_mock import _select_template
        bad_prompt = "<approved_plan>{not valid json}</approved_plan>\n\nمتجر إلكتروني"
        result = _select_template(bad_prompt)
        # Should still produce output (not crash)
        self.assertIn("<<<FILE:", result)

    def test_empty_plan_fields_produce_base_files(self):
        """Minimal plan (no pages/tables/routes) → at least 4 files."""
        from app.ai.providers.dev_mock import _select_template
        minimal_plan = {
            "name": "App", "description": "Test", "tech_stack": {},
            "pages": [], "database_tables": [], "api_routes": [],
            "agents": [], "workflows": [], "integrations": [],
            "complexity": "simple",
        }
        result = _select_template(self._plan_prompt(minimal_plan))
        files = _file_names(result)
        self.assertGreaterEqual(len(files), 4)


# ── BuildRequest plan field ───────────────────────────────────────────────────

class TestBuildRequestPlanField(unittest.TestCase):

    def test_plan_field_is_optional(self):
        """plan is optional — BuildRequest without plan must not raise."""
        from app.routers import build as build_mod
        req = build_mod.BuildRequest(project_id="pid", prompt="build something")
        self.assertIsNone(req.plan)

    def test_plan_field_accepts_dict(self):
        """plan field accepts an arbitrary dict."""
        from app.routers import build as build_mod
        plan = {"name": "Test", "pages": ["Home"]}
        req = build_mod.BuildRequest(project_id="pid", prompt="build", plan=plan)
        self.assertEqual(req.plan, plan)

    def test_no_org_id_field_still_absent(self):
        """Adding plan must not accidentally add org_id."""
        from app.routers import build as build_mod
        self.assertFalse(hasattr(build_mod.BuildRequest, "org_id"))

    def test_no_user_id_field_still_absent(self):
        """Adding plan must not accidentally add user_id."""
        from app.routers import build as build_mod
        self.assertFalse(hasattr(build_mod.BuildRequest, "user_id"))


# ── _build_prompt_with_plan ───────────────────────────────────────────────────

class TestBuildPromptWithPlan(unittest.TestCase):

    def test_returns_prompt_unchanged_when_no_plan(self):
        from app.routers import build as build_mod
        self.assertEqual(build_mod._build_prompt_with_plan("hello", None), "hello")
        self.assertEqual(build_mod._build_prompt_with_plan("hello", {}), "hello")

    def test_injects_plan_xml_when_plan_present(self):
        from app.routers import build as build_mod
        plan = {"name": "Store", "pages": ["Home"]}
        result = build_mod._build_prompt_with_plan("build me a store", plan)
        self.assertIn("<approved_plan>", result)
        self.assertIn("</approved_plan>", result)
        self.assertIn('"Store"', result)
        self.assertIn("build me a store", result)

    def test_injected_plan_is_valid_json(self):
        """The plan JSON inside the XML wrapper must be valid."""
        from app.routers import build as build_mod
        plan = {"name": "X", "pages": ["A", "B"]}
        result = build_mod._build_prompt_with_plan("prompt", plan)
        match = re.search(r"<approved_plan>\s*([\s\S]*?)\s*</approved_plan>", result)
        self.assertIsNotNone(match)
        parsed = json.loads(match.group(1))
        self.assertEqual(parsed["name"], "X")
        self.assertEqual(parsed["pages"], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
