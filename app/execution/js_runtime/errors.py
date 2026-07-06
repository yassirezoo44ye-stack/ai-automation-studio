"""
Typed runtime error hierarchy for the JavaScript Runtime Executor.

Every failure that can occur during JS project execution is represented
as a concrete exception class. No raw subprocess output or OS exceptions
ever escape this layer to the caller.

Hierarchy:
    JsRuntimeError (base)
    ├── PackageManagerNotFound    — no PM installed on this host
    ├── PackageManagerBroken     — PM binary exists but fails --version
    ├── ScriptNotFound           — requested script missing from package.json
    ├── PackageJsonMissing       — no package.json in workspace
    ├── NodeModulesMissing       — node_modules absent and install failed
    ├── RuntimeUnavailable       — node executable missing
    ├── ExecutionTimeout         — process exceeded wall-clock limit
    └── ExecutionFailed          — process exited non-zero
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JsRuntimeError(Exception):
    """Base class for all runtime executor errors."""
    message: str
    fix: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    @property
    def error_type(self) -> str:
        return type(self).__name__

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class PackageManagerNotFound(JsRuntimeError):
    """No package manager (npm/pnpm/yarn/bun) is installed or reachable."""
    tried: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fix:
            tried_str = ", ".join(self.tried) if self.tried else "npm, pnpm, yarn, bun"
            self.fix = [
                f"No package manager found. Tried: {tried_str}",
                "Install Node.js (includes npm): https://nodejs.org",
                "Or install pnpm: npm install -g pnpm",
                "Download the ZIP and run locally: npm install && npm run dev",
            ]
        super().__post_init__()


@dataclass
class PackageManagerBroken(JsRuntimeError):
    """Package manager binary exists but exits non-zero on --version."""
    pm_name: str = ""
    last_output: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fix:
            self.fix = [
                f"{self.pm_name} binary is present but broken (non-zero on --version).",
                f"Reinstall {self.pm_name} or switch to another package manager.",
                "Download the ZIP and run locally.",
            ]
        super().__post_init__()


@dataclass
class ScriptNotFound(JsRuntimeError):
    """Requested npm script does not exist in package.json."""
    script: str = ""
    available: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fix:
            avail = ", ".join(self.available) if self.available else "none"
            self.fix = [
                f'Script "{self.script}" not found in package.json.',
                f"Available scripts: {avail}",
                "Add the script to package.json or use one of the available ones.",
            ]
        super().__post_init__()


@dataclass
class PackageJsonMissing(JsRuntimeError):
    """No package.json found in the workspace root."""

    def __post_init__(self) -> None:
        if not self.fix:
            self.fix = [
                "No package.json found in the project root.",
                "Run: npm init -y  to create one.",
            ]
        super().__post_init__()


@dataclass
class NodeModulesMissing(JsRuntimeError):
    """node_modules is absent and install failed."""
    install_output: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fix:
            self.fix = [
                "Dependencies could not be installed.",
                "Download the ZIP and run: npm install  locally.",
            ]
        super().__post_init__()


@dataclass
class RuntimeUnavailable(JsRuntimeError):
    """node executable is not present on the host."""

    def __post_init__(self) -> None:
        if not self.fix:
            self.fix = [
                "Node.js runtime not found.",
                "Install Node.js 18+: https://nodejs.org",
            ]
        super().__post_init__()


@dataclass
class ExecutionTimeout(JsRuntimeError):
    """Process exceeded the configured wall-clock timeout."""
    timeout_seconds: float = 0.0
    script: str = ""

    def __post_init__(self) -> None:
        if not self.fix:
            self.fix = [
                f'Script "{self.script}" timed out after {self.timeout_seconds:.0f}s.',
                "The project may depend on external services not available in the sandbox.",
                "Download the ZIP and run locally.",
            ]
        super().__post_init__()


@dataclass
class ExecutionFailed(JsRuntimeError):
    """Process exited with non-zero exit code."""
    exit_code: int = -1
    script: str = ""
    stderr_tail: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fix:
            self.fix = [
                f'Script "{self.script}" failed with exit code {self.exit_code}.',
                "Check the output above for error details.",
                "Download the ZIP and debug locally: npm run " + self.script,
            ]
        super().__post_init__()


@dataclass
class LockfileConflict(JsRuntimeError):
    """Multiple lockfiles found — ambiguous package manager."""
    found: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fix:
            self.fix = [
                f"Multiple lockfiles found: {', '.join(self.found)}",
                "Keep only the lockfile for your intended package manager.",
                "Delete the others and commit the change.",
            ]
        super().__post_init__()
