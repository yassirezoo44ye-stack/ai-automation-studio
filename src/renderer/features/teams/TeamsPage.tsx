/**
 * TeamsPage — teams, members, and invitations for the current organization.
 * Data: GET/PATCH/DELETE /api/orgs/{id}/members*, POST .../invitations,
 *       GET/POST/PATCH/DELETE /api/orgs/{id}/teams*
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/toast";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";
import { GoldButton, GlassCard } from "../../shared/ui/gold";
import { EmptyState } from "../../shared/ui/EmptyState";

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
// Solid color (badge text/border) + the matching pre-mixed "-dim" token
// (badge background) — every value here is an existing design token, no
// hardcoded hex, no new CSS.
const ROLE_COLOR: Record<Role, string> = {
  owner: "var(--yellow)", admin: "var(--red)", manager: "var(--accent)",
  developer: "var(--blue)", operator: "var(--green)", viewer: "var(--t4)",
};
const ROLE_BG: Record<Role, string> = {
  owner: "var(--yellow-dim)", admin: "var(--red-dim)", manager: "var(--accent-dim)",
  developer: "var(--blue-dim)", operator: "var(--green-dim)", viewer: "var(--bg-hover)",
};

export function TeamsPage() {
  const toast = useToast();
  const { currentOrgId, currentOrg, orgs } = useOrg();
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [membersError, setMembersError] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("viewer");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [teams, setTeams] = useState<Team[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(true);
  const [teamsError, setTeamsError] = useState(false);
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
    setMembersError(false);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/members`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ members: Member[] }>(r, "/api/orgs/{id}/members");
      setMembers(d.members);
    } catch {
      toast("Could not load members", "err");
      setMembers([]);
      setMembersError(true);
    } finally { setLoading(false); }
  }, [currentOrgId, toast]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const loadTeams = useCallback(async () => {
    if (!currentOrgId) { setTeams([]); setTeamsLoading(false); return; }
    setTeamsLoading(true);
    setTeamsError(false);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/teams`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ teams: Team[] }>(r, "/api/orgs/{id}/teams");
      setTeams(d.teams);
    } catch {
      toast("Could not load teams", "err");
      setTeams([]);
      setTeamsError(true);
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
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>👥</span>}
        title="No organization selected"
        description={orgs.length === 0 ? "Create an organization first." : "Pick one from the Organizations page."}
      />
    );
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Teams — {currentOrg?.name ?? "…"}</span>
        <div style={{ display: "flex", gap: 8 }}>
          <GoldButton variant="ghost" onClick={() => setCreatingTeam(v => !v)}>+ New Team</GoldButton>
          <GoldButton onClick={() => setInviting(v => !v)}>+ Invite Member</GoldButton>
        </div>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        <div className="section-label" style={{ marginBottom: 8 }}>Teams</div>
        {creatingTeam && (
          <GlassCard lift={false} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 12 }}>New Team</div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                value={newTeamName} onChange={e => setNewTeamName(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void createTeam()}
                placeholder="Team name" className="g-input" style={{ flex: 1 }} autoFocus
              />
              <input
                value={newTeamDesc} onChange={e => setNewTeamDesc(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void createTeam()}
                placeholder="Description (optional)" className="g-input" style={{ flex: 2 }}
              />
              <GoldButton onClick={() => void createTeam()} disabled={teamSaving || !newTeamName.trim()}>
                {teamSaving ? "Creating…" : "Create"}
              </GoldButton>
              <GoldButton variant="ghost" onClick={() => { setCreatingTeam(false); setNewTeamName(""); setNewTeamDesc(""); }}>Cancel</GoldButton>
            </div>
          </GlassCard>
        )}

        {teamsLoading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
            {[1, 2].map(i => <div key={i} className="skeleton" style={{ height: 48, borderRadius: 12 }} />)}
          </div>
        ) : teamsError ? (
          <div style={{ marginBottom: 20 }}>
            <EmptyState
              icon={<span style={{ fontSize: 40 }}>⚠️</span>}
              title="Could not load teams"
              description="Something went wrong reaching the server."
              action={<GoldButton variant="ghost" onClick={() => void loadTeams()}>Retry</GoldButton>}
            />
          </div>
        ) : teams.length === 0 ? (
          <GlassCard lift={false} style={{ marginBottom: 20, textAlign: "center", color: "var(--t4)", fontSize: 12, padding: 20 }}>
            No teams yet — create one to group members for project access.
          </GlassCard>
        ) : (
          <GlassCard lift={false} style={{ marginBottom: 20 }}>
            {teams.map((t, i) => {
              const isOpen = expandedTeam === t.id;
              const tm = teamMembers[t.id] || [];
              const availableToAdd = members.filter(m => !tm.some(x => x.user_id === m.user_id));
              return (
                <div key={t.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none", padding: "12px 4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div
                      role="button" tabIndex={0}
                      onClick={() => void toggleTeam(t.id)}
                      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void toggleTeam(t.id); } }}
                      style={{ flex: 1, minWidth: 0, cursor: "pointer" }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{t.name}</div>
                      {t.description && <div style={{ fontSize: 11, color: "var(--t4)" }}>{t.description}</div>}
                    </div>
                    <GoldButton
                      variant="ghost" onClick={() => void toggleTeam(t.id)}
                      style={{ padding: "5px 12px", fontSize: 11 }}
                    >{isOpen ? "Hide" : "Members"}</GoldButton>
                    <GoldButton
                      variant="danger" onClick={() => void deleteTeam(t.id)} disabled={teamBusy === t.id}
                      style={{ padding: "5px 12px", fontSize: 11 }}
                    >Delete</GoldButton>
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
                              <GoldButton
                                variant="danger" onClick={() => void removeTeamMember(t.id, m.user_id)}
                                disabled={teamBusy === `${t.id}:${m.user_id}`}
                                style={{ padding: "3px 10px", fontSize: 10 }}
                              >Remove</GoldButton>
                            </div>
                          ))}
                          {availableToAdd.length > 0 && (
                            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                              <select
                                value={addMemberUserId}
                                onChange={e => setAddMemberUserId(e.target.value)}
                                className="g-input" style={{ flex: 1, fontSize: 11, padding: "5px 10px" }}
                              >
                                <option value="">Add member…</option>
                                {availableToAdd.map(m => (
                                  <option key={m.user_id} value={m.user_id}>{m.name || m.email}</option>
                                ))}
                              </select>
                              <GoldButton
                                variant="ghost" onClick={() => void addTeamMember(t.id)}
                                disabled={!addMemberUserId || teamBusy === t.id}
                                style={{ padding: "5px 12px", fontSize: 11 }}
                              >Add</GoldButton>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </GlassCard>
        )}

        <div className="section-label" style={{ marginBottom: 8 }}>Members</div>
        {inviting && (
          <GlassCard lift={false} style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 12 }}>Invite by Email</div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                value={inviteEmail} onChange={e => setInviteEmail(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void invite()}
                placeholder="teammate@company.com" type="email" className="g-input" style={{ flex: 1 }} autoFocus
              />
              <select value={inviteRole} onChange={e => setInviteRole(e.target.value as Role)} className="g-input" style={{ width: "auto" }}>
                {ROLES.filter(r => r !== "owner").map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <GoldButton onClick={() => void invite()} disabled={saving || !inviteEmail.trim()}>
                {saving ? "Sending…" : "Send Invite"}
              </GoldButton>
              <GoldButton variant="ghost" onClick={() => { setInviting(false); setInviteEmail(""); }}>Cancel</GoldButton>
            </div>
          </GlassCard>
        )}

        {loading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 56, borderRadius: 12 }} />)}
          </div>
        ) : membersError ? (
          <EmptyState
            icon={<span style={{ fontSize: 40 }}>⚠️</span>}
            title="Could not load members"
            description="Something went wrong reaching the server."
            action={<GoldButton variant="ghost" onClick={() => void load()}>Retry</GoldButton>}
          />
        ) : members.length === 0 ? (
          <EmptyState icon={<span style={{ fontSize: 40 }}>👥</span>} title="No members yet" />
        ) : (
          <GlassCard lift={false}>
            {members.map((m, i) => (
              <div key={m.user_id} style={{
                padding: "12px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
                display: "flex", alignItems: "center", gap: 12,
              }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                  background: "var(--accent-dim)", border: "1px solid var(--accent-border)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, fontWeight: 700, color: "var(--accent)",
                }}>
                  {(m.name || m.email)[0]?.toUpperCase()}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{m.name || m.email}</div>
                  <div style={{ fontSize: 11, color: "var(--t4)" }}>{m.email}</div>
                </div>
                <span style={{
                  fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 99,
                  color: ROLE_COLOR[m.role], background: ROLE_BG[m.role],
                  border: `1px solid ${ROLE_BG[m.role]}`,
                }}>
                  {m.role}
                </span>
                {m.role !== "owner" && (
                  <>
                    <select
                      value={m.role} disabled={busy === m.user_id}
                      onChange={e => void changeRole(m.user_id, e.target.value as Role)}
                      className="g-input" style={{ width: "auto", fontSize: 11, padding: "5px 10px" }}
                    >
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <GoldButton
                      variant="danger" onClick={() => void removeMember(m.user_id)} disabled={busy === m.user_id}
                      style={{ padding: "5px 12px", fontSize: 11 }}
                    >Remove</GoldButton>
                  </>
                )}
              </div>
            ))}
          </GlassCard>
        )}
      </div>
    </>
  );
}
