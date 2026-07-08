#!/usr/bin/env python3
"""
AI Automation Studio — Command-Line Interface

Unified entry point for all commands.

Usage:
    python cli.py "run ./my-project"
    python cli.py run ./my-project --port=3000
    python cli.py build ./my-project --output=./dist
    python cli.py inspect workspace ./my-project
    python cli.py modify env --key=PORT --value=4000
    python cli.py modify register greet ./plugins/greet.py
    python cli.py help
    python cli.py help run

If a single quoted argument is passed, it is treated as a raw command string.
Otherwise, all arguments are joined and parsed normally.

The CLI mirrors exactly what the REST API does — same registry, same runner.
"""
from __future__ import annotations

import asyncio
import sys

# Force UTF-8 on Windows terminals that default to cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _raw_input() -> str:
    args = sys.argv[1:]
    if not args:
        return "help"
    # Single quoted argument → raw string
    if len(args) == 1 and not args[0].startswith("-"):
        return args[0]
    return " ".join(args)


async def _main() -> int:
    from app.kernel import get_kernel
    kernel = get_kernel()      # boot() is called inside get_kernel()
    raw    = _raw_input()
    result = await kernel.execute(raw, caller="cli")

    print(result.to_cli_text())

    if result.data:
        import json
        # Only print JSON data if it's non-trivial (more than a commands list)
        keys = set(result.data.keys()) - {"commands"}
        if keys:
            print()
            print(json.dumps(result.data, indent=2, default=str))

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
