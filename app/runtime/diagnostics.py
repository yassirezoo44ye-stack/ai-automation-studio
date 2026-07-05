"""
Runtime Diagnostics — generates a structured health report.

Used by GET /api/runtime/health and the Settings > Diagnostics panel.
Shows: all detected tools, versions, paths, derived capabilities, missing
tools, and install suggestions.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from app.runtime import registry, capabilities


@dataclass
class ToolReport:
    name: str
    display: str
    available: bool
    version: Optional[str]
    path: Optional[str]
    category: str
    required_for: list[str]
    install_hint: Optional[str]


@dataclass
class HealthReport:
    tools: list[ToolReport]
    env_vars: dict[str, bool]
    capabilities: dict
    missing_tools: list[str]
    suggestions: list[str]
    summary: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tools"] = [asdict(t) for t in self.tools]
        return d


_TOOL_META: dict[str, dict] = {
    "python3": {
        "display": "Python 3",
        "category": "language",
        "required_for": ["Python scripts", "FastAPI", "Flask", "PyInstaller", "BeeWare"],
        "install_hint": "https://python.org — ensure python3 is on PATH",
    },
    "python": {
        "display": "Python (legacy)",
        "category": "language",
        "required_for": ["Python scripts (Windows fallback)"],
        "install_hint": "https://python.org",
    },
    "node": {
        "display": "Node.js",
        "category": "language",
        "required_for": ["React", "Vue", "Vite", "Express", "Electron", "Capacitor"],
        "install_hint": "https://nodejs.org — install LTS 20",
    },
    "npm": {
        "display": "npm",
        "category": "package-manager",
        "required_for": ["Node.js dependencies", "Electron Builder", "Capacitor CLI"],
        "install_hint": "Bundled with Node.js — reinstall Node.js",
    },
    "npx": {
        "display": "npx",
        "category": "package-manager",
        "required_for": ["Capacitor CLI"],
        "install_hint": "Bundled with Node.js 5.2+ — update Node.js",
    },
    "java": {
        "display": "Java JDK",
        "category": "language",
        "required_for": ["Android APK builds (Briefcase, Capacitor)", "Gradle"],
        "install_hint": "Install JDK 17+ — https://adoptium.net (Eclipse Temurin)",
    },
    "javac": {
        "display": "Java Compiler",
        "category": "language",
        "required_for": ["Java compilation"],
        "install_hint": "Install JDK (not just JRE) — https://adoptium.net",
    },
    "gradle": {
        "display": "Gradle",
        "category": "build-tool",
        "required_for": ["Android APK assembly"],
        "install_hint": "https://gradle.org — or use Android Studio's bundled Gradle",
    },
    "uvicorn": {
        "display": "uvicorn",
        "category": "server",
        "required_for": ["FastAPI server (can be pip-installed automatically)"],
        "install_hint": "pip install uvicorn",
    },
    "cargo": {
        "display": "Cargo (Rust)",
        "category": "language",
        "required_for": ["Rust projects", "Tauri"],
        "install_hint": "https://rustup.rs",
    },
    "go": {
        "display": "Go",
        "category": "language",
        "required_for": ["Go projects"],
        "install_hint": "https://go.dev/dl",
    },
    "deno": {
        "display": "Deno",
        "category": "language",
        "required_for": ["Deno projects"],
        "install_hint": "https://deno.land",
    },
    "pnpm": {
        "display": "pnpm",
        "category": "package-manager",
        "required_for": ["pnpm-based Node projects"],
        "install_hint": "npm install -g pnpm",
    },
    "bun": {
        "display": "Bun",
        "category": "language",
        "required_for": ["Bun projects"],
        "install_hint": "https://bun.sh",
    },
}


def generate() -> HealthReport:
    """Build a complete health report from current registry + capabilities state."""
    reg = registry.to_dict()
    caps = capabilities.get()

    tools: list[ToolReport] = []
    missing: list[str] = []

    for name, meta in _TOOL_META.items():
        info = reg.get(name, {})
        available = info.get("available", False)
        if not available:
            missing.append(name)
        tools.append(ToolReport(
            name=name,
            display=meta["display"],
            available=available,
            version=info.get("version"),
            path=info.get("path"),
            category=meta["category"],
            required_for=meta["required_for"],
            install_hint=meta["install_hint"] if not available else None,
        ))

    env_vars = {
        "ANDROID_HOME":     registry.has_env("ANDROID_HOME"),
        "ANDROID_SDK_ROOT": registry.has_env("ANDROID_SDK_ROOT"),
        "JAVA_HOME":        registry.has_env("JAVA_HOME"),
    }

    suggestions: list[str] = []
    if not caps.can_run_python:
        suggestions.append("Install Python 3.9+ to enable script execution, FastAPI, and Flask support.")
    if not caps.can_run_node:
        suggestions.append("Install Node.js 20 LTS to enable React, Vue, Express, Electron, and Capacitor.")
    if not caps.can_build_apk and caps.can_run_python:
        if not registry.has("java"):
            suggestions.append("Install JDK 17+ to enable Android APK building.")
        if not registry.has_env("ANDROID_HOME"):
            suggestions.append("Set ANDROID_HOME to your Android SDK path to enable APK builds.")
    if caps.can_run_python and not caps.can_build_exe:
        pass  # PyInstaller is pip-installed automatically — no suggestion needed

    available_count = sum(1 for t in tools if t.available)
    total = len(tools)
    cap_count = sum(1 for v in caps.to_dict().values() if v)
    total_caps = len(caps.to_dict())
    summary = (
        f"{available_count}/{total} tools available · "
        f"{cap_count}/{total_caps} capabilities unlocked"
    )

    return HealthReport(
        tools=tools,
        env_vars=env_vars,
        capabilities=caps.to_dict(),
        missing_tools=missing,
        suggestions=suggestions,
        summary=summary,
    )
