"""
CI release helper — runs only after a successful post-deploy smoke test on
main. Reads commits since the last tag, buckets them by this repo's existing
conventional-commit prefix convention (feat/fix/test/docs), bumps a patch
version, updates CHANGELOG.md, and prints the new tag + release notes for
the calling workflow step to create the tag and GitHub Release with.

Does not push or create the tag itself — keeps side effects (git push, `gh
release create`) visible in the workflow YAML rather than hidden in this
script.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

_PREFIXES = {
    "feat": "Features",
    "fix": "Fixes",
    "test": "Tests",
    "docs": "Docs",
}


def _run(*args: str) -> str:
    return subprocess.run(
        args, cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _last_tag() -> str:
    try:
        return _run("git", "describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        return "v0.0.0"


def _next_version(last_tag: str) -> str:
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(-rc\d+)?$", last_tag)
    if not m:
        return "v1.0.0"
    major, minor, patch, rc = m.groups()
    if rc:
        return f"v{major}.{minor}.{patch}"
    return f"v{major}.{minor}.{int(patch) + 1}"


def _bucket_commits(last_tag: str) -> dict[str, list[str]]:
    try:
        log = _run("git", "log", f"{last_tag}..HEAD", "--pretty=format:%s")
    except subprocess.CalledProcessError:
        log = _run("git", "log", "--pretty=format:%s")
    buckets: dict[str, list[str]] = {label: [] for label in _PREFIXES.values()}
    buckets["Other"] = []
    for line in log.splitlines():
        if not line.strip():
            continue
        m = re.match(r"(\w+):\s*(.+)", line)
        if m and m.group(1) in _PREFIXES:
            buckets[_PREFIXES[m.group(1)]].append(m.group(2))
        else:
            buckets["Other"].append(line)
    return buckets


def main() -> None:
    last_tag = _last_tag()
    new_version = _next_version(last_tag)
    buckets = _bucket_commits(last_tag)

    lines = [f"## {new_version}", ""]
    for label, items in buckets.items():
        if not items:
            continue
        lines.append(f"### {label}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    notes = "\n".join(lines).strip() or f"## {new_version}\n\nNo notable changes."

    existing = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n"
    CHANGELOG.write_text(existing.rstrip() + "\n\n" + notes + "\n", encoding="utf-8")

    # Machine-readable output for the calling workflow step (modern GITHUB_OUTPUT
    # file, not the deprecated ::set-output:: command).
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"version={new_version}\n")
    print(f"NEW_VERSION={new_version}")
    notes_path = REPO_ROOT / ".release-notes.md"
    notes_path.write_text(notes, encoding="utf-8")
    print(f"Wrote release notes to {notes_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        # Local dry-run: print what would happen without touching CHANGELOG.md.
        last_tag = _last_tag()
        print("Last tag:", last_tag)
        print("Next version:", _next_version(last_tag))
        print("Buckets:", _bucket_commits(last_tag))
    else:
        main()
