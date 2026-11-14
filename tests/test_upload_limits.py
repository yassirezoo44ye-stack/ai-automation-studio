"""
Upload endpoint size-limit tests.

Verifies that:
  - A file exceeding 50 MB per-file cap returns 413
  - Multiple files summing > 200 MB total returns 413
  - Empty filename is rejected with 400
  - Normal upload (< 50 MB) succeeds
  - Exactly at the 50 MB boundary is accepted
"""
from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient


def _fake_pool():
    conn = AsyncMock()
    conn.fetchrow.return_value = {"id": "proj-1", "user_id": "uid-1"}
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _make_client():
    """Return a TestClient with the build router mounted."""
    from fastapi import FastAPI
    from app.routers.build import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


_OWNER_EMAIL = "owner@example.com"
_PROJECT_ID = "00000000-0000-0000-0000-000000000001"


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


class TestUploadLimits(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()
        self.pool = _fake_pool()

    def _upload(self, files, *, project_id=_PROJECT_ID):
        with patch("app.routers.build.get_pool", return_value=self.pool), \
             patch("app.routers.build.owner_email", return_value=_OWNER_EMAIL), \
             patch("app.routers.build._require_project_owner", new=AsyncMock()):
            return self.client.post(
                f"/api/projects/{project_id}/upload",
                files=files,
                headers=_auth_headers(),
            )

    def test_normal_small_file_accepted(self):
        content = b"x" * 1024  # 1 KB
        resp = self._upload([("files", ("hello.txt", BytesIO(content), "text/plain"))])
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["saved"][0]["size"], 1024)

    def test_file_exactly_at_50mb_limit_accepted(self):
        content = b"x" * (50 * 1024 * 1024)  # exactly 50 MB
        resp = self._upload([("files", ("big.bin", BytesIO(content), "application/octet-stream"))])
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_file_one_byte_over_50mb_rejected_413(self):
        content = b"x" * (50 * 1024 * 1024 + 1)
        resp = self._upload([("files", ("toobig.bin", BytesIO(content), "application/octet-stream"))])
        self.assertEqual(resp.status_code, 413, resp.text)
        self.assertIn("50 MB", resp.json().get("detail", ""))

    def test_empty_filename_rejected_4xx(self):
        # An empty filename is rejected either by the framework (422) or
        # by the handler's own guard (400) — both are correct client errors.
        resp = self._upload([("files", ("", BytesIO(b"data"), "text/plain"))])
        self.assertIn(resp.status_code, (400, 422), resp.text)

    def test_multiple_files_under_total_accepted(self):
        # 3 files × 1 MB = 3 MB total — well under 200 MB
        content = b"y" * (1024 * 1024)
        files = [
            ("files", (f"file{i}.bin", BytesIO(content), "application/octet-stream"))
            for i in range(3)
        ]
        resp = self._upload(files)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["count"], 3)

    def test_total_exceeding_200mb_rejected_413(self):
        # 5 files × 45 MB = 225 MB — over the 200 MB aggregate limit
        chunk = b"z" * (45 * 1024 * 1024)
        files = [
            ("files", (f"chunk{i}.bin", BytesIO(chunk), "application/octet-stream"))
            for i in range(5)
        ]
        resp = self._upload(files)
        self.assertEqual(resp.status_code, 413, resp.text)
        self.assertIn("200 MB", resp.json().get("detail", ""))


if __name__ == "__main__":
    unittest.main()
