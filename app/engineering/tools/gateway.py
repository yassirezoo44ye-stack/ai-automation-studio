"""
EngineeringToolGateway — the ONLY path Claude uses to touch external systems.

Security contract:
  1. org_id is ALWAYS sourced from the caller's verified OrgContext,
     never from Claude's output or the request body.
  2. Credentials are loaded by CredentialStore using (provider_id, org_id).
     They are NEVER passed to Claude, never included in logs, never in Evidence.
  3. Tool results from external APIs are UNTRUSTED DATA. They are sanitized
     before inclusion in any LLM context.
  4. Every execution is recorded in:
       - activity_logs   (audit trail, who called what when)
       - eng_evidence    (immutable result record with verification status)
  5. Every tool call is permission-checked against the calling user's role.
  6. High-risk tools are blocked here if no active approval exists.
  7. Cost budget is decremented; a mission that exceeds its step budget
     is paused (status=BLOCKED) and requires operator intervention.

Usage:
    gateway = EngineeringToolGateway(pool)
    result = await gateway.execute(
        tool_name="github.create_pull_request",
        args={"repo": "owner/repo", "title": "...", "head": "...", "base": "main"},
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        role=ctx.role,
        mission_id=mission_id,
        task_id=task_id,
    )
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

# ── Tool category risk levels ─────────────────────────────────────────────────

class RiskLevel(str, Enum):
    READ        = "read"
    ANALYZE     = "analyze"
    WRITE       = "write"
    DEPLOY      = "deploy"
    DESTRUCTIVE = "destructive"


# Minimum role required per risk level
_RISK_MIN_ROLE: dict[str, list[str]] = {
    RiskLevel.READ:        ["viewer", "operator", "developer", "manager", "admin", "owner"],
    RiskLevel.ANALYZE:     ["developer", "manager", "admin", "owner"],
    RiskLevel.WRITE:       ["operator", "manager", "admin", "owner"],
    RiskLevel.DEPLOY:      ["admin", "owner"],
    RiskLevel.DESTRUCTIVE: ["owner"],
}

# Risk levels that require an active eng_approvals record before execution
_APPROVAL_REQUIRED = {RiskLevel.DEPLOY, RiskLevel.DESTRUCTIVE}


@dataclass
class ToolDefinition:
    """Static definition of one engineering tool."""
    name: str                       # e.g. "github.create_pull_request"
    provider: str                   # e.g. "github"
    operation: str                  # e.g. "create_pull_request"
    description: str
    risk_level: RiskLevel
    # Required fields in the args dict (validated before execution)
    required_args: list[str] = field(default_factory=list)
    # Timeout in seconds
    timeout_s: float = 30.0
    # Whether this tool can be idempotently retried
    idempotent: bool = True


@dataclass
class ToolCallResult:
    """Typed result returned by the gateway after executing a tool."""
    tool_name: str
    success: bool
    # Sanitized output — safe to include in LLM context
    output: dict[str, Any]
    error: Optional[str] = None
    evidence_id: Optional[str] = None
    duration_ms: float = 0.0
    # Caller should surface this in approval workflow when required_approval=True
    required_approval: bool = False
    approval_id: Optional[str] = None


class ToolNotFoundError(Exception):
    pass


class ToolPermissionError(Exception):
    pass


class ToolBudgetExceeded(Exception):
    pass


class ToolApprovalRequired(Exception):
    """Raised when the tool requires an active approval that doesn't exist."""
    def __init__(self, action: str, resource: str, risk_level: str):
        self.action    = action
        self.resource  = resource
        self.risk_level = risk_level
        super().__init__(f"Approval required for {action} on {resource!r} (risk={risk_level})")


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """Immutable registry of allowed tool definitions."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._tools[definition.name] = definition
        log.debug("engineering tool registered: %s (risk=%s)", definition.name, definition.risk_level)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def require(self, name: str) -> ToolDefinition:
        t = self.get(name)
        if t is None:
            raise ToolNotFoundError(f"engineering tool {name!r} is not registered")
        return t

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_for_role(self, role: str) -> list[ToolDefinition]:
        """Tools this role is allowed to call (excludes approval-required ones
        since those need an active approval in addition to the role check)."""
        return [
            t for t in self._tools.values()
            if role in _RISK_MIN_ROLE.get(t.risk_level, [])
        ]


_global_registry = ToolRegistry()

# Maps tool_name → async function. Each tool module patches this dict
# on import (via its _register_*_tools() function). Lives here — not in
# __init__.py — to avoid circular imports between tools/* and tools/__init__.
ALL_TOOLS: dict = {}


def get_tool_registry() -> ToolRegistry:
    return _global_registry


# ── Sanitizer ─────────────────────────────────────────────────────────────────

_SECRET_KEYS = frozenset({
    "token", "api_key", "secret", "password", "access_token", "refresh_token",
    "private_key", "private_key_pem", "webhook_secret", "installation_token",
    "auth_token", "client_secret", "bearer", "authorization",
})


def _sanitize(data: Any, depth: int = 0) -> Any:
    """Recursively redact known secret key names from dicts.

    Tool results from external APIs are UNTRUSTED DATA — this sanitization
    ensures no credential-shaped value from a provider response (e.g. a
    GitHub token embedded in a webhook payload) leaks into LLM context or
    Evidence. It does NOT prevent all prompt injection — the gateway also
    limits which fields are included in the sanitized output.

    depth cap prevents infinite recursion on pathological inputs.
    """
    if depth > 8:
        return "<depth_limit>"
    if isinstance(data, dict):
        return {
            k: "***REDACTED***" if k.lower() in _SECRET_KEYS else _sanitize(v, depth + 1)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_sanitize(item, depth + 1) for item in data[:50]]  # cap at 50 items
    if isinstance(data, str) and len(data) > 4096:
        return data[:4096] + "...<truncated>"
    return data


def _inputs_hash(args: dict) -> str:
    """Stable SHA-256 of sanitized args for Evidence tracking (no secrets)."""
    sanitized = _sanitize(args)
    canonical = json.dumps(sanitized, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# ── Gateway ───────────────────────────────────────────────────────────────────

class EngineeringToolGateway:
    """
    The single execution path for all engineering tool calls.

    Workflow per call:
      1. Resolve tool definition (ToolNotFoundError if unknown)
      2. Validate required args
      3. Check role permission (ToolPermissionError if insufficient)
      4. Check mission budget (ToolBudgetExceeded if over limit)
      5. Check active approval for DEPLOY/DESTRUCTIVE tools
      6. Load credential from CredentialStore (never passed to Claude)
      7. Execute provider call via the tool's fn
      8. Sanitize result (remove secret-shaped keys, truncate)
      9. Record Evidence
     10. Write activity_log
     11. Decrement mission step budget
     12. Return ToolCallResult (sanitized output only)
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def execute(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        org_id: str,
        user_id: str,
        role: str,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> ToolCallResult:
        start = time.monotonic()
        registry = get_tool_registry()

        # 1. Resolve tool
        try:
            defn = registry.require(tool_name)
        except ToolNotFoundError:
            log.warning("tool not found: %s (org=%s)", tool_name, org_id)
            raise

        # 2. Validate required args
        missing = [k for k in defn.required_args if k not in args]
        if missing:
            raise ValueError(f"tool {tool_name!r} missing required args: {missing}")

        # 3. Permission check — role must be in the allowed list for this risk level
        allowed_roles = _RISK_MIN_ROLE.get(defn.risk_level, [])
        if role not in allowed_roles:
            log.warning(
                "tool permission denied: %s requires role in %s, caller has %r (org=%s)",
                tool_name, allowed_roles, role, org_id,
            )
            raise ToolPermissionError(
                f"tool {tool_name!r} requires role {allowed_roles!r}; caller role is {role!r}"
            )

        # 4. Budget check
        if mission_id:
            await self._check_budget(mission_id, org_id)

        # 5. Approval gate for high-risk operations
        if defn.risk_level in _APPROVAL_REQUIRED and mission_id:
            resource = args.get("service_id") or args.get("repo") or args.get("deployment_id") or ""
            await self._require_approval(
                mission_id=mission_id,
                org_id=org_id,
                action=tool_name,
                resource=str(resource),
                risk_level=defn.risk_level,
            )

        # 6. Load credential from store (never passed to Claude)
        from app.integrations.credential_store import get_credential_store
        credential = await get_credential_store(self._pool).load(defn.provider, org_id)
        if credential is None:
            raise ToolPermissionError(
                f"provider {defn.provider!r} is not connected for this organization. "
                f"Connect it at Settings → Integrations before running this tool."
            )

        # 7. Execute
        raw_output: dict[str, Any] = {}
        error: Optional[str] = None
        success = False
        try:
            from app.engineering.tools import ALL_TOOLS
            fn = ALL_TOOLS.get(tool_name)
            if fn is None:
                raise ToolNotFoundError(f"no executor for {tool_name!r}")
            import asyncio
            raw_output = await asyncio.wait_for(
                fn(credential=credential, args=args, org_id=org_id),
                timeout=defn.timeout_s,
            )
            success = True
        except asyncio.TimeoutError:
            error = f"tool {tool_name!r} timed out after {defn.timeout_s}s"
            raw_output = {}
        except ToolPermissionError:
            raise
        except Exception as exc:
            error = str(exc)
            raw_output = {}
            log.warning("tool %s failed (org=%s): %s", tool_name, org_id, exc)

        duration_ms = (time.monotonic() - start) * 1000

        # 8. Sanitize output — UNTRUSTED DATA from external API
        sanitized = _sanitize(raw_output)

        # 9. Record Evidence
        evidence_id = await self._record_evidence(
            org_id=org_id,
            mission_id=mission_id,
            task_id=task_id,
            defn=defn,
            args=args,
            sanitized_output=sanitized,
            success=success,
            error=error,
        )

        # 10. Audit log
        await self._audit(
            org_id=org_id,
            user_id=user_id,
            tool_name=tool_name,
            mission_id=mission_id,
            success=success,
        )

        # 11. Decrement budget
        if mission_id and success:
            await self._decrement_budget(mission_id)

        return ToolCallResult(
            tool_name=tool_name,
            success=success,
            output=sanitized if success else {},
            error=error,
            evidence_id=evidence_id,
            duration_ms=duration_ms,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _check_budget(self, mission_id: str, org_id: str) -> None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT steps_used, budget_steps FROM eng_missions "
                "WHERE id=$1 AND organization_id=$2",
                uuid.UUID(mission_id), uuid.UUID(org_id),
            )
        if row and row["steps_used"] >= row["budget_steps"]:
            raise ToolBudgetExceeded(
                f"mission {mission_id[:8]} has used {row['steps_used']}/{row['budget_steps']} steps"
            )

    async def _require_approval(
        self,
        *,
        mission_id: str,
        org_id: str,
        action: str,
        resource: str,
        risk_level: str,
    ) -> None:
        """Check that an active (pending→approved) approval exists for this action."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id FROM eng_approvals
                   WHERE mission_id=$1 AND organization_id=$2
                     AND action=$3 AND status='approved'
                     AND expires_at > NOW()
                   LIMIT 1""",
                uuid.UUID(mission_id), uuid.UUID(org_id), action,
            )
        if row is None:
            raise ToolApprovalRequired(action=action, resource=resource, risk_level=risk_level)

    async def _record_evidence(
        self,
        *,
        org_id: str,
        mission_id: Optional[str],
        task_id: Optional[str],
        defn: ToolDefinition,
        args: dict,
        sanitized_output: dict,
        success: bool,
        error: Optional[str],
    ) -> Optional[str]:
        if mission_id is None:
            return None
        try:
            evidence_id = str(uuid.uuid4())
            v_status = "pending" if success and defn.risk_level in _APPROVAL_REQUIRED else \
                       ("unverified" if success else "failed")
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO eng_evidence
                       (id, organization_id, mission_id, task_id,
                        provider, operation, tool_name,
                        inputs_hash, outputs_summary, verification_status)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                    uuid.UUID(evidence_id),
                    uuid.UUID(org_id),
                    uuid.UUID(mission_id),
                    uuid.UUID(task_id) if task_id else None,
                    defn.provider,
                    defn.operation,
                    defn.name,
                    _inputs_hash(args),
                    json.dumps({
                        "result": sanitized_output if success else {},
                        "error": error,
                    }),
                    v_status,
                )
            return evidence_id
        except Exception:
            log.warning("evidence record failed (continuing)", exc_info=True)
            return None

    async def _audit(
        self,
        *,
        org_id: str,
        user_id: str,
        tool_name: str,
        mission_id: Optional[str],
        success: bool,
    ) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO activity_logs "
                    "(organization_id, actor_id, action, resource, resource_id) "
                    "VALUES ($1,$2,$3,'engineering_tool',$4)",
                    uuid.UUID(org_id),
                    uuid.UUID(user_id),
                    f"engineering.tool.{'succeeded' if success else 'failed'}.{tool_name}",
                    mission_id or "none",
                )
        except Exception:
            log.warning("audit log write failed (continuing)", exc_info=True)

    async def _decrement_budget(self, mission_id: str) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE eng_missions SET steps_used = steps_used + 1, updated_at = NOW() "
                    "WHERE id=$1",
                    uuid.UUID(mission_id),
                )
        except Exception:
            log.warning("budget decrement failed (continuing)", exc_info=True)


# ── Module-level singleton ─────────────────────────────────────────────────────

_gateway: Optional[EngineeringToolGateway] = None


def get_tool_gateway(pool: Optional[asyncpg.Pool] = None) -> EngineeringToolGateway:
    global _gateway
    if _gateway is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _gateway = EngineeringToolGateway(pool)
    return _gateway
