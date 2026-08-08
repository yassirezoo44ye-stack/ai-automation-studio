"""
Regression tests for the AUDIT FIX to app/core/filesystem.py's traversal
checks (workspace(), safe_path()): both used to compare with
`str(p).startswith(str(root))`, the classic gotcha where a sibling
directory whose name happens to be a string-prefix of the real root's name
(e.g. "root-evil" vs "root") passes the check even though it isn't actually
inside it. Now uses Path.is_relative_to(), which closes that class of bug
outright.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.core.filesystem import safe_path, workspace


class TestSafePathStillAllowsLegitimateAccess(unittest.TestCase):
    def test_a_plain_relative_path_inside_the_workspace_resolves(self):
        ws = Path("/tmp/ws-root")
        p = safe_path(ws, "sub/file.txt")
        self.assertEqual(p, (ws / "sub/file.txt").resolve())

    def test_dot_dot_traversal_outside_the_workspace_is_still_rejected(self):
        ws = Path("/tmp/ws-root")
        with self.assertRaises(HTTPException) as cm:
            safe_path(ws, "../../etc/passwd")
        self.assertEqual(cm.exception.status_code, 400)


class TestSafePathRejectsSiblingPrefixGotcha(unittest.TestCase):
    """The exact bug class the fix closes: a resolved path that lands in a
    sibling directory whose name is a superstring of the real workspace's
    name must be rejected — the old `startswith` string check would have
    wrongly accepted it."""

    def test_traversal_into_a_sibling_dir_with_a_superstring_name_is_rejected(self):
        ws = Path("/tmp/ws-root")
        # "/tmp/ws-root-evil" starts with "/tmp/ws-root" as a *string*, but
        # is not actually inside it as a *path*.
        with self.assertRaises(HTTPException) as cm:
            safe_path(ws, "../ws-root-evil/secret.txt")
        self.assertEqual(cm.exception.status_code, 400)


class TestWorkspaceStillAllowsLegitimateAccess(unittest.TestCase):
    def test_a_plain_project_id_resolves_and_creates_the_dir(self):
        with patch("app.core.filesystem.WORKSPACES", Path("/tmp/workspaces-root")), \
             patch.object(Path, "mkdir") as mkdir_mock:
            ws = workspace("project-123")
            self.assertEqual(ws, (Path("/tmp/workspaces-root") / "project-123").resolve())
            mkdir_mock.assert_called_once()

    def test_dot_dot_traversal_is_still_rejected(self):
        with patch("app.core.filesystem.WORKSPACES", Path("/tmp/workspaces-root")):
            with self.assertRaises(HTTPException) as cm:
                workspace("../../etc")
            self.assertEqual(cm.exception.status_code, 400)


class TestWorkspaceRejectsSiblingPrefixGotcha(unittest.TestCase):
    def test_a_project_id_resolving_into_a_superstring_sibling_root_is_rejected(self):
        with patch("app.core.filesystem.WORKSPACES", Path("/tmp/workspaces-root")):
            with self.assertRaises(HTTPException) as cm:
                workspace("../workspaces-root-evil/whatever")
            self.assertEqual(cm.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
