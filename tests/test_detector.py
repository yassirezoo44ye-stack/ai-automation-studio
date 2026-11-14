"""
Tests for app.execution.detector — ProjectDetector.

Covers the detection priority order and the critical static-vs-node
disambiguation: a workspace that contains index.html + app.js must be
classified as html/static, NOT as a Node.js project.

Regression guard for: App Builder "Run Project" failure where the generated
app.js file caused the detector to route to the Node driver instead of the
static HTML driver, producing a spurious "Add package.json: npm init -y" error.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.execution.detector import detect, ProjectInfo


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_ws(files: dict[str, str]) -> Path:
    """Create a temp workspace with the given {relative_path: content} map."""
    tmp = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp


def _minimal_html(title: str = "App") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<div id="app"></div>
<script src="app.js"></script>
</body>
</html>"""


# ── Static HTML detection ─────────────────────────────────────────────────────

class TestStaticHtmlDetection(unittest.TestCase):

    def test_index_html_only(self):
        """index.html alone → html/static."""
        ws = _make_ws({"index.html": _minimal_html()})
        info = detect(ws)
        self.assertEqual(info.project_type, "html")
        self.assertEqual(info.run_strategy, "static")
        self.assertEqual(info.entry_point, "index.html")

    def test_index_html_with_app_js(self):
        """
        index.html + app.js → html/static.

        REGRESSION: before the fix, app.js caused the detector to return
        run_strategy='node', routing to the Node driver and failing with
        'package.json not found'.
        """
        ws = _make_ws({
            "index.html": _minimal_html(),
            "app.js": "document.getElementById('app').textContent = 'Hello';",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "static",
                         "index.html + app.js must be classified as static, not node")
        self.assertEqual(info.project_type, "html")

    def test_app_builder_full_output(self):
        """
        Exact App Builder output structure → html/static.

        Files: index.html, styles.css, app.js, pages/*.js,
               data/schema.sql, api/routes.json, README.md
        """
        ws = _make_ws({
            "index.html":             _minimal_html("متجر إلكتروني"),
            "styles.css":             "body { margin: 0; }",
            "app.js":                 "// main entry",
            "pages/home.js":          "// home page",
            "pages/products.js":      "// products page",
            "pages/cart.js":          "// cart page",
            "data/schema.sql":        "CREATE TABLE products (id SERIAL PRIMARY KEY);",
            "api/routes.json":        json.dumps({"routes": ["/api/products"]}),
            "README.md":              "# متجر إلكتروني",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "static",
                         f"App Builder output must be static, got {info.run_strategy!r}")
        self.assertEqual(info.project_type, "html")
        self.assertEqual(info.entry_point, "index.html")

    def test_index_html_with_index_js(self):
        """index.html + index.js (common bundle) → html/static."""
        ws = _make_ws({
            "index.html": _minimal_html(),
            "index.js":   "console.log('loaded');",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "static")

    def test_index_html_with_styles_only(self):
        """index.html + styles.css (no JS) → html/static."""
        ws = _make_ws({
            "index.html": _minimal_html(),
            "styles.css": "body { font-family: sans-serif; }",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "static")
        self.assertEqual(info.project_type, "html")

    def test_non_index_html_entry(self):
        """A .html file that is not index.html → still html/static."""
        ws = _make_ws({"app.html": _minimal_html("Other")})
        info = detect(ws)
        self.assertEqual(info.run_strategy, "static")
        self.assertEqual(info.project_type, "html")


# ── Node.js detection ─────────────────────────────────────────────────────────

class TestNodeDetection(unittest.TestCase):

    def test_server_js_without_html(self):
        """server.js alone (no index.html) → node."""
        ws = _make_ws({
            "server.js": "const http = require('http'); http.createServer().listen(3000);",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node")
        self.assertEqual(info.project_type, "node")

    def test_main_js_without_html(self):
        """main.js alone → node."""
        ws = _make_ws({"main.js": "console.log('server');"}  )
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node")

    def test_app_js_without_html(self):
        """app.js alone (no index.html) → node (backend JS)."""
        ws = _make_ws({"app.js": "const express = require('express');"}  )
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node")

    def test_package_json_with_html_is_still_node(self):
        """
        package.json present → always node, even when index.html also present.

        A project with package.json is a real Node project (could be a build
        step that produces index.html) — the package.json check runs BEFORE
        the js_entries check and is unaffected by this fix.
        """
        pkg = json.dumps({"name": "app", "scripts": {"start": "node server.js"}})
        ws = _make_ws({
            "package.json": pkg,
            "index.html":   _minimal_html(),
            "server.js":    "require('express')();",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node",
                         "package.json must always win over js_entries check")

    def test_package_json_only(self):
        """package.json alone → node."""
        ws = _make_ws({"package.json": json.dumps({"name": "app"})})
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node")

    def test_vite_config_is_node(self):
        """vite.config.js → node (build project)."""
        ws = _make_ws({
            "vite.config.js": "export default {};",
            "index.html":     _minimal_html(),
        })
        info = detect(ws)
        # Vite projects are routed to node strategy (build step required)
        self.assertEqual(info.run_strategy, "node")


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_empty_workspace_is_unknown(self):
        """Empty workspace → unknown/unsupported."""
        ws = _make_ws({})
        info = detect(ws)
        self.assertEqual(info.run_strategy, "unsupported")

    def test_detect_never_raises(self):
        """detect() must not propagate exceptions."""
        ws = Path(tempfile.mkdtemp())  # empty, nothing broken
        result = detect(ws)
        self.assertIsInstance(result, ProjectInfo)

    def test_readme_only_is_unknown(self):
        """README.md alone (no code) → unknown/unsupported."""
        ws = _make_ws({"README.md": "# My App"})
        info = detect(ws)
        self.assertEqual(info.run_strategy, "unsupported")

    def test_app_builder_output_entry_point_is_index(self):
        """App Builder output: entry_point must be index.html."""
        ws = _make_ws({
            "index.html": _minimal_html(),
            "app.js":     "// app",
            "styles.css": "/* css */",
        })
        info = detect(ws)
        self.assertEqual(info.entry_point, "index.html")

    def test_confidence_html_is_high(self):
        """Static HTML detection should report high confidence."""
        ws = _make_ws({"index.html": _minimal_html()})
        info = detect(ws)
        self.assertEqual(info.confidence, "high")


# ── Subdirectory project root (AI-builder generates files in backend/) ────────

class TestSubdirProjectRoot(unittest.TestCase):
    """
    Regression guard for "Run Failed" when AI builder generates all project
    files inside a subdirectory (e.g. backend/) instead of the workspace root.

    Before the fix the node driver received the workspace root, not backend/,
    causing DEP_PKG_JSON_MISSING because backend/package.json was not found at
    the root level.
    """

    def test_node_project_in_backend_subdir_detected(self):
        """Node.js project under backend/ → effective_root points to backend/."""
        pkg = json.dumps({"name": "api", "scripts": {"start": "node src/server.js"}})
        ws = _make_ws({
            "backend/package.json":    pkg,
            "backend/src/server.js":   "const express = require('express'); express().listen(3000);",
            "backend/src/routes.js":   "module.exports = [];",
            "README.md":               "# AI SaaS",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node")
        self.assertIsNotNone(info.effective_root,
                             "effective_root must be set when project is in a subdir")
        self.assertEqual(info.effective_root.name, "backend")

    def test_python_project_in_backend_subdir_detected(self):
        """Python project under backend/ → effective_root points to backend/."""
        ws = _make_ws({
            "backend/main.py":          "from fastapi import FastAPI\napp = FastAPI()",
            "backend/requirements.txt": "fastapi\nuvicorn",
            "README.md":                "# SaaS",
        })
        info = detect(ws)
        self.assertIn(info.run_strategy, ("server", "script"))
        self.assertIsNotNone(info.effective_root)
        self.assertEqual(info.effective_root.name, "backend")

    def test_node_in_server_subdir(self):
        """Node.js project under server/ is also normalised."""
        pkg = json.dumps({"name": "srv", "scripts": {"start": "node index.js"}})
        ws = _make_ws({
            "server/package.json": pkg,
            "server/index.js":     "require('express')().listen(4000);",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node")
        self.assertIsNotNone(info.effective_root)
        self.assertEqual(info.effective_root.name, "server")

    def test_root_package_json_not_redirected(self):
        """When package.json is at root, effective_root stays None (no redirect)."""
        pkg = json.dumps({"name": "root-app", "scripts": {"start": "node index.js"}})
        ws = _make_ws({
            "package.json": pkg,
            "index.js":     "console.log('hi');",
            "backend/extra.txt": "notes",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node")
        self.assertIsNone(info.effective_root,
                          "effective_root must be None when project is at workspace root")

    def test_note_mentions_subdir(self):
        """Detected subdir project includes a human-readable note about the redirect."""
        pkg = json.dumps({"name": "api"})
        ws = _make_ws({
            "backend/package.json": pkg,
            "backend/server.js":    "require('express')().listen(3000);",
        })
        info = detect(ws)
        combined = " ".join(info.notes).lower()
        self.assertIn("backend", combined)

    def test_ai_builder_15_files_in_backend(self):
        """
        Simulates the exact AI-builder output that caused the original bug:
        15 files all under backend/ — must detect node and set effective_root.
        """
        pkg = json.dumps({
            "name": "saas-api",
            "version": "1.0.0",
            "scripts": {"start": "node src/server.js", "dev": "nodemon src/server.js"},
            "dependencies": {"express": "^4.18.2", "cors": "^2.8.5"},
        })
        ws = _make_ws({
            "backend/package.json":             pkg,
            "backend/src/server.js":            "const express = require('express'); express().listen(3000);",
            "backend/src/routes/auth.js":       "module.exports = require('express').Router();",
            "backend/src/routes/users.js":      "module.exports = require('express').Router();",
            "backend/src/middleware/auth.js":    "module.exports = (req, res, next) => next();",
            "backend/src/models/user.js":        "module.exports = class User {};",
            "backend/src/config/db.js":          "module.exports = {};",
            "backend/src/utils/helpers.js":      "module.exports = {};",
            "backend/src/controllers/auth.js":   "module.exports = {};",
            "backend/src/controllers/users.js":  "module.exports = {};",
            "backend/.env.example":              "PORT=3000\nDB_URL=",
            "backend/.gitignore":                "node_modules/\n.env",
            "backend/README.md":                 "# API",
            "README.md":                         "# SaaS Project\n\nSee backend/ for the API.",
        })
        info = detect(ws)
        self.assertEqual(info.run_strategy, "node",
                         f"Expected node strategy, got {info.run_strategy!r}")
        self.assertIsNotNone(info.effective_root,
                             "effective_root must point to backend/ for AI-builder output")
        self.assertEqual(info.effective_root.name, "backend")


if __name__ == "__main__":
    unittest.main()
