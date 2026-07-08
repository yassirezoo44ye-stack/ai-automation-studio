"""
Typed error codes for every failure the JS runtime can produce.

Each code maps to exactly one failure mode.  Callers switch on the code
to decide how to render the error; they never parse the message string.

Naming convention:
  Phase prefix + _ + specific failure
  ENV_*   — Phase A (environment validation)
  DEP_*   — Phase B (dependency resolution)
  EXEC_*  — Phase C (application execution)
"""
from __future__ import annotations

from enum import Enum


class RuntimeErrorCode(str, Enum):
    # ── Phase A: Environment ──────────────────────────────────────────────────
    ENV_NODE_MISSING        = "ENV_NODE_MISSING"        # node binary not found
    ENV_PM_MISSING          = "ENV_PM_MISSING"          # no PM found anywhere
    ENV_PM_BROKEN           = "ENV_PM_BROKEN"           # binary exits non-zero on --version
    ENV_TMP_NOT_WRITABLE    = "ENV_TMP_NOT_WRITABLE"    # /tmp not writable — can't redirect cache
    ENV_INVALID_WORKSPACE   = "ENV_INVALID_WORKSPACE"   # workspace dir missing or unreadable

    # ── Phase B: Dependencies ─────────────────────────────────────────────────
    DEP_PKG_JSON_MISSING    = "DEP_PKG_JSON_MISSING"    # no package.json in workspace
    DEP_PKG_JSON_INVALID    = "DEP_PKG_JSON_INVALID"    # package.json is not valid JSON
    DEP_LOCKFILE_MISSING    = "DEP_LOCKFILE_MISSING"    # no lockfile (non-deterministic install)
    DEP_INSTALL_FAILED      = "DEP_INSTALL_FAILED"      # generic non-zero exit
    DEP_INSTALL_EACCES      = "DEP_INSTALL_EACCES"      # EACCES — filesystem permission denied
    DEP_INSTALL_ERESOLVE    = "DEP_INSTALL_ERESOLVE"    # ERESOLVE — version conflict
    DEP_INSTALL_ENOTFOUND   = "DEP_INSTALL_ENOTFOUND"   # ENOTFOUND — network / registry unreachable
    DEP_INSTALL_ETARGET     = "DEP_INSTALL_ETARGET"     # ETARGET — package version not found
    DEP_INSTALL_ENGINE      = "DEP_INSTALL_ENGINE"      # engine mismatch (node version too old)
    DEP_INSTALL_TIMEOUT     = "DEP_INSTALL_TIMEOUT"     # install timed out
    DEP_EXTERNAL_SERVICE    = "DEP_EXTERNAL_SERVICE"    # requires DB/queue not in sandbox

    # ── Phase C: Execution ────────────────────────────────────────────────────
    EXEC_SCRIPT_MISSING     = "EXEC_SCRIPT_MISSING"     # script not in package.json
    EXEC_SERVER_TIMEOUT     = "EXEC_SERVER_TIMEOUT"     # server did not bind port within limit
    EXEC_SERVER_CRASH       = "EXEC_SERVER_CRASH"       # server process exited early
    EXEC_PORT_UNAVAILABLE   = "EXEC_PORT_UNAVAILABLE"   # port pool exhausted
    EXEC_BUILD_FAILED       = "EXEC_BUILD_FAILED"       # build script exited non-zero


# ── npm stderr → error code mapping ──────────────────────────────────────────
# Used by InstallErrorClassifier to extract a typed code from raw npm output.

_NPM_CODE_MAP: dict[str, RuntimeErrorCode] = {
    "EACCES":           RuntimeErrorCode.DEP_INSTALL_EACCES,
    "EPERM":            RuntimeErrorCode.DEP_INSTALL_EACCES,
    "ERESOLVE":         RuntimeErrorCode.DEP_INSTALL_ERESOLVE,
    "ENOTFOUND":        RuntimeErrorCode.DEP_INSTALL_ENOTFOUND,
    "ECONNREFUSED":     RuntimeErrorCode.DEP_INSTALL_ENOTFOUND,
    "ETARGET":          RuntimeErrorCode.DEP_INSTALL_ETARGET,
    "ENOPKG":           RuntimeErrorCode.DEP_INSTALL_ETARGET,
    "EBADENGINE":       RuntimeErrorCode.DEP_INSTALL_ENGINE,
    "engine":           RuntimeErrorCode.DEP_INSTALL_ENGINE,
    "Unsupported engine": RuntimeErrorCode.DEP_INSTALL_ENGINE,
}


