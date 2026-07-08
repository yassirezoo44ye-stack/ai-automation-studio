"""
CommandRegistry — central register of all available commands.

Usage:
    registry = CommandRegistry()
    registry.register("run", run_handler, description="Run a project")
    handler, meta = registry.lookup("run")

Commands are plain async callables:
    async def handler(ctx: CommandContext) -> CommandResult

Each registration stores:
    - name        (str)       — the command keyword
    - handler     (callable)  — async function(ctx) → CommandResult
    - description (str)       — shown in help output
    - aliases     (list[str]) — alternative names
    - group       (str)       — grouping for help display
    - source      (str)       — "builtin" | "plugin" | "api"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from app.commands.context import CommandContext
from app.commands.result import CommandResult

log = logging.getLogger(__name__)

Handler = Callable[[CommandContext], Coroutine[Any, Any, CommandResult]]


@dataclass
class CommandMeta:
    name: str
    handler: Handler
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    group: str = "general"
    source: str = "builtin"     # "builtin" | "plugin" | "dynamic"
    usage: str = ""             # e.g. "run <workspace> [--port=3000]"

    def matches(self, name: str) -> bool:
        return name == self.name or name in self.aliases


class CommandRegistry:
    """
    Central registry of all executable commands.

    Thread-safe for reads; register() should be called at startup only.
    """

    def __init__(self) -> None:
        self._commands: dict[str, CommandMeta] = {}   # name → meta
        self._aliases:  dict[str, str] = {}           # alias → canonical name

    # ── Registration ─────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        handler: Handler,
        *,
        description: str = "",
        aliases: list[str] | None = None,
        group: str = "general",
        source: str = "builtin",
        usage: str = "",
        override: bool = False,
    ) -> None:
        """
        Register a command.  Raises ValueError on duplicate unless override=True.
        """
        if name in self._commands and not override:
            raise ValueError(
                f"Command '{name}' is already registered "
                f"(source={self._commands[name].source}). "
                f"Pass override=True to replace it."
            )
        meta = CommandMeta(
            name=name, handler=handler, description=description,
            aliases=aliases or [], group=group, source=source, usage=usage,
        )
        self._commands[name] = meta
        for alias in (aliases or []):
            self._aliases[alias] = name
        log.debug("registered command: %s (source=%s)", name, source)

    def unregister(self, name: str) -> bool:
        """Remove a command. Returns True if it existed."""
        meta = self._commands.pop(name, None)
        if meta is None:
            return False
        for alias in meta.aliases:
            self._aliases.pop(alias, None)
        return True

    # ── Lookup ────────────────────────────────────────────────────────────────

    def lookup(self, name: str) -> Optional[CommandMeta]:
        """Return the CommandMeta for name (or its alias), or None."""
        canonical = self._aliases.get(name, name)
        return self._commands.get(canonical)

    def names(self) -> list[str]:
        return sorted(self._commands.keys())

    def all(self) -> list[CommandMeta]:
        return list(self._commands.values())

    def by_group(self) -> dict[str, list[CommandMeta]]:
        groups: dict[str, list[CommandMeta]] = {}
        for meta in self._commands.values():
            groups.setdefault(meta.group, []).append(meta)
        return dict(sorted(groups.items()))

    # ── Introspection ─────────────────────────────────────────────────────────

    def help_text(self) -> str:
        lines: list[str] = ["Available commands:", ""]
        for group, commands in self.by_group().items():
            lines.append(f"  {group.upper()}")
            for meta in sorted(commands, key=lambda m: m.name):
                usage = f"  {meta.usage}" if meta.usage else ""
                lines.append(f"    {meta.name:<16} {meta.description}{usage}")
            lines.append("")
        return "\n".join(lines)
