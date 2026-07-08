"""
Example plugin — demonstrates auto-loading from the plugins directory.

Drop any .py file here with a register(registry) function and it will
be loaded automatically at startup.  No changes to core required.

Usage:
    python cli.py greet
    python cli.py greet Alice
"""
from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def greet_handler(ctx: CommandContext) -> CommandResult:
    name = ctx.first_arg("world")
    return CommandResult.ok(
        "greet",
        output=f"Hello, {name}!  (loaded from example_greet plugin)",
        data={"name": name, "source": "plugin"},
    )


def register(registry) -> None:
    registry.register(
        "greet",
        greet_handler,
        description="Example plugin: say hello",
        group="demo",
        source="plugin",
        usage="greet [name]",
    )
