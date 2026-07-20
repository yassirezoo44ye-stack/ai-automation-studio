/**
 * SecurityAuditTab — two separate, intentionally NOT-merged audit trails
 * (see app/routers/auth_users.py's get_my_audit_log and
 * app/routers/organizations.py's activity for why they're distinct):
 *   - the caller's own security events (register/login/MFA/account changes)
 *   - the current organization's activity log (settings/members/billing/
 *     marketplace changes)
 * Data: GET /api/auth/me/audit-log, GET /api/orgs/{org_id}/activity.
 * Rendered as one merged, day-grouped, filterable timeline via the shared
 * ActivityTimeline component (see shared/ui/notifications).
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useOrg } from "../../../contexts/OrgContext";
import { S } from "../../../styles/theme";
import { ActivityTimeline, type TimelineEntry } from "../../../shared/ui/notifications";
import type { ActivityLogEntry, AuditLogEntry } from "../types";

export function SecurityAuditTab() {
  const { currentOrgId } = useOrg();
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");

  const load = useCallback(async () => {
    setStatus(prev => prev === "success" ? "success" : "loading");
    try {
      const auditRes = await apiFetch("/api/auth/me/audit-log?limit=50");
      if (!auditRes.ok) throw new Error();
      const auditData = await parseJSON<{ entries: AuditLogEntry[] }>(auditRes, "/api/auth/me/audit-log");

      let activity: ActivityLogEntry[] = [];
      if (currentOrgId) {
        const actRes = await apiFetch(`/api/orgs/${currentOrgId}/activity?limit=50`);
        if (!actRes.ok) throw new Error();
        const actData = await parseJSON<{ activity: ActivityLogEntry[] }>(actRes, "/api/orgs/{org_id}/activity");
        activity = actData.activity;
      }

      const merged: TimelineEntry[] = [
        ...auditData.entries.map(a => ({
          id: a.id, action: a.action, sub: a.ip_address, created_at: a.created_at, group: "security",
        })),
        ...activity.map((a, i) => ({
          id: `org-${i}-${a.created_at}`, action: a.action, sub: a.resource, created_at: a.created_at, group: "organization",
        })),
      ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

      setEntries(merged);
      setStatus("success");
    } catch {
      setStatus("error");
    }
  }, [currentOrgId]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  return (
    <div>
      <div style={{ ...S.cardTitle, marginBottom: 12 }}>Activity</div>
      <ActivityTimeline
        entries={entries}
        groups={[
          { id: "security", label: "Security" },
          { id: "organization", label: currentOrgId ? "Organization" : "Organization (select an org)" },
        ]}
        status={status}
        onRetry={() => void load()}
        emptyMessage="No security or organization activity recorded yet."
      />
    </div>
  );
}