def classify_install_error(stderr_lines: list[str]) -> RuntimeErrorCode:
    """
    Scan npm/pnpm/yarn stderr and return the most specific error code.
    Falls back to DEP_INSTALL_FAILED if no known pattern is found.
    """
    combined = "\n".join(stderr_lines)
    for pattern, code in _NPM_CODE_MAP.items():
        if pattern in combined:
            return code
    return RuntimeErrorCode.DEP_INSTALL_FAILED


# ── Human-readable messages keyed by code ────────────────────────────────────

_MESSAGES: dict[RuntimeErrorCode, str] = {
    RuntimeErrorCode.ENV_NODE_MISSING:       "Node.js runtime not found on this host",
    RuntimeErrorCode.ENV_PM_MISSING:         "No JavaScript package manager found (tried pnpm, yarn, bun, npm)",
    RuntimeErrorCode.ENV_PM_BROKEN:          "Package manager binary exits non-zero on --version",
    RuntimeErrorCode.ENV_TMP_NOT_WRITABLE:   "/tmp is not writable — cannot redirect npm cache",
    RuntimeErrorCode.ENV_INVALID_WORKSPACE:  "Workspace directory is missing or unreadable",
    RuntimeErrorCode.DEP_PKG_JSON_MISSING:   "package.json not found in project root",
    RuntimeErrorCode.DEP_PKG_JSON_INVALID:   "package.json is not valid JSON",
    RuntimeErrorCode.DEP_LOCKFILE_MISSING:   "No lockfile found — install will be non-deterministic",
    RuntimeErrorCode.DEP_INSTALL_FAILED:     "Dependency installation failed (non-zero exit)",
    RuntimeErrorCode.DEP_INSTALL_EACCES:     "Permission denied during npm install (EACCES/EPERM)",
    RuntimeErrorCode.DEP_INSTALL_ERESOLVE:   "Dependency version conflict that npm cannot resolve (ERESOLVE)",
    RuntimeErrorCode.DEP_INSTALL_ENOTFOUND:  "npm registry unreachable — network or DNS failure (ENOTFOUND)",
    RuntimeErrorCode.DEP_INSTALL_ETARGET:    "Package version not found in registry (ETARGET)",
    RuntimeErrorCode.DEP_INSTALL_ENGINE:     "Installed Node.js version does not satisfy engine requirement",
    RuntimeErrorCode.DEP_INSTALL_TIMEOUT:    "Dependency installation timed out",
    RuntimeErrorCode.DEP_EXTERNAL_SERVICE:   "Project requires external services (database, cache) not available in sandbox",
    RuntimeErrorCode.EXEC_SCRIPT_MISSING:    "Requested npm script not defined in package.json",
    RuntimeErrorCode.EXEC_SERVER_TIMEOUT:    "Server did not bind its port within the allowed startup window",
    RuntimeErrorCode.EXEC_SERVER_CRASH:      "Server process exited before binding its port",
    RuntimeErrorCode.EXEC_PORT_UNAVAILABLE:  "No free port available — stop other running projects",
    RuntimeErrorCode.EXEC_BUILD_FAILED:      "Build script exited non-zero",
}

