/**
 * TeamsPage — teams, members, and invitations for the current organization.
 * Data: GET/PATCH/DELETE /api/orgs/{id}/members*, POST .../invitations,
 *       GET/POST/PATCH/DELETE /api/orgs/{id}/teams*
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/toast";
import { useOrg } from "../../contexts/OrgContext";
import { S, C } from "../../styles/theme";

type Role = "owner" | "admin" | "manager" | "developer" | "operator" | "viewer";

interface Member {
  user_id: string; email: string; name: string | null; role: Role; joined_at: string;
}

interface Team {
  id: string; organization_id: string; name: string; description: string | null;
  created_at: string; updated_at: string;
}

interface TeamMember { user_id: string; email: string; name: string | null; joined_at: string }

const ROLES: Role[] = ["owner", "admin", "manager", "developer", "operator", "viewer"];
const ROLE_COLOR: Record<Role, string> = {
  owner: C.amber, admin: C.red, manager: "#D4AF37",
  developer: C.blue, operator: C.green, viewer: C.gray,
};

const sectionLabel: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: "var(--t3)",
  textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8,
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

  const [teams, setTeams] = useState<Team[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(true);
  const [creatingTeam, setCreatingTeam] = useState(false);
  const [newTeamName, setNewTeamName] = useState("");
  const [newTeamDesc, setNewTeamDesc] = useState("");
  const [teamSaving, setTeamSaving] = useState(false);
  const [teamBusy, setTeamBusy] = useState<string | null>(null);
  const [expandedTeam, setExpandedTeam] = useState<string | null>(null);
  const [teamMembers, setTeamMembers] = useState<Record<string, TeamMember[]>>({});
  const [teamMembersLoading, setTeamMembersLoading] = useState<string | null>(null);
  const [addMemberUserId, setAddMemberUserId] = useState("");

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

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const loadTeams = useCallback(async () => {
    if (!currentOrgId) { setTeams([]); setTeamsLoading(false); return; }
    setTeamsLoading(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/teams`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ teams: Team[] }>(r, "/api/orgs/{id}/teams");
      setTeams(d.teams);
    } catch {
      toast("Could not load teams", "err");
      setTeams([]);
    } finally { setTeamsLoading(false); }
  }, [currentOrgId, toast]);

  useEffect(() => { void Promise.resolve().then(loadTeams); }, [loadTeams]);
  // Collapse expanded team state when the org changes — render-time adjustment.
  const [prevTeamsOrg, setPrevTeamsOrg] = useState(currentOrgId);
  if (prevTeamsOrg !== currentOrgId) { setPrevTeamsOrg(currentOrgId); setExpandedTeam(null); setTeamMembers({}); }

  const createTeam = async () => {
    if (!currentOrgId || !newTeamName.trim()) return;
    setTeamSaving(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/teams`, {
        method: "POST",
        body: JSON.stringify({ name: newTeamName.trim(), description: newTeamDesc.trim() || undefined }),
      });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "create team").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || "Failed to create team");
      }
      const team = await parseJSON<Team>(r, "create team");
      setTeams(prev => [...prev, team]);
      toast(`Created team ${team.name}`, "ok");
      setNewTeamName(""); setNewTeamDesc(""); setCreatingTeam(false);
    } catch (e) {
      toast((e as Error).message || "Failed to create team", "err");
    } finally { setTeamSaving(false); }
  };

  const deleteTeam = async (teamId: string) => {
    if (!currentOrgId) return;
    if (!confirm("Delete this team?")) return;
    setTeamBusy(teamId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/teams/${teamId}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      setTeams(prev => prev.filter(t => t.id !== teamId));
      if (expandedTeam === teamId) setExpandedTeam(null);
      toast("Team deleted", "ok");
    } catch { toast("Failed to delete team", "err"); }
    finally { setTeamBusy(null); }
  };

  const toggleTeam = async (teamId: string) => {
    if (expandedTeam === teamId) { setExpandedTeam(null); return; }
    setExpandedTeam(teamId);
    if (teamMembers[teamId] || !currentOrgId) return;
    setTeamMembersLoading(teamId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/teams/${teamId}/members`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ members: TeamMember[] }>(r, "team members");
      setTeamMembers(prev => ({ ...prev, [teamId]: d.members }));
    } catch { toast("Could not load team members", "err"); }
    finally { setTeamMembersLoading(null); }
  };

  const addTeamMember = async (teamId: string) => {
    if (!currentOrgId || !addMemberUserId) return;
    setTeamBusy(teamId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/teams/${teamId}/members`, {
        method: "POST", body: JSON.stringify({ user_id: addMemberUserId }),
      });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "add team member").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || "Failed to add member");
      }
      // Re-fetch from the server rather than synthesizing a row locally —
      // the add endpoint only returns {team_id, user_id}, and the local
      // `members` cache can be stale, which would otherwise show the raw
      // user id in place of a name/email.
      const mr = await apiFetch(`/api/orgs/${currentOrgId}/teams/${teamId}/members`);
      if (mr.ok) {
        const d = await parseJSON<{ members: TeamMember[] }>(mr, "team members");
        setTeamMembers(prev => ({ ...prev, [teamId]: d.members }));
      }
      setAddMemberUserId("");
      toast("Member added to team", "ok");
    } catch (e) {
      toast((e as Error).message || "Failed to add member", "err");
    } finally { setTeamBusy(null); }
  };

  const removeTeamMember = async (teamId: string, userId: string) => {
    if (!currentOrgId) return;
    setTeamBusy(`${teamId}:${userId}`);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/teams/${teamId}/members/${userId}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      setTeamMembers(prev => ({ ...prev, [teamId]: (prev[teamId] || []).filter(m => m.user_id !== userId) }));
      toast("Member removed from team", "ok");
    } catch { toast("Failed to remove team member", "err"); }
    finally { setTeamBusy(null); }
  };

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
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setCreatingTeam(v => !v)} style={S.btnSecondary}>+ New Team</button>
          <button onClick={() => setInviting(v => !v)} style={S.btnPrimary}>+ Invite Member</button>
        </div>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        <div style={sectionLabel}>Teams</div>
        {creatingTeam && (
          <div style={{ ...S.card, marginBottom: 12 }}>
            <div style={{ ...S.cardTitle, marginBottom: 12 }}>New Team</div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                value={newTeamName} onChange={e => setNewTeamName(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void createTeam()}
                placeholder="Team name" style={{ ...S.textInput, flex: 1 }} autoFocus
              />
              <input
                value={newTeamDesc} onChange={e => setNewTeamDesc(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void createTeam()}
                placeholder="Description (optional)" style={{ ...S.textInput, flex: 2 }}
              />
              <button onClick={() => void createTeam()} disabled={teamSaving || !newTeamName.trim()} style={S.btnPrimary}>
                {teamSaving ? "Creating…" : "Create"}
              </button>
              <button onClick={() => { setCreatingTeam(false); setNewTeamName(""); setNewTeamDesc(""); }} style={S.btnSecondary}>Cancel</button>
            </div>
          </div>
        )}

        {teamsLoading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
            {[1, 2].map(i => <div key={i} className="skeleton" style={{ height: 48, borderRadius: 12 }} />)}
          </div>
        ) : teams.length === 0 ? (
          <div style={{ ...S.card, marginBottom: 20, textAlign: "center", color: "var(--t4)", fontSize: 12, padding: 20 }}>
            No teams yet — create one to group members for project access.
          </div>
        ) : (
          <div style={{ ...S.card, marginBottom: 20 }}>
            {teams.map((t, i) => {
              const isOpen = expandedTeam === t.id;
              const tm = teamMembers[t.id] || [];
              const availableToAdd = members.filter(m => !tm.some(x => x.user_id === m.user_id));
              return (
                <div key={t.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none", padding: "12px 4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div
                      onClick={() => void toggleTeam(t.id)}
                      style={{ flex: 1, minWidth: 0, cursor: "pointer" }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{t.name}</div>
                      {t.description && <div style={{ fontSize: 11, color: "var(--t4)" }}>{t.description}</div>}
                    </div>
                    <button
                      onClick={() => void toggleTeam(t.id)}
                      style={{ ...S.btnSecondary, padding: "5px 12px", fontSize: 11 }}
                    >{isOpen ? "Hide" : "Members"}</button>
                    <button
                      onClick={() => void deleteTeam(t.id)} disabled={teamBusy === t.id}
                      style={{ ...S.btnSecondary, padding: "5px 12px", fontSize: 11, color: C.redSoft }}
                    >Delete</button>
                  </div>

                  {isOpen && (
                    <div style={{ marginTop: 10, marginLeft: 4, paddingLeft: 12, borderLeft: "2px solid var(--border)" }}>
                      {teamMembersLoading === t.id ? (
                        <div className="skeleton" style={{ height: 32, borderRadius: 8 }} />
                      ) : (
                        <>
                          {tm.length === 0 && (
                            <div style={{ fontSize: 11, color: "var(--t4)", marginBottom: 8 }}>No members in this team yet.</div>
                          )}
                          {tm.map(m => (
                            <div key={m.user_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0" }}>
                              <span style={{ fontSize: 12, color: "var(--t1)", flex: 1 }}>{m.name || m.email}</span>
                              <button
                                onClick={() => void removeTeamMember(t.id, m.user_id)}
                                disabled={teamBusy === `${t.id}:${m.user_id}`}
                                style={{ ...S.btnSecondary, padding: "3px 10px", fontSize: 10, color: C.redSoft }}
                              >Remove</button>
                            </div>
                          ))}
                          {availableToAdd.length > 0 && (
                            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                              <select
                                value={addMemberUserId}
                                onChange={e => setAddMemberUserId(e.target.value)}
                                style={{ ...S.textInput, flex: 1, fontSize: 11, padding: "5px 10px" }}
                              >
                                <option value="">Add member…</option>
                                {availableToAdd.map(m => (
                                  <option key={m.user_id} value={m.user_id}>{m.name || m.email}</option>
                                ))}
                              </select>
                              <button
                                onClick={() => void addTeamMember(t.id)}
                                disabled={!addMemberUserId || teamBusy === t.id}
                                style={{ ...S.btnSecondary, padding: "5px 12px", fontSize: 11 }}
                              >Add</button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div style={sectionLabel}>Members</div>
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
                  background: "rgba(255,215,0,.14)", border: "1px solid rgba(255,215,0,.25)",
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
                      style={{ ...S.btnSecondary, padding: "5px 12px", fontSize: 11, color: C.redSoft }}
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
