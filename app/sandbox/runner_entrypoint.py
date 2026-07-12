"""
Runs INSIDE a sandbox worker (Docker container or subprocess) — never
imported by the main app process. Standard library only (no third-party
deps, no `app` package required to be installed) so this runs unmodified
inside a bare `python:3.11-slim` container with nothing pip-installed.

Expects two files to already exist in its working directory (placed there
by SandboxManager before the worker starts — see app/sandbox/manager.py):
  plugin_base.py   — a byte-identical copy of app/plugins/base.py
  plugin_code.py   — the plugin's own source (the marketplace bundle's "code")
and one environment variable:
  AXON_ENTRY_POINT — "module:ClassName", e.g. "plugin_code:ExampleToolPlugin"
                      (matches the manifest's entry_point, module part
                      always rewritten to "plugin_code" by the manager)

Protocol: see app/sandbox/protocol.py's module docstring. This process is
single-threaded and handles exactly one request from the main process at
a time — a `context_rpc` request it sends mid-dispatch blocks for its
reply on the same stdin, which is safe because the main process never
sends a second top-level request before the first one's response (or an
interleaved context_rpc round-trip) completes.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types
import uuid
from pathlib import Path

# plugin_base.py / plugin_code.py are placed in the worker's isolated
# workspace by SandboxManager, which also sets this process's cwd to that
# workspace root (both backends: process cwd=, Docker WORKDIR=/workspace)
# — NOT next to this script, which lives in the repo/image, not the
# per-worker workspace.
_WORKDIR = Path.cwd()


# ── Wire channel ─────────────────────────────────────────────────────────

class _Channel:
    def send(self, payload: dict) -> None:
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    def read_line(self) -> dict:
        line = sys.stdin.readline()
        if not line:
            raise EOFError("stdin closed")
        return json.loads(line)

    def context_rpc(self, method: str, args: list, kwargs: dict):
        """Blocking round-trip back to the main process — used by the
        PluginContext shim below for get_secret/storage_*/emit_event/
        emit_metric, none of which are servable inside this isolated
        process (no DB pool, no app package)."""
        req_id = uuid.uuid4().hex
        self.send({"id": req_id, "call": "context_rpc", "method": method, "args": args, "kwargs": kwargs})
        resp = self.read_line()
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or f"context_rpc {method} failed")
        return resp.get("result")


_channel = _Channel()

# name -> callable, or (obj, default_method_name) for agents/providers
_registered: dict[str, object] = {}
_registrations: list[dict] = []


# ── PluginBase / PluginContext (real module, RPC-shimmed I/O) ──────────────

def _load_plugin_base_module():
    spec = importlib.util.spec_from_file_location("_axon_plugin_base", _WORKDIR / "plugin_base.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_axon_plugin_base"] = module
    spec.loader.exec_module(module)

    ctx_cls = module.PluginContext

    def get_secret(self, key):
        return _channel.context_rpc("get_secret", [key], {})

    def set_secret(self, key, value):
        return _channel.context_rpc("set_secret", [key, value], {})

    def storage_get(self, key):
        return _channel.context_rpc("storage_get", [key], {})

    def storage_put(self, key, value):
        return _channel.context_rpc("storage_put", [key, value], {})

    def storage_delete(self, key):
        return _channel.context_rpc("storage_delete", [key], {})

    def emit_event(self, type_, data):
        return _channel.context_rpc("emit_event", [type_, data], {})

    def emit_metric(self, name, value, **tags):
        return _channel.context_rpc("emit_metric", [name, value], tags)

    # These are async on the real PluginContext; the worker's own dispatch
    # loop is sync (see run_forever below, driven via asyncio.run per
    # request), so keep them async here too — context_rpc itself is a
    # blocking stdio round-trip either way (there is nothing else this
    # single-threaded worker could be doing concurrently).
    async def _get_secret(self, key):
        return get_secret(self, key)

    async def _set_secret(self, key, value):
        return set_secret(self, key, value)

    async def _storage_get(self, key):
        return storage_get(self, key)

    async def _storage_put(self, key, value):
        return storage_put(self, key, value)

    async def _storage_delete(self, key):
        return storage_delete(self, key)

    async def _emit_event(self, type_, data):
        return emit_event(self, type_, data)

    ctx_cls.get_secret = _get_secret
    ctx_cls.set_secret = _set_secret
    ctx_cls.storage_get = _storage_get
    ctx_cls.storage_put = _storage_put
    ctx_cls.storage_delete = _storage_delete
    ctx_cls.emit_event = _emit_event
    ctx_cls.emit_metric = emit_metric
    return module


# ── app.plugins.adapters shim ───────────────────────────────────────────────

def _install_ai_models_shim() -> None:
    """A plugin's register() commonly does `from app.ai.models import
    ToolSchema` (the real app.ai.models is not importable here — no `app`
    package present). Only ToolSchema is shimmed: it's the one model class
    a TOOL-type plugin's register() needs, matching what's actually used
    by the shipped dev_plugins/example_tool/plugin.py reference plugin."""
    shim = types.ModuleType("app.ai.models")

    class ToolSchema:
        def __init__(self, name, description, parameters):
            self.name = name
            self.description = description
            self.parameters = parameters

        def model_dump(self):
            return {"name": self.name, "description": self.description, "parameters": self.parameters}

    shim.ToolSchema = ToolSchema
    sys.modules.setdefault("app.ai", types.ModuleType("app.ai"))
    sys.modules["app.ai.models"] = shim


def _install_adapters_shim() -> None:
    shim = types.ModuleType("app.plugins.adapters")

    def _schema_to_json(schema):
        if hasattr(schema, "model_dump"):
            return schema.model_dump()
        return schema

    def adapt_tool(schema, fn):
        name = schema.name if hasattr(schema, "name") else schema["name"]
        _registered[name] = fn
        _registrations.append({"type": "tool", "name": name, "schema": _schema_to_json(schema)})

    def unadapt_tool(name):
        return _registered.pop(name, None) is not None

    def adapt_workflow_node(name, fn):
        _registered[name] = fn
        _registrations.append({"type": "workflow_node", "name": name})

    def unadapt_workflow_node(name):
        return _registered.pop(name, None) is not None

    def adapt_agent(agent):
        # "execute" (not "run") — inside the worker, an AGENT-type plugin's
        # object only needs the agent's own core logic method, not the full
        # EvolvableAgent base (validate/timing/health_check machinery,
        # which the main-process WorkerProxyAgent already supplies for
        # free by properly subclassing the real EvolvableAgent — see
        # app/plugins/adapters.py). A plugin-authored agent inside the
        # worker is just `class MyAgent: name = "..."; async def
        # execute(self, **kwargs): ...` — no AgentContext/AgentResult
        # porting needed.
        name = getattr(agent, "name", agent.__class__.__name__)
        _registered[name] = (agent, "execute")
        _registrations.append({"type": "agent", "name": name})

    def unadapt_agent(name):
        return _registered.pop(name, None) is not None

    _counter = {"event": 0}

    def adapt_event_listener(pattern, handler):
        name = f"__event_listener_{_counter['event']}"
        _counter["event"] += 1
        _registered[name] = handler
        _registrations.append({"type": "event_listener", "name": name, "pattern": pattern})

    def unadapt_event_listener(pattern, handler):
        for name, obj in list(_registered.items()):
            if obj is handler:
                del _registered[name]
                return

    def adapt_memory_provider(provider_id, provider):
        _registered[provider_id] = (provider, None)
        _registrations.append({"type": "memory_provider", "name": provider_id})

    def unadapt_memory_provider(provider_id):
        return _registered.pop(provider_id, None) is not None

    def adapt_storage_provider(provider_id, provider):
        _registered[provider_id] = (provider, None)
        _registrations.append({"type": "storage_provider", "name": provider_id})

    def unadapt_storage_provider(provider_id):
        return _registered.pop(provider_id, None) is not None

    def adapt_auth_provider(provider_id, provider):
        _registered[provider_id] = (provider, None)
        _registrations.append({"type": "auth_provider", "name": provider_id})

    def unadapt_auth_provider(provider_id):
        return _registered.pop(provider_id, None) is not None

    def adapt_ai_provider(provider_id, provider):
        _registered[provider_id] = (provider, None)
        _registrations.append({"type": "ai_provider", "name": provider_id})

    def unadapt_ai_provider(provider_id):
        return _registered.pop(provider_id, None) is not None

    for fn in (adapt_tool, unadapt_tool, adapt_workflow_node, unadapt_workflow_node,
               adapt_agent, unadapt_agent, adapt_event_listener, unadapt_event_listener,
               adapt_memory_provider, unadapt_memory_provider,
               adapt_storage_provider, unadapt_storage_provider,
               adapt_auth_provider, unadapt_auth_provider,
               adapt_ai_provider, unadapt_ai_provider):
        setattr(shim, fn.__name__, fn)

    sys.modules["app.plugins.adapters"] = shim
    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules.setdefault("app.plugins", types.ModuleType("app.plugins"))


