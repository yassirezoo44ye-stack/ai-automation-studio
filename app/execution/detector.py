"""
ProjectDetector — inspects workspace files and determines project type,
run strategy, and entry point without executing any code.

Run strategies:
  static      → serve HTML content as blob URL
  script      → subprocess, capture stdout/stderr
  server      → uvicorn/gunicorn, proxy via FastAPI route
  flask       → Flask server (node driver will pip-install if needed)
  node        → Node.js server/script (node driver handles if runtime available)
  npm         → npm start / npm run dev (node driver handles)
  unsupported → cannot run in this sandbox (electron, docker, rust, java, etc.)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ProjectInfo:
    project_type: str           # e.g. "html", "python_script", "fastapi"
    run_strategy: str           # "static" | "script" | "server" | "unsupported"
    entry_point: Optional[str]  # relative path, e.g. "main.py" or "index.html"
    confidence: str             # "high" | "medium" | "low"
    detected_by: list[str]      # files / patterns that triggered detection
    notes: list[str] = field(default_factory=list)  # human-readable messages
    unsupported_reason: str = ""
    local_run_hint: str = ""    # how to run locally when unsupported


# ── Public API ────────────────────────────────────────────────────────────────

def detect(ws: Path) -> ProjectInfo:
    """
    Scan *ws* and return a ProjectInfo.
    Never raises — returns project_type="unknown" on any error.
    """
    try:
        return _detect(ws)
    except Exception as exc:
        return ProjectInfo(
            project_type="unknown", run_strategy="unsupported",
            entry_point=None, confidence="low", detected_by=[],
            unsupported_reason=f"Detection error: {exc}",
        )


# ── Internal detection logic ──────────────────────────────────────────────────

def _detect(ws: Path) -> ProjectInfo:
    files: dict[str, Path] = {
        str(p.relative_to(ws)).replace("\\", "/"): p
        for p in ws.rglob("*") if p.is_file()
    }
    fset = set(files)

    # ── Highest-confidence manifest files ─────────────────────────────────

    if "electron-builder.yml" in fset or "electron-builder.yaml" in fset:
        return _unsupported("electron", fset, "Electron apps require a GUI runtime.",
                            "npm start  (after npm install)")

    if _has_any(fset, "tauri.conf.json", "src-tauri/tauri.conf.json"):
        return _unsupported("tauri", fset, "Tauri requires Rust + WebView2.",
                            "cargo tauri dev")

    if _has_any(fset, "docker-compose.yml", "docker-compose.yaml"):
        # Try to run the inner project directly (Docker not available in sandbox)
        inner = _detect_inner_for_docker(ws, fset)
        if inner:
            inner.notes.insert(0, "⚠️ Docker Compose not available — running app directly without Docker.")
            return inner
        return _unsupported("docker_compose", fset,
                            "Docker Compose is not available in this sandbox.",
                            "docker compose up")

    if "Dockerfile" in fset:
        # Try inner project before giving up
        inner = _detect_inner_for_docker(ws, fset)
        if inner:
            inner.notes.insert(0, "⚠️ Docker not available — running app directly.")
            return inner
        return _unsupported("docker", fset, "Docker is not available in this sandbox.",
                            "docker build . && docker run ...")

    if "Cargo.toml" in fset:
        return _unsupported("rust", fset, "Rust toolchain not installed.",
                            "cargo run")

    if "pom.xml" in fset or "build.gradle" in fset:
        return _unsupported("java", fset, "Java/JVM not installed.",
                            "mvn spring-boot:run  or  gradle run")

    if _has_prefix(fset, "next.config."):
        return ProjectInfo(project_type="nextjs", run_strategy="node",
                           entry_point=None, confidence="high",
                           detected_by=list(_triggers_prefix(fset, "next.config.")),
                           notes=["Next.js — handled by Node driver if available."])

    if _has_prefix(fset, "vite.config."):
        return ProjectInfo(project_type="vite", run_strategy="node",
                           entry_point=None, confidence="high",
                           detected_by=list(_triggers_prefix(fset, "vite.config.")),
                           notes=["Vite — handled by Node driver if available."])

    if _has_prefix(fset, "nuxt.config."):
        return ProjectInfo(project_type="nuxt", run_strategy="node",
                           entry_point=None, confidence="high",
                           detected_by=list(_triggers_prefix(fset, "nuxt.config.")),
                           notes=["Nuxt — handled by Node driver if available."])

    if _has_prefix(fset, "svelte.config."):
        return ProjectInfo(project_type="svelte", run_strategy="node",
                           entry_point=None, confidence="high",
                           detected_by=list(_triggers_prefix(fset, "svelte.config.")),
                           notes=["Svelte — handled by Node driver if available."])

    # ── Python framework detection (highest priority for Python) ──────────

    # Django — unmistakable signature
    if "manage.py" in fset:
        return _unsupported("django", fset,
                            "Django is not installed in this sandbox.",
                            "python manage.py runserver")

    # Read requirements.txt once for all framework checks
    reqs_lower = ""
    if "requirements.txt" in fset:
        try:
            reqs_lower = files["requirements.txt"].read_text(encoding="utf-8").lower()
        except Exception:
            pass

    # Flask — return run_strategy="flask" so python_server driver can handle it
    if _has_flask(reqs_lower, fset, files):
        entry = _find_py_entry(fset)
        return ProjectInfo(
            project_type="flask", run_strategy="flask",
            entry_point=entry, confidence="high",
            detected_by=_triggers(fset, "requirements.txt", entry or "app.py"),
            notes=["Flask detected — will install dependencies and run."],
        )

    # FastAPI — uvicorn IS installed → can actually run with proxy
    if _has_fastapi(reqs_lower, fset, files):
        entry = _find_py_entry(fset)
        if entry:
            return ProjectInfo(
                project_type="fastapi", run_strategy="server",
                entry_point=entry, confidence="high",
                detected_by=_triggers(fset, "requirements.txt", entry),
                notes=[f"FastAPI server — will run on an internal port and be proxied."],
            )

    # aiohttp / other async frameworks
    if "aiohttp" in reqs_lower or "tornado" in reqs_lower:
        return _unsupported("aiohttp", fset,
                            "aiohttp/tornado not installed in sandbox.",
                            "pip install aiohttp && python main.py")

    # ── Runnable Python scripts ────────────────────────────────────────────

    py_entry = _find_py_entry(fset)

    if py_entry:
        # Deep-check: does the file import Flask/FastAPI without requirements.txt?
        try:
            src = files[py_entry].read_text(encoding="utf-8")
        except Exception:
            src = ""

        if re.search(r"from\s+flask\b|import\s+flask\b|Flask\(", src, re.I):
            return _unsupported("flask", fset,
                                "Flask is not installed in this sandbox.",
                                f"pip install flask && python {py_entry}",
                                entry=py_entry)

        if re.search(r"from\s+fastapi\b|import\s+fastapi\b|FastAPI\(", src, re.I):
            return ProjectInfo(
                project_type="fastapi", run_strategy="server",
                entry_point=py_entry, confidence="medium",
                detected_by=[py_entry],
                notes=["FastAPI detected by import — will try proxy mode."],
            )

        if re.search(r"from\s+django\b|import\s+django\b", src, re.I):
            return _unsupported("django", fset,
                                "Django is not installed in this sandbox.",
                                f"python manage.py runserver",
                                entry=py_entry)

        return ProjectInfo(
            project_type="python_script", run_strategy="script",
            entry_point=py_entry, confidence="high",
            detected_by=[py_entry],
        )

    # Any .py file (non-test, non-config)
    all_py = _all_py_files(fset)
    if all_py:
        return ProjectInfo(
            project_type="python_script", run_strategy="script",
            entry_point=all_py[0], confidence="medium",
            detected_by=[all_py[0]],
        )

    # ── Node.js — route to node driver; it will check registry availability ───

    if "package.json" in fset:
        pkg_type = _node_type(files, fset)
        return ProjectInfo(
            project_type=pkg_type, run_strategy="node",
            entry_point=None, confidence="high",
            detected_by=["package.json"],
            notes=[f"{pkg_type} project — handled by Node driver if runtime available."],
        )

    js_entries = [f for f in ("main.js", "index.js", "server.js", "app.js") if f in fset]
    if js_entries:
        return ProjectInfo(
            project_type="node", run_strategy="node",
            entry_point=js_entries[0], confidence="medium",
            detected_by=[js_entries[0]],
            notes=["Node.js script — handled by Node driver if runtime available."],
        )

    # ── HTML static ────────────────────────────────────────────────────────

    html_files = sorted(f for f in fset if f.endswith(".html"))
    if html_files:
        entry = "index.html" if "index.html" in fset else html_files[0]
        return ProjectInfo(
            project_type="html", run_strategy="static",
            entry_point=entry, confidence="high",
            detected_by=html_files,
        )

    # ── Unknown ────────────────────────────────────────────────────────────

    return ProjectInfo(
        project_type="unknown", run_strategy="unsupported",
        entry_point=None, confidence="low",
        detected_by=list(fset)[:10],
        unsupported_reason=(
            "Could not determine project type. "
            "Add main.py, index.html, or package.json."
        ),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_any(fset: set, *names: str) -> bool:
    return any(n in fset for n in names)


def _has_prefix(fset: set, prefix: str) -> bool:
    return any(f.startswith(prefix) for f in fset)


def _triggers(fset: set, *names: str) -> list[str]:
    return [n for n in names if n in fset]


def _triggers_prefix(fset: set, prefix: str) -> list[str]:
    return [f for f in fset if f.startswith(prefix)]


def _find_py_entry(fset: set) -> Optional[str]:
    priority = ("main.py", "app.py", "server.py", "run.py", "api.py",
                "cli.py", "solution.py", "wsgi.py", "asgi.py", "index.py")
    for f in priority:
        if f in fset:
            return f
    return None


def _all_py_files(fset: set) -> list[str]:
    skip = ("test_", "_test.py", "setup.py", "conf.py", "conftest.py")
    return sorted(
        f for f in fset
        if f.endswith(".py")
        and not any(s in f for s in skip)
        and not f.startswith("__")
    )


def _has_flask(reqs_lower: str, fset: set, files: dict) -> bool:
    if "flask" in reqs_lower:
        return True
    # Check entry file imports
    entry = _find_py_entry(fset)
    if entry and entry in files:
        try:
            src = files[entry].read_text(encoding="utf-8")
            return bool(re.search(r"from\s+flask\b|import\s+flask\b|Flask\(", src, re.I))
        except Exception:
            pass
    return False


def _has_fastapi(reqs_lower: str, fset: set, files: dict) -> bool:
    if "fastapi" in reqs_lower or "uvicorn" in reqs_lower:
        return True
    entry = _find_py_entry(fset)
    if entry and entry in files:
        try:
            src = files[entry].read_text(encoding="utf-8")
            return bool(re.search(r"from\s+fastapi\b|import\s+fastapi\b|FastAPI\(", src, re.I))
        except Exception:
            pass
    return False


def _node_type(files: dict, fset: set) -> str:
    try:
        pkg = json.loads(files["package.json"].read_text(encoding="utf-8"))
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "react" in deps:      return "react"
        if "vue" in deps:        return "vue"
        if "svelte" in deps:     return "svelte"
        if "express" in deps:    return "express"
        if "koa" in deps:        return "koa"
        if "@nestjs/core" in deps: return "nestjs"
    except Exception:
        pass
    return "node"


def _unsupported(
    project_type: str,
    fset: set,
    reason: str,
    local_hint: str,
    entry: Optional[str] = None,
) -> ProjectInfo:
    detected_by = [f for f in fset if not f.endswith((".png", ".jpg", ".ico", ".svg"))][:6]
    return ProjectInfo(
        project_type=project_type, run_strategy="unsupported",
        entry_point=entry, confidence="high",
        detected_by=detected_by,
        unsupported_reason=reason,
        local_run_hint=local_hint,
    )


def _detect_inner_for_docker(ws: Path, fset: set) -> Optional[ProjectInfo]:
    """
    When Docker/Compose is detected, look for a runnable inner component
    (Next.js, Vite, Node.js, Python) and return its ProjectInfo so we can
    run the app directly without Docker.

    Searches both root and common sub-directories (frontend/, backend/, app/).
    Returns None if no runnable component is found.
    """
    search_dirs = [ws] + [
        ws / d for d in ("frontend", "client", "web", "app", "backend", "server")
        if (ws / d).is_dir()
    ]

    for base in search_dirs:
        sub_fset: set[str] = {
            str(p.relative_to(base)).replace("\\", "/")
            for p in base.rglob("*") if p.is_file()
        }

        # Next.js
        if any(f.startswith("next.config.") for f in sub_fset):
            return ProjectInfo(
                project_type="nextjs", run_strategy="node",
                entry_point=None, confidence="high",
                detected_by=["next.config.*"],
                notes=["Next.js app detected inside Docker project."],
            )

        # Vite / React / Vue
        if any(f.startswith("vite.config.") for f in sub_fset):
            return ProjectInfo(
                project_type="vite", run_strategy="node",
                entry_point=None, confidence="high",
                detected_by=["vite.config.*"],
                notes=["Vite app detected inside Docker project."],
            )

        # package.json with start/dev script
        if "package.json" in sub_fset:
            pkg_path = base / "package.json"
            try:
                pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
                scripts = pkg.get("scripts", {})
                if scripts.get("start") or scripts.get("dev"):
                    pkg_type = _node_type({**{
                        str(p.relative_to(base)).replace("\\", "/"): p
                        for p in base.rglob("*") if p.is_file()
                    }}, sub_fset)
                    return ProjectInfo(
                        project_type=pkg_type, run_strategy="node",
                        entry_point=None, confidence="medium",
                        detected_by=["package.json"],
                        notes=[f"{pkg_type} project detected inside Docker project."],
                    )
            except Exception:
                pass

        # Python
        py_entry = _find_py_entry(sub_fset)
        if py_entry:
            return ProjectInfo(
                project_type="python_script", run_strategy="script",
                entry_point=py_entry, confidence="medium",
                detected_by=[py_entry],
                notes=["Python entry detected inside Docker project."],
            )

    return None
