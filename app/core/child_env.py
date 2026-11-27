"""Minimal environment for processes that run user, project or plugin code.

Child processes used to start from a copy of the server's os.environ, so any
project script, build step or plugin could read DATABASE_URL, SESSION_SECRET
(which signs every user's session) and provider/Stripe keys, and from there
reach every tenant's data. Only what a toolchain needs to run is passed on.

Variables that change how an interpreter loads code (NODE_OPTIONS,
PYTHONPATH, PYTHONSTARTUP, LD_PRELOAD, …) are deliberately not forwarded, so
a value planted in the server environment can't run inside other users'
processes either.
"""
from __future__ import annotations

import os

# Exact names a build/run toolchain may legitimately need.
_ALLOWED = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL",
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TZ", "TERM",
    "TMPDIR", "TEMP", "TMP",
    "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "GRADLE_USER_HOME",
    "NODE_ENV", "PYTHONUNBUFFERED", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
    # Windows essentials (dev machines)
    "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMFILES", "ProgramFiles",
})


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return an allowlisted copy of the server environment plus `extra`."""
    env = {k: v for k, v in os.environ.items() if k in _ALLOWED}
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env
