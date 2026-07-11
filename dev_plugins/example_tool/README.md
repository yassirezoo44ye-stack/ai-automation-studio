# example_tool

A tool plugin scaffolded by `python -m app.plugins.cli generate`.

## Next steps

1. Fill in `register()` (and `unregister()`, if your plugin type needs cleanup) in `plugin.py`.
2. Fill in `required_permissions` in `manifest.json` with any of the declared capabilities your code actually needs (see app/marketplace/security.py's ALL_KNOWN_CAPABILITIES).
3. To publish: bundle manifest.json + plugin.py's contents into a marketplace listing's inline asset as `{"manifest": <manifest.json contents>, "code": "<plugin.py contents>"}` via `POST /marketplace/listings` with `type=plugin`.
