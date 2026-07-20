"""
Maps existing EventBus event types (app/core/events/bus.py's EVENT_TYPES)
to notification content. New event types only need an entry here — no
change to the dispatcher itself (Step "extensibility" from the spec).
"""
from __future__ import annotations

from typing import Any, Callable, NamedTuple, Optional, Union

SeverityFn = Union[str, Callable[[dict[str, Any]], str]]


class NotificationTemplate(NamedTuple):
    category: str
    severity: SeverityFn
    title: Callable[[dict[str, Any]], str]
    message: Callable[[dict[str, Any]], str]
    action: Optional[Callable[[dict[str, Any]], dict[str, str]]] = None

    def resolve_severity(self, data: dict[str, Any]) -> str:
        return self.severity(data) if callable(self.severity) else self.severity


def _wf_action(d: dict[str, Any]) -> dict[str, str]:
    return {"label": "View run", "href": f"/automation?run={d.get('run_id', '')}"}


TEMPLATES: dict[str, NotificationTemplate] = {
    "workflow.completed": NotificationTemplate(
        "workflow", "success",
        lambda d: f"Workflow “{d.get('name', 'run')}” completed",
        lambda d: f"Run {d.get('run_id', '')[:8]} finished successfully.",
        _wf_action,
    ),
    "workflow.failed": NotificationTemplate(
        "workflow", "error",
        lambda d: f"Workflow “{d.get('name', 'run')}” failed",
        lambda d: d.get("error") or "The run failed — check the run log for details.",
        _wf_action,
    ),
    "agent.finished": NotificationTemplate(
        "agent",
        lambda d: "success" if d.get("success") else "error",
        lambda d: f"Agent “{d.get('agent', 'agent')}” finished",
        lambda d: "The agent run completed successfully." if d.get("success")
                  else "The agent run did not complete successfully.",
        None,
    ),
    "billing.updated": NotificationTemplate(
        "billing", "info",
        lambda d: "Billing updated",
        lambda d: f"Your plan is now {d.get('plan', 'updated')} ({d.get('status', 'active')}).",
        lambda d: {"label": "View billing", "href": "/billing"},
    ),
    "billing.payment_failed": NotificationTemplate(
        "billing", "error",
        lambda d: "Payment failed",
        lambda d: "A payment on your account failed — update your payment method to avoid service interruption.",
        lambda d: {"label": "View billing", "href": "/billing"},
    ),
    "billing.invoice_paid": NotificationTemplate(
        "billing", "success",
        lambda d: "Invoice paid",
        lambda d: "Your latest invoice was paid successfully.",
        lambda d: {"label": "View billing", "href": "/billing"},
    ),
    "marketplace.installed": NotificationTemplate(
        "marketplace", "success",
        lambda d: f"Installed “{d.get('name', 'listing')}”",
        lambda d: f"Version {d.get('version', '')} was installed successfully.".strip(),
        lambda d: {"label": "View marketplace", "href": "/marketplace"},
    ),
    "marketplace.install_failed": NotificationTemplate(
        "marketplace", "error",
        lambda d: "Marketplace install failed",
        lambda d: d.get("reason") or "The marketplace install failed.",
        lambda d: {"label": "View marketplace", "href": "/marketplace"},
    ),
    "marketplace.published": NotificationTemplate(
        "marketplace", "success",
        lambda d: f"Published “{d.get('name', 'listing')}”",
        lambda d: "Your marketplace listing is now live.",
        lambda d: {"label": "View marketplace", "href": "/marketplace"},
    ),
    "deployment.completed": NotificationTemplate(
        "deployment", "success",
        lambda d: "Deployment completed",
        lambda d: d.get("message") or "A deployment finished.",
        None,
    ),
    "organization.member_added": NotificationTemplate(
        "organization", "info",
        lambda d: "New team member",
        lambda d: f"A new member joined your organization as {d.get('role', 'a member')}.",
        lambda d: {"label": "View team", "href": "/teams"},
    ),
    "job.completed": NotificationTemplate(
        "background_job", "success",
        lambda d: "Background job completed",
        lambda d: d.get("message") or "A background job finished successfully.",
        None,
    ),
    "job.failed": NotificationTemplate(
        "background_job", "error",
        lambda d: "Background job failed",
        lambda d: d.get("error") or "A background job failed.",
        None,
    ),
}
