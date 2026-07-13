/**
 * SecurityAuditTab — two separate, intentionally NOT-merged audit trails
 * (see app/routers/auth_users.py's get_my_audit_log and
 * app/routers/organizations.py's activity for why they're distinct):
 *   - the caller's own security events (register/login/MFA/account changes)
 *   - the current organization's activity log (settings/members/billing/
 *     marketplace changes)
 * Data: GET /api/auth/me/audit-log, GET /api/orgs/{org_id}/activity.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useOrg } from "../../../contexts/OrgContext";
import { S } from "../../../styles/theme";
import { EmptyNote, ErrorNote, Skeletons } from "../components";
import type { ActivityLogEntry, AuditLogEntry } from "../types";

function Row({ action, sub, ts }: { action: string; sub?: string | null; ts: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 16px",
    }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{action}</span>
      {sub && <span style={{ fontSize: 11, color: "var(--t4)" }}>{sub}</span>}
      <span style={{ fontSize: 11, color: "var(--t4)", marginLeft: "auto" }}>{new Date(ts).toLocaleString()}</span>
    </div>
  );
}

export function SecurityAuditTab() {
  const { currentOrgId } = useOrg();
  const [audit, setAudit] = useState<AuditLogEntry[] | null>(null);
  const [activity, setActivity] = useState<ActivityLogEntry[] | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const auditRes = await apiFetch("/api/auth/me/audit-log?limit=50");
      if (!auditRes.ok) throw new Error();
      const auditData = await parseJSON<{ entries: AuditLogEntry[] }>(auditRes, "/api/auth/me/audit-log");
      setAudit(auditData.entries);

      if (currentOrgId) {
        const actRes = await apiFetch(`/api/orgs/${currentOrgId}/activity?limit=50`);
        if (!actRes.ok) throw new Error();
        const actData = await parseJSON<{ activity: ActivityLogEntry[] }>(actRes, "/api/orgs/{org_id}/activity");
        setActivity(actData.activity);
      } else {
        setActivity([]);
      }
      setError(false);
    } catch {
      setError(true);
    }
  }, [currentOrgId]);

  useEffect(() => { void load(); }, [load]);

  if (error && !audit) return <ErrorNote>Could not load audit/activity logs.</ErrorNote>;
  if (!audit || !activity) return <Skeletons n={3} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div>
        <div style={{ ...S.cardTitle, marginBottom: 12 }}>Your security events</div>
        {audit.length === 0 ? (
          <EmptyNote>No security events recorded yet.</EmptyNote>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {audit.map(a => <Row key={a.id} action={a.action} sub={a.ip_address} ts={a.created_at} />)}
          </div>
        )}
      </div>

      <div>
        <div style={{ ...S.cardTitle, marginBottom: 12 }}>Organization activity</div>
        {!currentOrgId ? (
          <EmptyNote>Select an organization to see its activity log.</EmptyNote>
        ) : activity.length === 0 ? (
          <EmptyNote>No activity recorded yet.</EmptyNote>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {activity.map((a, i) => <Row key={i} action={a.action} sub={a.resource ?? undefined} ts={a.created_at} />)}
          </div>
        )}
      </div>
    </div>
  );
}
