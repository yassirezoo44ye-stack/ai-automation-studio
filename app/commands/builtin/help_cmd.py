"""help — list all registered commands."""
from __future__ import annotations

from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def help_handler(ctx: CommandContext) -> CommandResult:
    from app.commands import get_registry
    registry = get_registry()
    specific = ctx.first_arg()
    if specific:
        meta = registry.lookup(specific)
        if meta is None:
            return CommandResult.unknown(specific, registry.names())
        lines = [
            f"Command: {meta.name}",
            f"  {meta.description}",
        ]
        if meta.usage:
            lines.append(f"  Usage: {meta.usage}")
        if meta.aliases:
            lines.append(f"  Aliases: {', '.join(meta.aliases)}")
        lines.append(f"  Source: {meta.source}  Group: {meta.group}")
        return CommandResult.ok("help", output="\n".join(lines),
                                data={"name": meta.name, "description": meta.description})
    text = registry.help_text()
    return CommandResult.ok("help", output=text,
                            data={"commands": registry.names()})


def register(registry) -> None:
    registry.register(
        "help",
        help_handler,
        description="List all commands or describe one: help [command]",
        aliases=["?", "commands"],
        group="system",
        usage="help [command]",
    )
