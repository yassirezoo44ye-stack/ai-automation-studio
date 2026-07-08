"""
test_gen plugin — auto-loaded from the plugins directory.
"""
from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def test_gen_handler(ctx: CommandContext) -> CommandResult:
    arg = ctx.first_arg("world")
    return CommandResult.ok("test_gen", output=f"Hello from test_gen: {arg}")


def register(registry) -> None:
    registry.register(
        "test_gen",
        test_gen_handler,
        description="test_gen — auto-generated plugin",
        group="plugin",
        source="plugin",
        usage="test_gen [arg]",
    )
