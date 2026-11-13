"""Child processes for user/project/plugin code get an allowlisted env."""
from __future__ import annotations

from unittest.mock import patch

from app.core.child_env import child_env


def test_server_secrets_are_not_inherited():
    fake = {
        "PATH": "/usr/bin", "HOME": "/home/app", "LANG": "C.UTF-8",
        "DATABASE_URL": "postgresql://secret", "SESSION_SECRET": "s3cret",
        "ANTHROPIC_API_KEY": "k", "STRIPE_SECRET_KEY": "k",
        "NODE_OPTIONS": "--require=/tmp/evil.js", "PYTHONPATH": "/tmp/evil",
        "LD_PRELOAD": "/tmp/evil.so",
    }
    with patch.dict("os.environ", fake, clear=True):
        env = child_env({"PORT": 8123})
    assert env == {"PATH": "/usr/bin", "HOME": "/home/app", "LANG": "C.UTF-8", "PORT": "8123"}


def test_runtime_process_env_uses_the_allowlist():
    from app.runtime import process
    with patch.dict("os.environ", {"PATH": "/bin", "SESSION_SECRET": "s"}, clear=True):
        env = process._build_env({"X": "1"})
    assert "SESSION_SECRET" not in env
    assert env["PATH"] == "/bin" and env["X"] == "1"
