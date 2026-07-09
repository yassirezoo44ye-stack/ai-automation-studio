"""
Pre-flight validation — Phase 2.

Checks that every tool required for a given (lang, target) or run strategy
is available BEFORE any subprocess is launched. When a tool is missing the
build/run is aborted immediately with a structured, user-readable error —
no FileNotFoundError ever reaches the client.

Public API
----------
run_preflight(lang, target)           → PreflightResult  (package system)
run_preflight_for_strategy(strategy)  → PreflightResult  (execution engine)
preflight_error_events(result)        → list[str]         (SSE event strings)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from app.runtime import registry


@dataclass
class ToolCheck:
    name: str
    display: str
    available: bool
    version: Optional[str] = None
    path: Optional[str] = None
    required_for: str = ""
    fix_hint: str = ""


@dataclass
class PreflightResult:
    ok: bool
    checks: list[ToolCheck]
    missing: list[ToolCheck]   # list of ToolCheck objects (internal detail)

    # ── Phase 2 schema fields ─────────────────────────────────────────────────
    available:   list[str] = field(default_factory=list)   # tool names that passed
    suggestions: list[str] = field(default_factory=list)   # actionable fix steps
    severity:    str        = "high"                        # "low"|"medium"|"high"

    def to_unified(self) -> dict:
        """Return the Phase 2 unified preflight schema."""
        return {
            "ok":          self.ok,
            "missing":     [c.name for c in self.missing],
            "available":   self.available,
            "suggestions": self.suggestions,
            "severity":    self.severity,
        }


# ── Tool requirement matrix ───────────────────────────────────────────────────
# Add new (lang, target) combinations here to extend the build system.

_REQUIREMENTS: dict[tuple[str, str], list[dict]] = {
    # Python → .EXE (PyInstaller)
    ("python", "exe"): [
        {
            "name": "python",
            "display": "Python 3",
            "required_for": "Python .EXE build (PyInstaller)",
            "fix_hint": "Install Python 3.9+ from python.org and ensure it is on PATH.",
        },
    ],

    # Python → .APK (BeeWare Briefcase)
    ("python", "apk"): [
        {
            "name": "python",
            "display": "Python 3",
            "required_for": "Python APK build (BeeWare Briefcase)",
            "fix_hint": "Install Python 3.9+ from python.org.",
        },
        {
            "name": "java",
            "display": "Java JDK",
            "required_for": "Android APK compilation (Briefcase needs JDK)",
            "fix_hint": "Install JDK 17+ (e.g. Eclipse Temurin) and set JAVA_HOME.",
        },
        {
            "name": "ANDROID_HOME",
            "display": "Android SDK (ANDROID_HOME)",
            "required_for": "Briefcase Android build",
            "fix_hint": "Install Android Studio, then set ANDROID_HOME to the SDK path.",
            "env_var": True,
        },
    ],

    # Web HTML → .APK (Capacitor + Gradle)
    ("web", "apk"): [
        {
            "name": "node",
            "display": "Node.js",
            "required_for": "Capacitor / npm packages",
            "fix_hint": "Install Node.js 18 LTS or 20 LTS from nodejs.org.",
        },
        {
            "name": "npm",
            "display": "npm",
            "required_for": "Installing Capacitor dependencies",
            "fix_hint": "npm ships with Node.js — reinstall Node.js.",
        },
        {
            "name": "npx",
            "display": "npx",
            "required_for": "Running Capacitor CLI",
            "fix_hint": "npx ships with Node.js 5.2+ — update Node.js.",
        },
        {
            "name": "java",
            "display": "Java JDK",
            "required_for": "Gradle / Android SDK compilation",
            "fix_hint": "Install JDK 17+ and set JAVA_HOME.",
        },
        {
            "name": "ANDROID_HOME",
            "display": "Android SDK (ANDROID_HOME)",
            "required_for": "Gradle APK build",
            "fix_hint": "Install Android Studio, then set ANDROID_HOME to the SDK path.",
            "env_var": True,
        },
    ],

    # Electron → .EXE (Electron Builder)
    ("electron", "exe"): [
        {
            "name": "node",
            "display": "Node.js",
            "required_for": "Electron app build",
            "fix_hint": "Install Node.js 18 LTS or 20 LTS from nodejs.org.",
        },
        {
            "name": "npm",
            "display": "npm",
            "required_for": "Installing Electron and electron-builder",
            "fix_hint": "npm ships with Node.js — reinstall Node.js.",
        },
    ],

    # Web HTML → .EXE (wrapped in Electron — same pipeline as electron→exe)
    ("web", "exe"): [
        {
            "name": "node",
            "display": "Node.js",
            "required_for": "Electron wrap build for the web app",
            "fix_hint": "Install Node.js 18 LTS or 20 LTS from nodejs.org.",
        },
        {
            "name": "npm",
            "display": "npm",
            "required_for": "Installing Electron and electron-builder",
            "fix_hint": "npm ships with Node.js — reinstall Node.js.",
        },
    ],
}


# ── Run-strategy requirement matrix ──────────────────────────────────────────
# Used by the execution engine before dispatching to a driver.

_RUN_REQUIREMENTS: dict[str, list[dict]] = {
    "script": [
        {
            "name": "python",
            "display": "Python 3",
            "required_for": "Running Python scripts",
            "fix_hint": "Install Python 3.11+ from https://python.org and ensure it is on PATH.",
        },
    ],
    "server": [
        {
            "name": "python",
            "display": "Python 3",
            "required_for": "Running FastAPI/Flask servers",
            "fix_hint": "Install Python 3.11+ from https://python.org and ensure it is on PATH.",
        },
    ],
    "flask": [
        {
            "name": "python",
            "display": "Python 3",
            "required_for": "Running Flask servers",
            "fix_hint": "Install Python 3.11+ from https://python.org and ensure it is on PATH.",
        },
    ],
    "node": [
        {
            "name": "node",
            "display": "Node.js",
            "required_for": "Running Node.js / npm projects",
            "fix_hint": "Install Node.js 20 LTS from https://nodejs.org.",
        },
    ],
    "npm": [
        {
            "name": "node",
            "display": "Node.js",
            "required_for": "Running npm-based projects",
            "fix_hint": "Install Node.js 20 LTS from https://nodejs.org.",
        },
        {
            "name": "npm",
            "display": "npm",
            "required_for": "Running npm scripts",
            "fix_hint": "npm ships with Node.js — reinstall Node.js 20 LTS.",
        },
    ],
    # "static" has no runtime requirements — HTML is read from disk
    # "unsupported" has no requirements — handled by fallback driver
}


def run_preflight(lang: str, target: str) -> PreflightResult:
    """
    Check all tools required for (lang, target).
    Never raises — always returns a PreflightResult.
    """
    requirements = _REQUIREMENTS.get((lang, target), [])
    return _check_requirements(requirements)


def run_preflight_for_strategy(strategy: str) -> PreflightResult:
    """
    Check tools required for a run strategy (used by the execution engine).
    Never raises — always returns a PreflightResult.
    """
    requirements = _RUN_REQUIREMENTS.get(strategy, [])
    return _check_requirements(requirements)


def _check_requirements(requirements: list[dict]) -> PreflightResult:
    checks: list[ToolCheck] = []

    for req in requirements:
        name = req["name"]
        is_env = req.get("env_var", False)

        if is_env:
            avail = registry.has_env(name)
            info = None
        else:
            avail = registry.has(name)
            info = registry.get(name) or registry.get("python3" if name == "python" else name)

        checks.append(ToolCheck(
            name=name,
            display=req["display"],
            available=avail,
            version=info.version if info else None,
            path=info.path if info else None,
            required_for=req.get("required_for", ""),
            fix_hint=req.get("fix_hint", ""),
        ))

    missing = [c for c in checks if not c.available]
    available_names = [c.name for c in checks if c.available]
    suggestions = [c.fix_hint for c in missing if c.fix_hint]
    severity = "high" if missing else "low"

    return PreflightResult(
        ok=len(missing) == 0,
        checks=checks,
        missing=missing,
        available=available_names,
        suggestions=suggestions,
        severity=severity,
    )


def preflight_error_events(result: PreflightResult) -> list[str]:
    """
    Convert a failed PreflightResult into SSE event strings for streaming.
    """
    events: list[str] = []

    events.append(
        f"data: {json.dumps({'type':'log','text':'━━━ Pre-flight Check ━━━','level':'info'})}\n\n"
    )
    for check in result.checks:
        icon = "✓" if check.available else "✗"
        level = "ok" if check.available else "err"
        ver = f"  ({check.version})" if check.version else ""
        events.append(
            f"data: {json.dumps({'type':'log','text':f'{icon} {check.display}{ver}','level':level})}\n\n"
        )

    events.append(
        f"data: {json.dumps({'type':'log','text':'','level':'info'})}\n\n"
    )
    for missing in result.missing:
        events.append(
            f"data: {json.dumps({'type':'log','text':f'Missing: {missing.display}','level':'err'})}\n\n"
        )
        events.append(
            f"data: {json.dumps({'type':'log','text':f'  Required for: {missing.required_for}','level':'err'})}\n\n"
        )
        events.append(
            f"data: {json.dumps({'type':'log','text':f'  Fix: {missing.fix_hint}','level':'info'})}\n\n"
        )

    first = result.missing[0]
    events.append(f"data: {json.dumps({'type': 'error', 'category': 'preflight', 'message': f'Missing runtime: {first.display}', 'fix': result.suggestions, 'severity': result.severity, 'recoverable': False, 'missing_tool': first.name, 'required_for': first.required_for, 'all_missing': [m.name for m in result.missing]})}\n\n")
    return events
