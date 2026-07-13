"""
Marketplace security checks — run during installation (see installer.py).

Three checks are REAL: secret detection (regex pass over inline asset
content), checksum verification (delegates to assets.py), and permission-
manifest validation (declared capabilities vs. a known allowlist).
ALL_KNOWN_CAPABILITIES is validated here at declaration time and enforced
at runtime by the Agent Sandbox (app/sandbox/) — a worker's network
policy, filesystem mount mode, and secret injection are derived directly
from an installation's already-approved plugin_permissions rows.

Two hooks are STUBS, clearly labeled: malware scanning and dependency
vulnerability scanning. Both return a passing result with a "not configured"
finding today, structured so a real scanner (VirusTotal API, OSV/Snyk
database) can be plugged in later without changing the installer's call
shape.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SecurityScanResult:
    passed: bool
    findings: list[str] = field(default_factory=list)
    stage: str = ""


# ── Secret detection (real) ────────────────────────────────────────────────

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("AWS access key",        re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS secret key",        re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?")),
    ("Private key header",    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("Generic API key",       re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")),
    ("Slack token",           re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("GitHub token",          re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Stripe key",            re.compile(r"(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("Generic bearer/JWT",    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("Anthropic API key",     re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API key",        re.compile(r"sk-[A-Za-z0-9]{20,}")),
)


def scan_for_secrets(text: str) -> list[str]:
    """Regex pass over inline asset content for API-key-shaped strings,
    private-key PEM headers, and other credential patterns. Returns a list
    of human-readable findings (empty if clean)."""
    findings: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"possible {label} found in asset content")
    return findings


# ── Checksum verification (real, delegates to assets.py) ──────────────────

def verify_checksum(content: str, expected_sha256: str) -> bool:
    from app.marketplace.assets import compute_checksum
    return compute_checksum(content) == expected_sha256


# ── Permission manifest (real declaration/validation check) ───────────────

ALL_KNOWN_CAPABILITIES: frozenset[str] = frozenset({
    "network", "filesystem", "database", "shell_exec", "credentials_read",
    "clipboard", "camera", "microphone", "location", "notifications",
    "background_tasks", "third_party_api",
    # Added for Agent Sandbox runtime enforcement — additive only, every
    # capability above keeps validating exactly as before.
    "terminal", "environment_variables", "git_access", "docker_access",
    "browser_automation", "filesystem_write",
})


def check_permission_manifest(
    declared_capabilities: list[str], allowed: frozenset[str] = ALL_KNOWN_CAPABILITIES,
) -> list[str]:
    """Validates an item's declared capability list against the known-
    capability allowlist, flagging anything unrecognized. Declaration-time
    validation only — runtime enforcement of an approved capability set
    happens in app.sandbox (SandboxManager.spawn_worker derives a worker's
    network policy / filesystem mount mode / secret injection from the
    already-approved plugin_permissions rows for that installation)."""
    return [f"unknown declared capability: {cap!r}" for cap in declared_capabilities if cap not in allowed]


# ── Stub hooks — clearly labeled, not implemented this phase ──────────────

def scan_for_malware(asset: dict) -> SecurityScanResult:
    """STUB — no malware scanner is configured. Wiring a real scanner
    (e.g. a VirusTotal-style API) is deferred to a later phase. Structured
    so the installer's call shape doesn't need to change when one lands."""
    return SecurityScanResult(passed=True, findings=["not configured — skipping"], stage="malware_scan")


def scan_dependency_vulnerabilities(item_id: str) -> SecurityScanResult:
    """STUB — no vulnerability database (OSV/Snyk) is wired up yet."""
    return SecurityScanResult(passed=True, findings=["not configured — skipping"], stage="dependency_vuln_scan")
