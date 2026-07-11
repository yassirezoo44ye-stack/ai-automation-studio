"""
example_tool — the SDK's shipped reference plugin. A minimal, fully working
TOOL-type plugin: exercises the manifest + register()/unregister() lifecycle
+ Context API (logging + metrics) end to end.

This file is loaded standalone by the Plugin Loader (importlib, isolated
module namespace) — it must not import anything from app.* other than the
Plugin SDK itself (app.plugins.*) and, inside register(), the specific
adapter/registry module it needs. See app/plugins/base.py for the full
PluginBase/PluginContext API.
"""
from app.plugins.base import PluginBase, PluginContext, PluginType


class ExampleToolPlugin(PluginBase):
    plugin_type = PluginType.TOOL

    def register(self, ctx: PluginContext) -> None:
        from app.ai.models import ToolSchema
        from app.plugins.adapters import adapt_tool

        schema = ToolSchema(
            name="example_tool",
            description="Reverses the input string. Demonstrates the Plugin SDK's TOOL type.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "The string to reverse"}},
                "required": ["text"],
            },
        )

        def handler(text: str) -> dict:
            ctx.logger.info("example_tool reversing %d characters", len(text))
            ctx.emit_metric("example_tool.invocations", 1)
            return {"reversed": text[::-1]}

        adapt_tool(schema, handler)

    def unregister(self, ctx: PluginContext) -> None:
        from app.plugins.adapters import unadapt_tool
        unadapt_tool("example_tool")
