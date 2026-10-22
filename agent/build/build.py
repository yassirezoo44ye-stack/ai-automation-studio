"""
Build script for flow-agent.exe (Windows).

Usage:
    py -3.11 agent/build/build.py

Requires PyInstaller: pip install pyinstaller
Requires the agent dependencies: pip install -r agent/requirements.txt

Output: dist/flow-agent.exe (single-file executable for Windows)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HERE  = Path(__file__).resolve().parent
_SPEC  = _HERE / "flow_agent.spec"
_DIST  = _HERE.parent.parent / "dist"


def main() -> int:
    if sys.platform != "win32":
        print("Warning: Building on non-Windows — the resulting exe may not work.", file=sys.stderr)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(_DIST),
        "--workpath", str(_HERE / "pyinstaller_work"),
        "--noconfirm",
        str(_SPEC),
    ]
    result = subprocess.run(cmd, cwd=str(_HERE.parent.parent))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
