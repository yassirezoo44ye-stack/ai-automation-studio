import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_chat_preview import write_preview_config


ROOT = Path(__file__).resolve().parents[1]
BACKEND = "https://flow-chat-review-api-test.onrender.com"


class ChatPreviewFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "vercel.json"
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        config["testDescription"] = "معاينة المحادثات"
        self.source.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        self.original = self.source.read_bytes()
        self.output = self.root / "preview.json"

    def test_real_repository_config_roundtrips_utf8_without_changing_source(self):
        write_preview_config(self.source, self.output, BACKEND)
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(result["testDescription"], "معاينة المحادثات")
        self.assertEqual(result["rewrites"][0]["destination"], BACKEND + "/api/:path*")
        self.assertEqual(result["rewrites"][1]["destination"], "/index.html")
        self.assertNotIn("ai-automation-studio-viio.onrender.com", self.output.read_text())

    def test_rejects_source_as_output(self):
        with self.assertRaises(ValueError):
            write_preview_config(self.source, self.source, BACKEND)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_rejects_hardlink_to_source(self):
        os.link(self.source, self.output)
        with self.assertRaises(ValueError):
            write_preview_config(self.source, self.output, BACKEND)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_rejects_symlink_to_source(self):
        self.output.symlink_to(self.source)
        with self.assertRaises(ValueError):
            write_preview_config(self.source, self.output, BACKEND)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_failed_validation_preserves_previous_output(self):
        self.output.write_text("previous config")
        with self.assertRaises(ValueError):
            write_preview_config(self.source, self.output, "https://production.example")
        self.assertEqual(self.output.read_text(), "previous config")

    def test_failed_replace_keeps_previous_output_and_removes_temporary_file(self):
        self.output.write_text("previous config")
        with patch("scripts.prepare_chat_preview.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                write_preview_config(self.source, self.output, BACKEND)
        self.assertEqual(self.output.read_text(), "previous config")
        self.assertEqual(list(self.root.glob(".flow-preview-*")), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_cli_writes_separate_config(self):
        result = self.run_cli(BACKEND)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_cli_rejects_credentials_without_echoing_them(self):
        result = self.run_cli("https://test-user:sentinel-not-a-secret@flow-chat-review-api.onrender.com")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("sentinel-not-a-secret", result.stderr + result.stdout)
        self.assertFalse(self.output.exists())

    def run_cli(self, backend):
        return subprocess.run([
            sys.executable, str(ROOT / "scripts/prepare_chat_preview.py"),
            "--source", str(self.source), "--output", str(self.output),
            "--backend-url", backend,
        ], capture_output=True, text=True, check=False)


if __name__ == "__main__":
    unittest.main()
