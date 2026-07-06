"""
ScriptResolver — reads package.json and validates that a requested script
exists before any process is spawned.

Never guess at script names. Never allow execution of undefined scripts.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .errors import PackageJsonMissing, ScriptNotFound

log = logging.getLogger(__name__)

# Scripts we try in order when the caller requests the generic "start" flow.
_START_CANDIDATES = ("start", "dev", "serve", "preview")
_BUILD_CANDIDATES = ("build", "compile", "bundle")


class ScriptResolver:
    """
    Reads package.json scripts and resolves script names.

    Raises structured errors instead of letting the caller discover
    a missing script at process-start time.
    """

    def resolve(self, ws: Path, script: str) -> str:
        """
        Verify `script` exists in package.json and return its exact name.

        Raises:
            PackageJsonMissing  — no package.json in workspace
            ScriptNotFound      — script name not in package.json scripts
        """
        scripts = self._load_scripts(ws)
        if script not in scripts:
            raise ScriptNotFound(
                message=f'Script "{script}" not defined in package.json',
                script=script,
                available=sorted(scripts.keys()),
            )
        log.debug("resolved script %r in %s", script, ws.name)
        return script

    def resolve_start(self, ws: Path) -> Optional[str]:
        """
        Find the best script to start the project server.

        Returns the first matching candidate from _START_CANDIDATES,
        or None if none are defined (caller falls back to `node <entry>`).
        Does NOT raise if package.json is missing — returns None instead.
        """
        try:
            scripts = self._load_scripts(ws)
        except PackageJsonMissing:
            return None
        for candidate in _START_CANDIDATES:
            if candidate in scripts:
                log.debug("resolved start script → %r in %s", candidate, ws.name)
                return candidate
        return None

    def resolve_build(self, ws: Path) -> Optional[str]:
        """Return the build script name, or None if not defined."""
        try:
            scripts = self._load_scripts(ws)
        except PackageJsonMissing:
            return None
        for candidate in _BUILD_CANDIDATES:
            if candidate in scripts:
                return candidate
        return None

    def list_scripts(self, ws: Path) -> dict[str, str]:
        """Return all scripts from package.json, or {} if missing."""
        try:
            return self._load_scripts(ws)
        except PackageJsonMissing:
            return {}

    def _load_scripts(self, ws: Path) -> dict[str, str]:
        pkg_json = ws / "package.json"
        if not pkg_json.exists():
            raise PackageJsonMissing(message="package.json not found in project root")
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            return {k: str(v) for k, v in data.get("scripts", {}).items()}
        except json.JSONDecodeError as exc:
            raise PackageJsonMissing(
                message=f"package.json is not valid JSON: {exc}"
            ) from exc
