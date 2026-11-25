"""
Modify agent — runtime file editing via the SelfModifyingEngine.

Sub-commands:
  patch <file> <find> <replace>  — find-and-replace in a file
  append <file> <content>        — append to end of file
  replace <file> <content>       — overwrite entire file
  create <file> <content>        — create a new file
  rollback <index>               — restore file from backup
  diff <file>                    — show current vs backup
  list                           — list all modifications
"""
from __future__ import annotations

import logging
import shlex

from app.agents.base import AgentContext, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)


class ModifyAgent(EvolvableAgent):
    name        = "modify"
    description = "Runtime file modification with rollback support"
    group       = "system"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        try:
            parts = shlex.split(ctx.args) if ctx.args else []
        except ValueError:
            parts = ctx.args.split() if ctx.args else []

        sub = parts[0].lower() if parts else ""

        # Writes go into the server's own source tree (the policy allows
        # app/), which the agent loader and hot-reload then execute — only a
        # platform administrator may do that. Read-only views stay open.
        if sub in {"patch", "append", "replace", "create", "rollback"} and not await _is_platform_admin(ctx.user_id):
            return AgentResult.fail(self.name, "Platform administrator access required.")

        modifier = ctx.kernel._modifier
        if modifier is None:
            return AgentResult.fail(self.name, "SelfModifyingEngine not initialized")

        try:
            if sub == "patch" and len(parts) >= 4:
                file, find, replace = parts[1], parts[2], parts[3]
                result = modifier.patch(file, find=find, replace=replace)
                return AgentResult.ok(self.name, f"Patched {file}: {result['occurrences']} occurrence(s)",
                                      data=result)

            if sub == "append" and len(parts) >= 3:
                file, content = parts[1], " ".join(parts[2:])
                result = modifier.append(file, content=content)
                return AgentResult.ok(self.name, f"Appended to {file}", data=result)

            if sub == "replace" and len(parts) >= 3:
                file, content = parts[1], " ".join(parts[2:])
                result = modifier.replace(file, content=content)
                return AgentResult.ok(self.name, f"Replaced {file}", data=result)

            if sub == "create" and len(parts) >= 3:
                file, content = parts[1], " ".join(parts[2:])
                result = modifier.create(file, content=content)
                return AgentResult.ok(self.name, f"Created {file}", data=result)

            if sub == "rollback" and len(parts) >= 2:
                index = int(parts[1])
                result = modifier.rollback(index)
                return AgentResult.ok(self.name, f"Rolled back modification {index}", data=result)

            if sub == "diff" and len(parts) >= 2:
                result = modifier.diff(parts[1])
                changed = result.get("changed", False)
                return AgentResult.ok(self.name,
                    f"{parts[1]}: {'CHANGED' if changed else 'no changes from backup'}",
                    data=result)

            if sub == "list":
                state = modifier._state
                mods  = state.modifications
                return AgentResult.ok(
                    self.name, f"{len(mods)} modification(s) recorded",
                    data={"modifications": [m.to_dict() for m in mods]},
                )

        except Exception as exc:
            return AgentResult.fail(self.name, str(exc))

        return AgentResult.fail(
            self.name,
            "Usage: modify patch|append|replace|create|rollback|diff|list ...",
        )

    def performance_hint(self) -> dict:
        return {"complexity": "low", "writes_files": True}


agent = ModifyAgent()


async def _is_platform_admin(user_id: str | None) -> bool:
    """True when the verified caller's account email is in ADMIN_EMAILS."""
    import uuid

    from app.core.config import ADMIN_EMAILS
    if not user_id or not ADMIN_EMAILS:
        return False
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        return False
    from app.core.db import get_pool
    email = await get_pool().fetchval("SELECT email FROM users WHERE id=$1", uid)
    return bool(email) and email.strip().lower() in ADMIN_EMAILS
