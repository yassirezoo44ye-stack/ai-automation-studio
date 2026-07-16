/**
 * OrganizationsPage — create, list, and switch between organizations.
 * Data: GET/POST /api/orgs, GET /api/orgs/{id}/activity
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/ToastContext";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";

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

  const loadActivity = useCallback(async (orgId: string) => {
    setActivityLoading(true);
    try {
      const r = await apiFetch(`/api/orgs/${orgId}/activity?limit=20`);
      if (!r.ok) { setActivity([]); return; }
      const d = await parseJSON<{ activity: ActivityEntry[] }>(r, "/api/orgs/{id}/activity");
      setActivity(d.activity);
    } catch { setActivity([]); }
    finally { setActivityLoading(false); }
  }, []);

  useEffect(() => {
    if (currentOrgId) void loadActivity(currentOrgId);
    else setActivity([]);
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
        <button onClick={() => setCreating(c => !c)} style={S.btnPrimary}>+ New Organization</button>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {creating && (
          <div style={{ ...S.card, marginBottom: 20 }}>
            <div style={{ ...S.cardTitle, marginBottom: 12 }}>New Organization</div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                value={newName} onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void handleCreate()}
                placeholder="Organization name" style={{ ...S.textInput, flex: 1 }} autoFocus
              />
              <button onClick={() => void handleCreate()} disabled={saving || !newName.trim()} style={S.btnPrimary}>
                {saving ? "Creating…" : "Create"}
              </button>
              <button onClick={() => { setCreating(false); setNewName(""); }} style={S.btnSecondary}>Cancel</button>
            </div>
          </div>
        )}

        {loading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[1, 2].map(i => <div key={i} className="skeleton" style={{ height: 72, borderRadius: 12 }} />)}
          </div>
        ) : orgs.length === 0 ? (
          <div className="empty-state">
            <div style={{ fontSize: 40 }}>🏢</div>
            <h3>No organizations yet</h3>
            <p>Create one to invite teammates and manage billing.</p>
            <button onClick={() => setCreating(true)} style={S.btnPrimary}>+ New Organization</button>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))", gap: 12, marginBottom: 24 }}>
            {orgs.map(org => {
              const meta = KIND_META[org.kind] ?? KIND_META.organization;
              const active = org.id === currentOrgId;
              return (
                <div
                  key={org.id}
                  role="button" tabIndex={0}
                  onClick={() => setCurrentOrgId(org.id)}
                  onKeyDown={e => e.key === "Enter" && setCurrentOrgId(org.id)}
                  style={{
                    ...S.card, padding: "16px 18px", cursor: "pointer",
                    border: active ? "1px solid var(--accent)" : S.card.border as string,
                    background: active ? "rgba(232,200,125,.06)" : S.card.background as string,
                  }}
                >
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
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
                      <span style={{ fontSize: 10, fontWeight: 700, color: "var(--accent)", background: "rgba(232,200,125,.15)", padding: "2px 8px", borderRadius: 99 }}>
                        ACTIVE
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {currentOrgId && (
          <div style={S.card}>
            <div style={{ ...S.cardTitle, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Recent Activity</span>
              <button onClick={() => void refreshOrgs()} style={{ ...S.btnSecondary, padding: "4px 10px", fontSize: 11 }}>↻</button>
            </div>
            <div style={{ padding: activityLoading || activity.length === 0 ? "16px 18px" : 0 }}>
              {activityLoading ? (
                <div style={{ color: "var(--t4)", fontSize: 13 }}>Loading…</div>
              ) : activity.length === 0 ? (
                <div style={{ color: "var(--t4)", fontSize: 13 }}>No activity yet.</div>
              ) : activity.map((a, i) => (
                <div key={i} style={{ padding: "10px 18px", borderTop: i > 0 ? "1px solid var(--border)" : "none", display: "flex", gap: 10, alignItems: "center" }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>{a.action}</span>
                  {a.resource && <span style={{ fontSize: 11, color: "var(--t4)" }}>{a.resource}</span>}
                  <span style={{ fontSize: 11, color: "var(--t5)", marginLeft: "auto" }}>
                    {new Date(a.created_at).toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
