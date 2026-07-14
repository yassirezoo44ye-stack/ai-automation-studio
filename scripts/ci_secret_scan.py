"""
CI secret scan — reuses the same detection patterns already used to scan
marketplace asset uploads (app.marketplace.security.scan_for_secrets), so
this isn't a second, parallel implementation of secret detection.

Scans every git-tracked text file for API-key-shaped strings, private-key
headers, and other credential patterns; fails the build on a real match.
`.env.example` and test/fixture files are excluded since they legitimately
document key *names* or use deliberately-fake, pattern-matching values for
auth-code test coverage, not real secrets.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.marketplace.security import scan_for_secrets  # noqa: E402

_EXCLUDED_PATHS = {".env.example"}
_EXCLUDED_PREFIXES = ("tests/",)
_EXCLUDED_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf",
    ".eot", ".pdf", ".zip",
)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    findings: list[str] = []
    tracked = _tracked_files()

    for rel_path in tracked:
        if rel_path in _EXCLUDED_PATHS:
            continue
        if rel_path.startswith(_EXCLUDED_PREFIXES):
            continue
        if rel_path.endswith(_EXCLUDED_SUFFIXES):
            continue
        path = repo_root / rel_path
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for finding in scan_for_secrets(text):
            findings.append(f"{rel_path}: {finding}")

    if findings:
        print("SECRET SCAN FAILED — possible secrets found:", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)

    print(f"SECRET SCAN PASSED: {len(tracked)} tracked files scanned, no matches.")


if __name__ == "__main__":
    main()
