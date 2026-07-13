"""
Observability context — org_id/user_id/workflow_id/agent_id carried via
ContextVars, mirroring app.core.logging's existing _request_id_var pattern
exactly. Both the OTel span processor (otel.py) and the JSON log formatter
(app/core/logging.py) read from this same context, so every span and every
log line gets the same tags without each call site threading them through
by hand.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_org_id_var     : ContextVar[str] = ContextVar("obs_org_id", default="")
_user_id_var    : ContextVar[str] = ContextVar("obs_user_id", default="")
_workflow_id_var: ContextVar[str] = ContextVar("obs_workflow_id", default="")
_agent_id_var   : ContextVar[str] = ContextVar("obs_agent_id", default="")


def get_org_id() -> str:
    return _org_id_var.get()


def set_org_id(v: Optional[str]) -> None:
    _org_id_var.set(v or "")


def get_user_id() -> str:
    return _user_id_var.get()


def set_user_id(v: Optional[str]) -> None:
    _user_id_var.set(v or "")


def get_workflow_id() -> str:
    return _workflow_id_var.get()


def set_workflow_id(v: Optional[str]) -> None:
    _workflow_id_var.set(v or "")


def get_agent_id() -> str:
    return _agent_id_var.get()


def set_agent_id(v: Optional[str]) -> None:
    _agent_id_var.set(v or "")


def current_tags() -> dict[str, str]:
    """All non-empty observability tags currently in context — the set of
    attributes every span and every log line should carry, per the
    directive's requirement (org_id/user_id/workflow_id/agent_id;
    request_id/correlation_id come from app.core.logging's own ContextVar
    and are added separately since that module already owns them)."""
    tags: dict[str, str] = {}
    if org := get_org_id():          tags["organization_id"] = org
    if usr := get_user_id():         tags["user_id"] = usr
    if wf  := get_workflow_id():     tags["workflow_id"] = wf
    if ag  := get_agent_id():        tags["agent_id"] = ag
    return tags
