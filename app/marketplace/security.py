"""
Marketplace security checks — run during installation (see installer.py).

Five checks are real: secret detection (regex pass over inline asset
content), checksum verification (delegates to assets.py), permission-
manifest validation (declared capabilities vs. a known allowlist), a
static dangerous-code-construct scan (scan_for_malware), and a dependency
vulnerability check against OSV.dev (scan_dependency_vulnerabilities).
ALL_KNOWN_CAPABILITIES is validated here at declaration time and enforced
at runtime by the Agent Sandbox (app/sandbox/) — a worker's network
policy, filesystem mount mode, and secret injection are derived directly
from an installation's already-approved plugin_permissions rows.

scan_for_malware and scan_dependency_vulnerabilities were previously
stubs that unconditionally returned passed=True with a "not configured"
finding — a false sense of security, since the installer logged whatever
they returned as if a real check had run. Neither is a drop-in
replacement for a commercial scanner (VirusTotal-style binary-signature
AV, a paid SCA tool): plugins here are Python/JS *source*, not compiled
binaries, so a signature-based AV scanner isn't the right tool anyway —
a static pattern scan for known-dangerous constructs (the same class of
check bandit's B102/B307/B605/B301 rules perform) is the more relevant
proxy. Dependency scanning uses OSV.dev's free, keyless batch API against
whatever pinned package versions can be parsed out of an item's own
inline assets (requirements.txt-shaped lines, package.json
dependencies/devDependencies) — there's no separate "declare your
external packages" manifest field, so items that don't ship anything
parseable simply have nothing to check. Both remain non-blocking
findings today (see installer.py) — a match is logged, not rejected.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


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


# ── Malware scan (real: static dangerous-construct pattern scan) ──────────

_DANGEROUS_CODE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("eval() call — arbitrary code execution",              re.compile(r"\beval\s*\(")),
    ("exec() call — arbitrary code execution",              re.compile(r"\bexec\s*\(")),
    ("os.system() call — arbitrary shell execution",        re.compile(r"\bos\.system\s*\(")),
    ("os.popen() call — shell execution",                   re.compile(r"\bos\.popen\s*\(")),
    ("subprocess call with shell=True — shell injection risk", re.compile(r"\bshell\s*=\s*True\b")),
    ("pickle.load(s)() — arbitrary code execution on untrusted data", re.compile(r"\bpickle\.loads?\s*\(")),
    ("marshal.load(s)() — arbitrary code execution on untrusted data", re.compile(r"\bmarshal\.loads?\s*\(")),
    ("dynamic __import__() call",                           re.compile(r"__import__\s*\(")),
    ("compile() building executable code from a string",    re.compile(r"\bcompile\s*\(")),
)


def scan_for_malware(asset: dict) -> SecurityScanResult:
    """Static pattern scan for dangerous code constructs across the item's
    inline asset content: eval/exec, shell execution, unpickling untrusted
    data, and similar arbitrary-code-execution primitives — the same class
    of check bandit's B102/B307/B605/B301 rules perform. Plugins here are
    Python/JS source, not compiled binaries, so this is the relevant proxy
    for "malware scanning" in this ecosystem, not a signature-based AV
    scan. It cannot catch cleverly obfuscated malicious code — only these
    easily-recognizable dangerous primitives — and a match is not proof of
    malicious intent (some legitimate plugins have real reasons to use
    eval/subprocess); it's a signal for a human reviewer, which is exactly
    why this stays a non-blocking finding (see installer.py)."""
    findings: list[str] = []
    for a in asset.get("assets", []) or []:
        if a.get("asset_type") != "inline" or not a.get("content"):
            continue
        content = a["content"]
        for label, pattern in _DANGEROUS_CODE_PATTERNS:
            if pattern.search(content):
                findings.append(f"{label} (asset {a.get('id', '?')})")
    return SecurityScanResult(
        passed=not findings,
        findings=findings or ["no dangerous code constructs detected"],
        stage="malware_scan",
    )


# ── Dependency vulnerability scan (real: OSV.dev) ──────────────────────────

_PYPI_PIN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_.\-]*)\s*==\s*([0-9][A-Za-z0-9_.\-]*)\s*$")


def _extract_declared_dependencies(assets: list[dict]) -> list[dict]:
    """Best-effort extraction of pinned package declarations from an
    item's own inline assets — requirements.txt-shaped `name==version`
    lines (PyPI), or a package.json `dependencies`/`devDependencies`
    block (npm). There's no separate "declare your external packages"
    manifest field; this reuses whatever inline assets an item already
    ships. Version ranges (^, ~, >=) are skipped, not guessed, since OSV
    needs one resolved version to check against."""
    found: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(ecosystem: str, name: str, version: str) -> None:
        key = (ecosystem, name.lower(), version)
        if key not in seen:
            seen.add(key)
            found.append({"ecosystem": ecosystem, "name": name, "version": version})

    for a in assets:
        if a.get("asset_type") != "inline" or not a.get("content"):
            continue
        content = a["content"]

        for line in content.splitlines():
            m = _PYPI_PIN_RE.match(line)
            if m:
                _add("PyPI", m.group(1), m.group(2))

        stripped = content.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            for key in ("dependencies", "devDependencies"):
                deps = data.get(key)
                if not isinstance(deps, dict):
                    continue
                for name, version in deps.items():
                    if not isinstance(version, str):
                        continue
                    v = version.lstrip("^~=> ").strip()
                    if v and v[0].isdigit():
                        _add("npm", name, v)

    return found


async def scan_dependency_vulnerabilities(
    item_id: str, assets: list[dict] | None = None,
) -> SecurityScanResult:
    """Queries OSV.dev's free, keyless batch API (https://osv.dev) for
    known vulnerabilities affecting pinned dependency versions declared in
    the item's own assets (see _extract_declared_dependencies). Items with
    no parseable pinned-dependency content simply have nothing to check —
    that's an honest "nothing found," not a stubbed pass. Never raises or
    blocks on a network failure: OSV.dev being unreachable must not be
    indistinguishable from "definitely no vulnerabilities" (the finding
    says so explicitly), and a real finding stays a WARNING today, same as
    scan_for_malware (see installer.py)."""
    deps = _extract_declared_dependencies(assets or [])
    if not deps:
        return SecurityScanResult(
            passed=True,
            findings=["no pinned dependency declarations found in item assets — nothing to check"],
            stage="dependency_vuln_scan",
        )

    import httpx
    queries = [
        {"package": {"name": d["name"], "ecosystem": d["ecosystem"]}, "version": d["version"]}
        for d in deps
    ]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://api.osv.dev/v1/querybatch", json={"queries": queries})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("OSV.dev dependency scan unavailable for %s: %s", item_id, exc)
        return SecurityScanResult(
            passed=True,
            findings=[f"dependency vulnerability check skipped — OSV.dev unreachable: {exc}"],
            stage="dependency_vuln_scan",
        )

    findings: list[str] = []
    for dep, result in zip(deps, data.get("results", [])):
        for v in (result.get("vulns") or []):
            findings.append(f"{dep['name']}@{dep['version']} ({dep['ecosystem']}): {v.get('id', 'unknown')}")

    return SecurityScanResult(
        passed=not findings,
        findings=findings or [f"checked {len(deps)} declared dependency(ies) against OSV.dev — none flagged"],
        stage="dependency_vuln_scan",
    )