_FIXES: dict[RuntimeErrorCode, list[str]] = {
    RuntimeErrorCode.ENV_NODE_MISSING:       ["Install Node.js 18+: https://nodejs.org"],
    RuntimeErrorCode.ENV_PM_MISSING:         ["Install Node.js (includes npm): https://nodejs.org", "Or install pnpm: npm install -g pnpm"],
    RuntimeErrorCode.ENV_PM_BROKEN:          ["Reinstall the package manager or switch to another (pnpm, yarn)"],
    RuntimeErrorCode.ENV_TMP_NOT_WRITABLE:   ["Contact the hosting provider — /tmp must be writable"],
    RuntimeErrorCode.ENV_INVALID_WORKSPACE:  ["Re-upload or regenerate the project"],
    RuntimeErrorCode.DEP_PKG_JSON_MISSING:   ["Add package.json: npm init -y", "Download the ZIP and run locally"],
    RuntimeErrorCode.DEP_PKG_JSON_INVALID:   ["Fix the JSON syntax error in package.json"],
    RuntimeErrorCode.DEP_LOCKFILE_MISSING:   ["Run: npm install  (generates package-lock.json)", "Commit the lockfile"],
    RuntimeErrorCode.DEP_INSTALL_FAILED:     ["Download the ZIP and run locally: npm install && npm run dev"],
    RuntimeErrorCode.DEP_INSTALL_EACCES:     ["Download the ZIP and run locally: npm install && npm run dev", "Or use Docker: docker compose up"],
    RuntimeErrorCode.DEP_INSTALL_ERESOLVE:   ["Run locally: npm install --legacy-peer-deps", "Or fix the version conflict in package.json"],
    RuntimeErrorCode.DEP_INSTALL_ENOTFOUND:  ["Check network connectivity to registry.npmjs.org", "Download the ZIP and install offline: npm install --prefer-offline"],
    RuntimeErrorCode.DEP_INSTALL_ETARGET:    ["Check the package version in package.json — the version may not exist"],
    RuntimeErrorCode.DEP_INSTALL_ENGINE:     ["Upgrade Node.js to match the engine field in package.json"],
    RuntimeErrorCode.DEP_INSTALL_TIMEOUT:    ["Download the ZIP and run locally: npm install && npm run dev"],
    RuntimeErrorCode.DEP_EXTERNAL_SERVICE:   ["Download the ZIP and run: docker compose up"],
    RuntimeErrorCode.EXEC_SCRIPT_MISSING:    ["Add the script to package.json scripts field", "Check the available scripts: npm run"],
    RuntimeErrorCode.EXEC_SERVER_TIMEOUT:    ["Download the ZIP and run locally: npm run dev", "The project may require external services"],
    RuntimeErrorCode.EXEC_SERVER_CRASH:      ["Download the ZIP and run locally to see the full crash log"],
    RuntimeErrorCode.EXEC_PORT_UNAVAILABLE:  ["Stop other running projects in the workspace"],
    RuntimeErrorCode.EXEC_BUILD_FAILED:      ["Download the ZIP and run locally: npm run build"],
}


def message_for(code: RuntimeErrorCode) -> str:
    return _MESSAGES.get(code, str(code))


def fixes_for(code: RuntimeErrorCode) -> list[str]:
    return _FIXES.get(code, ["Download the ZIP and run locally"])


# ── JS-prefixed code aliases (JS001–JS010) ────────────────────────────────────
# Maps the JS error codes from the production spec to the internal enum.

_JS_CODE_MAP: dict[str, RuntimeErrorCode] = {
    "JS001": RuntimeErrorCode.ENV_PM_MISSING,
    "JS002": RuntimeErrorCode.DEP_PKG_JSON_INVALID,
    "JS003": RuntimeErrorCode.DEP_INSTALL_FAILED,
    "JS004": RuntimeErrorCode.EXEC_SCRIPT_MISSING,
    "JS005": RuntimeErrorCode.EXEC_SERVER_CRASH,
    "JS006": RuntimeErrorCode.EXEC_PORT_UNAVAILABLE,
    "JS007": RuntimeErrorCode.EXEC_SERVER_TIMEOUT,
    "JS008": RuntimeErrorCode.ENV_INVALID_WORKSPACE,
    "JS009": RuntimeErrorCode.ENV_NODE_MISSING,
    "JS010": RuntimeErrorCode.DEP_LOCKFILE_MISSING,
}

_INTERNAL_TO_JS: dict[RuntimeErrorCode, str] = {v: k for k, v in _JS_CODE_MAP.items()}


def js_code_for(code: RuntimeErrorCode) -> str:
    """Return the JS-prefixed alias (e.g. 'JS001') or the internal code string."""
    return _INTERNAL_TO_JS.get(code, code.value)


def from_js_code(js_code: str) -> RuntimeErrorCode:
    """Resolve a JS-prefixed alias to the internal RuntimeErrorCode."""
    if js_code in _JS_CODE_MAP:
        return _JS_CODE_MAP[js_code]
    return RuntimeErrorCode(js_code)