def _load_plugin_code(base_module):
    spec = importlib.util.spec_from_file_location("plugin_code", _WORKDIR / "plugin_code.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plugin_code"] = module
    # Plugin code imports `from app.plugins.base import PluginBase, ...` —
    # route that at the real, already-loaded base module's classes.
    sys.modules["app.plugins.base"] = base_module
    spec.loader.exec_module(module)

    entry_point = os.environ["AXON_ENTRY_POINT"]
    _, class_name = entry_point.split(":", 1)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(f"entry_point class {class_name!r} not found in plugin_code.py")
    if not (isinstance(cls, type) and issubclass(cls, base_module.PluginBase)):
        raise TypeError(f"entry_point class {class_name!r} is not a PluginBase subclass")
    return cls()


async def _call_lifecycle(instance, ctx, method_name, args, kwargs):
    method = getattr(instance, method_name)
    # health_check() is the one lifecycle hook that takes no ctx argument
    # (app/plugins/base.py: `def health_check(self) -> PluginHealth`) —
    # every other hook is `async def hook(self, ctx, ...)`.
    if method_name == "health_check":
        result = method(*args, **kwargs)
    else:
        result = method(ctx, *args, **kwargs)
    if asyncio.iscoroutine(result):
        result = await result
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    return result


async def _call_invoke(name, args, kwargs):
    target = _registered.get(name)
    if target is None:
        raise KeyError(f"no handler registered under {name!r}")
    if isinstance(target, tuple):
        obj, default_method = target
        method_name = kwargs.pop("_sub_method", None) or default_method
        if method_name is None:
            raise ValueError(f"invoke on {name!r} requires _sub_method")
        fn = getattr(obj, method_name)
    else:
        fn = target
    result = fn(*args, **kwargs)
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def main() -> None:
    # Loading the plugin's own code (syntax errors, missing/wrong entry
    # point class, etc.) must NOT crash this process before it can even
    # respond to the main process's first request — that would make the
    # caller see a bare closed pipe (WorkerCrashedError) instead of a
    # clean, typed failure. Any load failure here is deferred: the worker
    # stays alive and reports the error on every subsequent request
    # instead of exiting.
    load_error: str | None = None
    base_module = None
    instance = None
    try:
        base_module = _load_plugin_base_module()
        _install_ai_models_shim()
        _install_adapters_shim()
        instance = _load_plugin_code(base_module)
    except Exception as exc:  # noqa: BLE001 — must report, never crash before responding
        load_error = f"{type(exc).__name__}: {exc}"

    installation_id = os.environ.get("AXON_INSTALLATION_ID", "")
    plugin_id = os.environ.get("AXON_PLUGIN_ID", "")
    org_id = os.environ.get("AXON_ORG_ID") or None
    config = json.loads(os.environ.get("AXON_PLUGIN_CONFIG", "{}"))

    import logging
    ctx = None
    if base_module is not None:
        ctx = base_module.PluginContext(
            plugin_id=plugin_id, installation_id=installation_id, organization_id=org_id,
            config=config, logger=logging.getLogger(f"plugin.{plugin_id}"),
        )

    while True:
        try:
            req = _channel.read_line()
        except EOFError:
            return

        req_id, call, method, args, kwargs = (
            req.get("id"), req.get("call"), req.get("method"),
            req.get("args") or [], req.get("kwargs") or {},
        )
        if load_error is not None:
            _channel.send({"id": req_id, "ok": False, "result": None,
                            "error": f"plugin failed to load: {load_error}"})
            continue
        try:
            if call == "register":
                # register() may run more than once per worker lifetime
                # (every enable() on a still-alive worker re-runs it) —
                # clear prior state first so the returned list always
                # reflects exactly this call's registrations, not an
                # accumulation across every register() this worker has
                # ever served.
                _registered.clear()
                _registrations.clear()
                instance.register(ctx)
                result = list(_registrations)
            elif call == "lifecycle":
                result = await _call_lifecycle(instance, ctx, method, args, kwargs)
            elif call == "invoke":
                result = await _call_invoke(method, args, kwargs)
            else:
                raise ValueError(f"unknown call kind {call!r}")
            _channel.send({"id": req_id, "ok": True, "result": result, "error": None})
        except Exception as exc:  # noqa: BLE001 — must report, never crash the loop
            _channel.send({"id": req_id, "ok": False, "result": None, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    asyncio.run(main())
