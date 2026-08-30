"""Run agent — executes a project using the UnifiedExecutionEngine."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)

# app.execution.platform.events.TypedEvent subclasses whose event_type
# marks a hard failure — see that module's ClassVar[str] event_type on
# each subclass. There is no literal "error" type.
_FAILURE_EVENT_TYPES = frozenset({
    "validation_failed", "install_failed", "build_failed",
    "execution_failed", "unsupported",
})

# Detection criteria that mirror RuntimeRegistry's four built-in adapters.
# Keep these in sync with:
#   app/execution/platform/runtimes/node.py       (priority 10)
#   app/execution/platform/runtimes/python_rt.py  (priority 20)
#   app/execution/platform/runtimes/docker_rt.py  (priority 30)
#   app/execution/platform/runtimes/electron_rt.py (priority 40)
_RUNTIME_INDICATORS: list[tuple[str, list[str]]] = [
    ("Node.js",  ["package.json", "*.js", "*.ts", "*.jsx", "*.tsx"]),
    ("Python",   ["requirements.txt", "pyproject.toml", "*.py"]),
    ("Docker",   ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"]),
]


def _detect_runtime_type(workspace: Path) -> str | None:
    """Return a human-readable runtime label if any indicator is found, else None.

    Only checks the workspace root — matching the four built-in runtimes'
    detect() implementations exactly — so the result is consistent with
    what RuntimeRegistry.select() would decide.
    """
    for label, indicators in _RUNTIME_INDICATORS:
        for pattern in indicators:
            if "*" in pattern:
                if any(True for _ in workspace.glob(pattern)):
                    return label
            elif (workspace / pattern).exists():
                return label
    return None


class RunAgent(EvolvableAgent):
    name        = "run"
    description = "Execute a project (auto-detects Node, Python, Docker)"
    group       = "execution"

    @property
    def permissions(self) -> AgentPermissions:
        # Matches performance_hint()'s own declared timeout_s=300 below —
        # a real project execution via UnifiedExecutionEngine routinely
        # exceeds the generic 30s default.
        return AgentPermissions(can_execute_subprocess=True, max_execution_seconds=300.0)

    async def execute(self, ctx: AgentContext) -> AgentResult:
        # SECURITY FIX: this used to derive the workspace directly from
        # ctx.args/ctx.workspace — a raw string that, via /api/agentos/run
        # etc., traces straight back to a client-supplied request field —
        # and hand it to UnifiedExecutionEngine, which copies it into a
        # sandbox and runs install/build/launch against it: an
        # arbitrary-file-read + arbitrary-code-execution primitive gated
        # by nothing but a valid session. ctx.user_id is trustworthy here
        # because every /api/agentos/* caller resolves it from the
        # verified auth token (see agent_os_api.py's optional_user_id
        # usage), never from the request body — but the workspace itself
        # must still be re-derived from a verified project_id, matching
        # runtime_api.py's POST /api/runtime/execute fix. ctx.workspace/
        # ctx.args are no longer trusted at all.
        if not ctx.user_id:
            return AgentResult.fail(self.name, "Authentication required.")
        if not ctx.project_id:
            return AgentResult.fail(
                self.name,
                "No project specified. Usage: run --project=<id> (or pass project_id).",
            )

        try:
            uid = uuid.UUID(ctx.user_id)
        except ValueError:
            return AgentResult.fail(self.name, "Invalid caller identity.")

        from app.core.db import get_pool
        from app.core.filesystem import workspace as project_workspace
        from app.core.helpers import resolve_project_id
        from fastapi import HTTPException

        async with get_pool().acquire() as conn:
            try:
                pid = await resolve_project_id(conn, ctx.project_id, uid)
            except HTTPException as exc:
                return AgentResult.fail(self.name, str(exc.detail))

        ws = project_workspace(str(pid))
        project_id = str(pid)

        # ── Workspace content validation ──────────────────────────────────────
        # Check BEFORE calling UnifiedExecutionEngine so the user gets a clear,
        # actionable message instead of the generic "Runtime 'unknown' is not
        # supported in this sandbox" that the engine emits when no runtime
        # matches an empty or unrecognised workspace.
        #
        # This mirrors RuntimeRegistry.select()'s detection logic — if we
        # can't find an indicator here, the engine will also find nothing.
        detected_runtime = _detect_runtime_type(ws)
        if detected_runtime is None:
            return AgentResult.fail(
                self.name,
                (
                    f"Project '{ws.name}' has no recognisable source files.\n\n"
                    "To run a project, the workspace must contain at least one of:\n"
                    "  • package.json or *.js / *.ts files  → Node.js runtime\n"
                    "  • requirements.txt, pyproject.toml, or *.py files  → Python runtime\n"
                    "  • Dockerfile or docker-compose.yml  → Docker runtime\n\n"
                    "Steps to fix:\n"
                    "  1. Open the App Builder and generate or upload project files.\n"
                    "  2. Or build the project first from the Dev → Build tab.\n"
                    "  3. Then run this command again."
                ),
                data={
                    "workspace"  : str(ws),
                    "error_code" : "EMPTY_WORKSPACE",
                    "project_id" : project_id,
                },
            )

        await ctx.step(
            f"Detected runtime: {detected_runtime} — starting {ws.name}…",
            "terminal",
            workspace=str(ws),
            runtime=detected_runtime,
        )

        try:
            from app.execution.platform.engine import UnifiedExecutionEngine
            execution_id = str(uuid.uuid4())
            engine = UnifiedExecutionEngine()

            events: list[dict] = []
            async for raw_event in engine.run(ws, project_id, execution_id):
                # engine.run() yields TypedEvent dataclass instances, not
                # dicts — to_sse_dict() is the documented way to get a plain
                # dict view (see app/execution/platform/events.py).
                event = raw_event.to_sse_dict()
                events.append(event)
                # Forward the engine's own progress narration live — this is
                # the same event stream DevWorkspace's RunTab already renders
                # after the fact; ctx.step() is what makes it live instead.
                narration = event.get("message") or event.get("line") or event.get("type")
                if narration:
                    await ctx.step(str(narration), "terminal")
                if event.get("type") in _FAILURE_EVENT_TYPES:
                    return AgentResult.fail(
                        self.name,
                        event.get("message", f"execution failed: {event.get('type')}"),
                        data={
                            "events"    : events[-10:],
                            "workspace" : str(ws),
                            "error_code": event.get("error_code", "EXECUTION_FAILED"),
                        },
                    )

            return AgentResult.ok(
                self.name,
                f"Project executed successfully: {ws.name}",
                data={
                    "workspace"   : str(ws),
                    "execution_id": execution_id,
                    "event_count" : len(events),
                    "runtime"     : detected_runtime,
                },
            )
        except Exception as exc:
            log.error("run agent error: %s", exc)
            return AgentResult.fail(self.name, str(exc),
                                    data={"workspace": str(ws)})

    def performance_hint(self) -> dict:
        return {"complexity": "high", "io_bound": True, "timeout_s": 300}


agent = RunAgent()
