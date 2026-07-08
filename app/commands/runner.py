"""
CommandRunner — the central command processor.

Responsibilities:
  1. Parse raw text input into (command, args, flags)
  2. Look up the command in the CommandRegistry
  3. Build a CommandContext
  4. Dispatch to the handler
  5. Return a CommandResult — never raises

The runner is the single point of failure for all command execution.
It isolates handler crashes so one bad plugin never takes down the system.

Entry points:
    await runner.execute("run ./my-project --port=3000")
    await runner.execute_parsed("run", ["./my-project"], {"port": "3000"})
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import Optional

from app.commands.context import CommandContext
from app.commands.registry import CommandRegistry
from app.commands.result import CommandResult

log = logging.getLogger(__name__)


class CommandRunner:
    """
    Stateless dispatcher.  Instantiate once per process; call execute() freely.

    Usage:
        runner = CommandRunner(registry)
        result = await runner.execute("run ./project --port=3000")
        print(result.to_cli_text())
    """

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute(
        self,
        raw: str,
        *,
        caller: str = "cli",
        user_id: Optional[str] = None,
        runtime_state: dict | None = None,
    ) -> CommandResult:
        """
        Parse raw text and execute the command.
        Never raises — all errors are captured in CommandResult.
        """
        try:
            command, args, flags = _parse(raw.strip())
        except Exception as exc:
            return CommandResult.fail("(parse)", f"Could not parse input: {exc}", "PARSE_ERROR")

        return await self.execute_parsed(
            command, args, flags,
            raw_input=raw, caller=caller,
            user_id=user_id, runtime_state=runtime_state,
        )

    async def execute_parsed(
        self,
        command: str,
        args: list[str],
        flags: dict[str, str],
        *,
        raw_input: str = "",
        caller: str = "cli",
        user_id: Optional[str] = None,
        runtime_state: dict | None = None,
    ) -> CommandResult:
        """
        Execute an already-parsed command.  Never raises.
        """
        if not command:
            return CommandResult.fail("(empty)", "No command provided.", "EMPTY_COMMAND",
                                     suggestions=["Run 'help' to see available commands."])

        meta = self._registry.lookup(command)
        if meta is None:
            return CommandResult.unknown(command, self._registry.names())

        # Resolve workspace from --workspace flag or first positional arg
        ws_raw = flags.get("workspace") or flags.get("w") or (args[0] if args else "")
        workspace: Optional[Path] = None
        if ws_raw:
            p = Path(ws_raw).expanduser().resolve()
            workspace = p if p.exists() else Path(ws_raw)

        ctx = CommandContext(
            command     = command,
            args        = args,
            flags       = flags,
            raw_input   = raw_input,
            workspace   = workspace,
            project_id  = flags.get("project", flags.get("p", "")),
            execution_id= flags.get("execution", flags.get("e")),
            caller      = caller,
            user_id     = user_id,
            runtime_state = runtime_state or {},
        )

        log.info("command: %s args=%s flags=%s caller=%s", command, args, flags, caller)
        t0 = time.monotonic()
        try:
            result = await meta.handler(ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("command handler %s raised: %s", command, exc)
            result = CommandResult.fail(
                command,
                f"Command '{command}' raised an unexpected error: {exc}",
                error_code="HANDLER_EXCEPTION",
                suggestions=[
                    "This is a bug — the system is still running.",
                    "Run 'help' to see if a different command serves your need.",
                ],
            )
        result.command    = command
        result.duration_ms = (time.monotonic() - t0) * 1000
        return result


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse(raw: str) -> tuple[str, list[str], dict[str, str]]:
    """
    Parse a raw command string into (command, positional_args, flags).

    Formats supported:
        run ./project --port=3000 --verbose
        build ./project --output=dist
        modify --file=app.py --action=add_route
    """
    if not raw:
        return "", [], {}

    try:
        tokens = shlex.split(raw)
    except ValueError:
        # shlex fails on unmatched quotes — fall back to simple split
        tokens = raw.split()

    if not tokens:
        return "", [], {}

    command = tokens[0].lower()
    args: list[str] = []
    flags: dict[str, str] = {}

    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            key_val = tok[2:]
            if "=" in key_val:
                k, v = key_val.split("=", 1)
                flags[k] = v
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                flags[key_val] = tokens[i + 1]
                i += 1
            else:
                flags[key_val] = "true"   # boolean flag
        elif tok.startswith("-") and len(tok) == 2:
            key = tok[1]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                flags[key] = tokens[i + 1]
                i += 1
            else:
                flags[key] = "true"
        else:
            args.append(tok)
        i += 1

    return command, args, flags
