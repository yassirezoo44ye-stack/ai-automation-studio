/**
 * TeamsPage — members and invitations for the current organization.
 * Data: GET/PATCH/DELETE /api/orgs/{id}/members*, POST .../invitations
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/ToastContext";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";

type Role = "owner" | "admin" | "manager" | "developer" | "operator" | "viewer";

interface Member {
  user_id: string; email: string; name: string | null; role: Role; joined_at: string;
}

const ROLES: Role[] = ["owner", "admin", "manager", "developer", "operator", "viewer"];
const ROLE_COLOR: Record<Role, string> = {
  owner: "#f59e0b", admin: "#ef4444", manager: "#8b5cf6",
  developer: "#6c8ef7", operator: "#34d399", viewer: "#6b7280",
};

export function TeamsPage() {
  const toast = useToast();
  const { currentOrgId, currentOrg, orgs } = useOrg();
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviting, setInviting] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("viewer");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!currentOrgId) { setMembers([]); setLoading(false); return; }
    setLoading(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/members`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ members: Member[] }>(r, "/api/orgs/{id}/members");
      setMembers(d.members);
    } catch {
      toast("Could not load members", "err");
      setMembers([]);
    } finally { setLoading(false); }
  }, [currentOrgId, toast]);

  useEffect(() => { void load(); }, [load]);

  const invite = async () => {
    if (!currentOrgId || !inviteEmail.trim()) return;
    setSaving(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/invitations`, {
        method: "POST", body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "invite").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || "Failed to send invitation");
      }
      toast(`Invited ${inviteEmail.trim()}`, "ok");
      setInviteEmail(""); setInviting(false);
    } catch (e) {
      toast((e as Error).message || "Failed to send invitation", "err");
    } finally { setSaving(false); }
  };

  const changeRole = async (userId: string, role: Role) => {
    if (!currentOrgId) return;
    setBusy(userId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/members/${userId}`, {
        method: "PATCH", body: JSON.stringify({ role }),
      });
      if (!r.ok) throw new Error();
      setMembers(prev => prev.map(m => m.user_id === userId ? { ...m, role } : m));
      toast("Role updated", "ok");
    } catch { toast("Failed to update role", "err"); }
    finally { setBusy(null); }
  };

  const removeMember = async (userId: string) => {
    if (!currentOrgId) return;
    if (!confirm("Remove this member from the organization?")) return;
    setBusy(userId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/members/${userId}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      setMembers(prev => prev.filter(m => m.user_id !== userId));
      toast("Member removed", "ok");
    } catch { toast("Failed to remove member", "err"); }
    finally { setBusy(null); }
  };

  if (!currentOrgId) {
    return (
      <div className="empty-state" style={{ margin: "auto" }}>
        <div style={{ fontSize: 40 }}>👥</div>
        <h3>No organization selected</h3>
        <p>{orgs.length === 0 ? "Create an organization first." : "Pick one from the Organizations page."}</p>
      </div>
    );
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Teams — {currentOrg?.name ?? "…"}</span>
        <button onClick={() => setInviting(v => !v)} style={S.btnPrimary}>+ Invite Member</button>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {inviting && (
          <div style={{ ...S.card, marginBottom: 20 }}>
            <div style={{ ...S.cardTitle, marginBottom: 12 }}>Invite by Email</div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                value={inviteEmail} onChange={e => setInviteEmail(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void invite()}
                placeholder="teammate@company.com" type="email" style={{ ...S.textInput, flex: 1 }} autoFocus
              />
              <select value={inviteRole} onChange={e => setInviteRole(e.target.value as Role)} style={{ ...S.textInput, width: "auto" }}>
                {ROLES.filter(r => r !== "owner").map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <button onClick={() => void invite()} disabled={saving || !inviteEmail.trim()} style={S.btnPrimary}>
                {saving ? "Sending…" : "Send Invite"}
              </button>
              <button onClick={() => { setInviting(false); setInviteEmail(""); }} style={S.btnSecondary}>Cancel</button>
            </div>
          </div>
        )}

        {loading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 56, borderRadius: 12 }} />)}
          </div>
        ) : members.length === 0 ? (
          <div className="empty-state">
            <div style={{ fontSize: 40 }}>👥</div>
            <h3>No members yet</h3>
          </div>
        ) : (
          <div style={S.card}>
            {members.map((m, i) => (
              <div key={m.user_id} style={{
                padding: "12px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
                display: "flex", alignItems: "center", gap: 12,
              }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                  background: "rgba(139,92,246,.14)", border: "1px solid rgba(139,92,246,.25)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, fontWeight: 700, color: "#c4b5fd",
                }}>
                  {(m.name || m.email)[0]?.toUpperCase()}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{m.name || m.email}</div>
                  <div style={{ fontSize: 11, color: "var(--t4)" }}>{m.email}</div>
                </div>
                <span style={{
                  fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 99,
                  color: ROLE_COLOR[m.role], background: ROLE_COLOR[m.role] + "18",
                  border: `1px solid ${ROLE_COLOR[m.role]}33`,
                }}>
                  {m.role}
                </span>
                {m.role !== "owner" && (
                  <>
                    <select
                      value={m.role} disabled={busy === m.user_id}
                      onChange={e => void changeRole(m.user_id, e.target.value as Role)}
                      style={{ ...S.textInput, width: "auto", fontSize: 11, padding: "5px 10px" }}
                    >
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <button
                      onClick={() => void removeMember(m.user_id)} disabled={busy === m.user_id}
                      style={{ ...S.btnSecondary, padding: "5px 12px", fontSize: 11, color: "#f87171" }}
                    >Remove</button>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
