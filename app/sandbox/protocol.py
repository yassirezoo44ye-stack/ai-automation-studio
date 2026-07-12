"""
Sandbox worker IPC protocol — newline-delimited JSON over stdin/stdout,
used both by app.sandbox.backends (the main-process side) and
app.sandbox.runner_entrypoint (the in-worker side). Kept in one shared
module so both sides can never drift on the wire format.

FULL DUPLEX by necessity: PluginContext's Secret/Storage/Event/Metric API
(app/plugins/base.py) needs a live Postgres pool and the real
app.plugins.secrets/storage/app.core.events modules — none of which exist
inside an isolated worker (no DB connection, no app package importable).
So a worker-side PluginContext shim doesn't call those modules directly;
it sends a "context_rpc" request BACK to the main process over the same
stdin/stdout channel and blocks for the response, and the main process
services it with the real modules. Both sides therefore run the same
kind of read/dispatch loop, just with opposite request/response roles for
different "call" kinds:

Request  : {"id": str, "call": "register"|"invoke"|"lifecycle"|"context_rpc", "method": str|None, "args": [...], "kwargs": {...}}
Response : {"id": str, "ok": bool, "result": <json>, "error": str|None}

Main process -> worker:
  "register"  — run once at worker startup. No method/args. Result is a
                list of recorded registrations: [{"type": "tool", "name": ...,
                "schema": {...}}, ...].
  "invoke"    — call a previously-registered handler by name. method =
                the registration's name, kwargs = the call arguments.
  "lifecycle" — call a PluginBase lifecycle hook directly (on_install,
                on_enable, on_disable, on_uninstall, on_config_change,
                health_check). method = the hook name.

Worker -> main process:
  "context_rpc" — method is one of get_secret/set_secret/storage_get/
                  storage_put/storage_delete/emit_event/emit_metric,
                  serviced against the real app.plugins.secrets/storage/
                  app.core.events modules using the installation_id the
                  main process already knows for this worker (never
                  trusted from the worker's own request payload).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

CallKind = Literal["register", "invoke", "lifecycle", "context_rpc"]


@dataclass
class SandboxRequest:
    id: str
    call: CallKind
    method: Optional[str] = None
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "id": self.id, "call": self.call, "method": self.method,
            "args": self.args, "kwargs": self.kwargs,
        })

    @classmethod
    def from_json(cls, raw: str) -> "SandboxRequest":
        data = json.loads(raw)
        return cls(
            id=data["id"], call=data["call"], method=data.get("method"),
            args=data.get("args") or [], kwargs=data.get("kwargs") or {},
        )


@dataclass
class SandboxResponse:
    id: str
    ok: bool
    result: Any = None
    error: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({"id": self.id, "ok": self.ok, "result": self.result, "error": self.error})

    @classmethod
    def from_json(cls, raw: str) -> "SandboxResponse":
        data = json.loads(raw)
        return cls(id=data["id"], ok=data["ok"], result=data.get("result"), error=data.get("error"))
