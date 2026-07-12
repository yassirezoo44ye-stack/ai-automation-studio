"""
Sandbox workspace — reuses app.execution.platform.sandbox.ExecutionSandbox
for isolated temp-directory creation/cleanup rather than reimplementing
copy-on-create / isolated-cache-and-tmp workspace logic that already
exists and is already used in production by the Build feature.

A plugin worker doesn't have a "real project workspace" to copy the way a
Build execution does (there's no user project directory involved), so
this wrapper skips ExecutionSandbox's workspace-copy step and only uses
it for what a worker actually needs: an isolated root/tmp/cache/logs
directory tree that's guaranteed cleaned up.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from app.execution.platform.sandbox import ExecutionSandbox, SandboxPaths

# ExecutionSandbox copies a real_workspace into paths.workspace if one
# exists; a path guaranteed not to exist makes create() skip the copy and
# just build the empty directory tree — exactly what a worker needs. Uses
# a random suffix under the OS temp dir so it can never collide with a
# real directory regardless of CWD.
_EMPTY_WORKSPACE = Path(tempfile.gettempdir()) / f"__axon_sandbox_no_project_{uuid.uuid4().hex}__"


class WorkerWorkspace:
    """Thin wrapper: one isolated directory tree per sandbox worker."""

    def __init__(self, worker_id: str) -> None:
        self._sandbox = ExecutionSandbox(_EMPTY_WORKSPACE, f"sandbox-worker-{worker_id}")
        self.paths: SandboxPaths | None = None

    def create(self) -> SandboxPaths:
        self.paths = self._sandbox.create()
        return self.paths

    def cleanup(self) -> int:
        return self._sandbox.cleanup()
