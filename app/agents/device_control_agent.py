"""
DeviceControlAgent — AgentOS EvolvableAgent for multi-device control.

This agent is registered in the AgentKernel (via app/agents/loader.py)
and handles user intents like:
  "Set up a multi-device session with my laptop and desktop"
  "Control 3 monitors from one keyboard"
  "List my available devices"
  "Stop the active device control session"

Security guarantees
-------------------
- organization_id comes EXCLUSIVELY from ctx.organization_id (JWT-verified)
  — the LLM output is never trusted for org scoping
- Sessions are created in DRAFT status — the agent cannot start them
- No credentials, tokens, or session secrets are ever shown to the LLM
- The agent sets device-control tool context BEFORE any LLM tool loop,
  so LLM-supplied arguments for those tools are validated against the
  actual org context
- All service calls use the existing DeviceControlService, which enforces
  RBAC, tenancy, and audit logging unchanged
"""
from __future__ import annotations

import logging

from app.agents.base import (
    AgentCapability,
    AgentContext,
    AgentMetadata,
    AgentPermissions,
    AgentResult,
    CapabilityKind,
    EvolvableAgent,
    ValidationResult,
)

log = logging.getLogger(__name__)

# System prompt for the LLM sub-call used to parse user intent
_SYSTEM_PROMPT = """\
You are a multi-device control assistant for the Flow platform.
You help operators set up sessions that allow one keyboard and mouse
to control up to 5 computers simultaneously.

CAPABILITIES:
- List devices registered to this organization (call device_control_list_devices)
- Validate a proposed session configuration (call device_control_validate_session)
- Propose a DRAFT session for human approval (call device_control_propose_session)
- Check session status (call device_control_session_status)
- Stop an active session (call device_control_stop_session)

HARD CONSTRAINTS you must never violate:
1. You cannot start a session — only PROPOSE a draft. A human must approve and
   start it through the Flow UI.
2. Never invent or guess device UUIDs — use only IDs returned by
   device_control_list_devices.
3. Never attempt to access devices from other organizations.
4. Maximum 5 devices per session (primary + up to 4 secondaries).
5. Never ask for or display device credentials, enrollment tokens, or session
   auth tokens.
6. Never attempt to issue keyboard or mouse events directly.

APPROVAL MESSAGE: Always include a clear message in your response that the session
requires human approval before it becomes active.
"""


class DeviceControlAgent(EvolvableAgent):
    """
    Multi-device control orchestrator for AgentOS.

    Registered as "device_control" in the kernel — matches intents like
    "multi-device", "control devices", "KVM", "share mouse", "device session".
    """

    @property
    def name(self) -> str:
        return "device_control"

    @property
    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            name="device_control",
            version="1.0.0",
            description=(
                "Set up and manage multi-device control sessions — "
                "one keyboard/mouse controlling up to 5 computers."
            ),
            group="platform",
            tags=["device", "multi-monitor", "kvm", "input", "control"],
        )

    @property
    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                kind=CapabilityKind.READ,
                description="List and inspect registered devices in the organization",
            ),
            AgentCapability(
                kind=CapabilityKind.WRITE,
                description="Create draft control sessions (requires human approval to start)",
            ),
            AgentCapability(
                kind=CapabilityKind.LLM,
                description="LLM used to parse device selection intent from natural language",
            ),
        ]

    @property
    def permissions(self) -> AgentPermissions:
        return AgentPermissions(
            can_read_filesystem=False,
            can_write_filesystem=False,
            can_execute_subprocess=False,
            can_call_llm=True,
            can_access_network=True,    # needs DB access via service layer
            can_access_memory=True,
            max_execution_seconds=30.0,
        )

    def validate(self, ctx: AgentContext):
        if not ctx.organization_id:
            return ValidationResult.fail(
                "Device control requires an authenticated organization context."
            )
        return ValidationResult.ok()

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """
        Main execution path.

        1. Bind org context so device-control tools cannot be called with
           a different org_id, regardless of LLM output.
        2. Run an AgentRuntime tool loop using the device-control tool set.
        3. Return the agent's response, which may include a draft session
           ID and instructions for the operator to approve it.
        """
        org_id = ctx.organization_id
        if not org_id:
            return AgentResult(
                agent=self.name,
                success=False,
                output="Organization context is required for device control.",
            )

        await ctx.step("Binding device-control context to organization", "info")

        # ── Bind org/user context for tool calls ──────────────────────────────
        from app.ai.tools_device_control import (
            set_device_control_context,
            DEVICE_CONTROL_TOOL_NAMES,
        )
        set_device_control_context(
            org_id=org_id,
            user_id=ctx.user_id or "",
            user_email=_resolve_user_email(ctx),
        )

        await ctx.step("Running device-control tool loop", "info")

        # ── Run AgentRuntime tool loop ────────────────────────────────────────
        try:
            from app.core.ai.agents.runtime import AgentRuntime, AgentConfig
            config = AgentConfig(
                name="device_control_coordinator",
                system_prompt=_SYSTEM_PROMPT,
                provider_id="anthropic",
                model="claude-haiku-4-5-20251001",  # fast, lightweight for tool routing
                max_tokens=2048,
                temperature=0.1,
                max_rounds=6,
                timeout_s=25.0,
                tools=list(DEVICE_CONTROL_TOOL_NAMES),
            )
            runtime = AgentRuntime(config=config)
            result = await runtime.run(ctx.input, user_id=ctx.user_id)

            if result.success:
                await ctx.step("Device-control response ready", "success")
                return AgentResult(
                    agent=self.name,
                    success=True,
                    output=result.content,
                    data={
                        "tool_calls": result.tool_calls,
                        "rounds":     result.rounds,
                    },
                )
            else:
                return AgentResult(
                    agent=self.name,
                    success=False,
                    output=result.content or result.error or "Agent run failed.",
                )

        except Exception as exc:
            log.error("DeviceControlAgent.execute failed: %s", exc, exc_info=True)
            return AgentResult(
                agent=self.name,
                success=False,
                output=f"Device control agent encountered an error: {exc}",
            )


def _resolve_user_email(ctx: AgentContext) -> str:
    """Try to find the user's email from context extras or return a safe default."""
    if ctx.extra:
        email = ctx.extra.get("user_email") or ctx.extra.get("email")
        if email and isinstance(email, str):
            return email
    # Fall back to a safe, auditable placeholder — never expose user_id as email
    return f"agent_run:{ctx.run_id}"
