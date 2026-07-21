/**
 * OrganizationsPage — create, list, and switch between organizations.
 * Data: GET/POST /api/orgs, GET /api/orgs/{id}/activity
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/toast";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";
import { GoldButton, GlassCard } from "../../shared/ui/gold";
import { EmptyState } from "../../shared/ui/EmptyState";

interface ActivityEntry {
  action: string; resource: string | null; resource_id: string | null;
  actor_id: string | null; created_at: string;
}

const KIND_META: Record<string, { icon: string; label: string }> = {
  personal:     { icon: "👤", label: "Personal" },
  organization: { icon: "🏢", label: "Organization" },
  enterprise:   { icon: "🏛️", label: "Enterprise" },
};

export function OrganizationsPage() {
  const toast = useToast();
  const { orgs, currentOrgId, setCurrentOrgId, refreshOrgs, createOrg, loading } = useOrg();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState(false);

  const loadActivity = useCallback(async (orgId: string) => {
    setActivityLoading(true);
    setActivityError(false);
    try {
      const r = await apiFetch(`/api/orgs/${orgId}/activity?limit=20`);
      if (!r.ok) { setActivity([]); setActivityError(true); return; }
      const d = await parseJSON<{ activity: ActivityEntry[] }>(r, "/api/orgs/{id}/activity");
      setActivity(d.activity);
    } catch { setActivity([]); setActivityError(true); }
    finally { setActivityLoading(false); }
  }, []);

  // Clear the feed when no org is selected — render-time adjustment.
  const [prevOrgId, setPrevOrgId] = useState(currentOrgId);
  if (prevOrgId !== currentOrgId) { setPrevOrgId(currentOrgId); if (!currentOrgId) setActivity([]); }

  useEffect(() => {
    if (currentOrgId) void Promise.resolve().then(() => loadActivity(currentOrgId));
  }, [currentOrgId, loadActivity]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      await createOrg(newName.trim());
      toast(`Organization "${newName.trim()}" created`, "ok");
      setNewName(""); setCreating(false);
    } catch (e) {
      toast(`Failed to create organization: ${(e as Error).message}`, "err");
    } finally { setSaving(false); }
  };

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Organizations</span>
        <GoldButton onClick={() => setCreating(c => !c)}>+ New Organization</GoldButton>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {creating && (
          <GlassCard lift={false} style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 12 }}>
              New Organization
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                value={newName} onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void handleCreate()}
                placeholder="Organization name" className="g-input" style={{ flex: 1 }} autoFocus
              />
              <GoldButton onClick={() => void handleCreate()} disabled={saving || !newName.trim()}>
                {saving ? "Creating…" : "Create"}
              </GoldButton>
              <GoldButton variant="ghost" onClick={() => { setCreating(false); setNewName(""); }}>Cancel</GoldButton>
            </div>
          </GlassCard>
        )}

        {loading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[1, 2].map(i => <div key={i} className="skeleton" style={{ height: 72, borderRadius: 12 }} />)}
          </div>
        ) : orgs.length === 0 ? (
          <EmptyState
            icon={<span style={{ fontSize: 40 }}>🏢</span>}
            title="No organizations yet"
            description="Create one to invite teammates and manage billing."
            action={<GoldButton onClick={() => setCreating(true)}>+ New Organization</GoldButton>}
          />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))", gap: 12, marginBottom: 24 }}>
            {orgs.map(org => {
              const meta = KIND_META[org.kind] ?? KIND_META.organization;
              const active = org.id === currentOrgId;
              return (
                <GlassCard
                  key={org.id}
                  style={{
                    padding: "16px 18px",
                    border: active ? "1px solid var(--accent)" : undefined,
                    background: active ? "var(--accent-dim)" : undefined,
                  }}
                >
                  <div
                    role="button" tabIndex={0}
                    onClick={() => setCurrentOrgId(org.id)}
                    onKeyDown={e => e.key === "Enter" && setCurrentOrgId(org.id)}
                    style={{ display: "flex", gap: 12, alignItems: "center", cursor: "pointer" }}
                  >
                    <div style={{ fontSize: 24 }}>{meta.icon}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {org.name}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
                        {meta.label} · {org.plan} plan{org.my_role ? ` · ${org.my_role}` : ""}
                      </div>
                    </div>
                    {active && (
                      <span style={{ fontSize: 10, fontWeight: 700, color: "var(--accent-2)", background: "var(--accent-dim)", padding: "2px 8px", borderRadius: 99 }}>
                        ACTIVE
                      </span>
                    )}
                  </div>
                </GlassCard>
              );
            })}
          </div>
        )}

        {currentOrgId && (
          <GlassCard lift={false}>
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12,
              fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px",
            }}>
              <span>Recent Activity</span>
              <GoldButton variant="ghost" onClick={() => void refreshOrgs()} style={{ padding: "4px 10px", fontSize: 11 }}>↻</GoldButton>
            </div>
            {activityLoading ? (
              <div style={{ color: "var(--t4)", fontSize: 13 }}>Loading…</div>
            ) : activityError ? (
              <EmptyState
                icon={<span style={{ fontSize: 32 }}>⚠️</span>}
                title="Could not load activity"
                description="Something went wrong reaching the server."
                action={<GoldButton variant="ghost" onClick={() => void loadActivity(currentOrgId)}>Retry</GoldButton>}
              />
            ) : activity.length === 0 ? (
              <div style={{ color: "var(--t4)", fontSize: 13 }}>No activity yet.</div>
            ) : activity.map((a, i) => (
              <div key={i} style={{ padding: "10px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none", display: "flex", gap: 10, alignItems: "center" }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>{a.action}</span>
                {a.resource && <span style={{ fontSize: 11, color: "var(--t4)" }}>{a.resource}</span>}
                <span style={{ fontSize: 11, color: "var(--t5)", marginLeft: "auto" }}>
                  {new Date(a.created_at).toLocaleString()}
                </span>
              </div>
            ))}
          </GlassCard>
        )}
      </div>
    </>
  );
}
