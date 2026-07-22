/**
 * AgentsTab — agent list, creation, and management.
 * CRUD operations against /api/agents. Uses shared S styles.
 */
import { useState } from "react";
import { useToast } from "../../../contexts/toast";
import { apiFetch, authH } from "../../../utils/api";
import { relTime } from "../../../utils/time";
import { AgentAvatar } from "../../../components/ui/AgentAvatar";
import { GoldButton, GlassCard } from "../../../shared/ui/gold";
import type { Agent } from "../../../types";
import { AGENT_TEMPLATES } from "../../../constants";

interface AgentsTabProps {
  agents:        Agent[];
  loading:       boolean;
  onRefresh:     () => void;
  onChatWith:    (agentId: string) => void;
}

type View = "list" | "form";

export function AgentsTab({ agents, loading, onRefresh, onChatWith }: AgentsTabProps) {
  const toast = useToast();
  const [view, setView]           = useState<View>("list");
  const [editing, setEditing]     = useState<Partial<Agent> | null>(null);
  const [saving, setSaving]       = useState(false);

  async function saveAgent() {
    if (!editing?.name?.trim() || !editing?.system_prompt?.trim()) return;
    setSaving(true);
    try {
      const isEdit = !!editing.id;
      const r = await apiFetch(
        isEdit ? `/api/agents/${editing.id}` : "/api/agents",
        { method: isEdit ? "PUT" : "POST", headers: authH(), body: JSON.stringify(editing) },
      );
      if (!r.ok) throw new Error();
      toast(isEdit ? "Agent updated" : "Agent created");
      setView("list"); setEditing(null); onRefresh();
    } catch { toast("Failed to save", "err"); }
    finally { setSaving(false); }
  }

  async function deleteAgent(id: string, name: string) {
    if (!confirm(`Delete agent "${name}"?`)) return;
    await apiFetch(`/api/agents/${id}`, { method: "DELETE" });
    toast(`Deleted ${name}`); onRefresh();
  }

  function openForm(template?: Partial<Agent>) {
    setEditing(template ?? { avatar: "🤖", model: "claude-sonnet-4-6", temperature: 1 });
    setView("form");
  }

  // ── Form view ─────────────────────────────────────────────────────────────
  if (view === "form") {
    return (
      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ width: 70 }}>
              <label className="g-label" htmlFor="agent-avatar">Avatar</label>
              <input id="agent-avatar" value={editing?.avatar ?? "🤖"} onChange={e => setEditing(p => ({ ...p, avatar: e.target.value }))}
                className="g-input" style={{ textAlign: "center", fontSize: 24 }} maxLength={2} />
            </div>
            <div style={{ flex: 1 }}>
              <label className="g-label" htmlFor="agent-name">Name *</label>
              <input id="agent-name" value={editing?.name ?? ""} onChange={e => setEditing(p => ({ ...p, name: e.target.value }))}
                className="g-input" placeholder="My Agent" autoFocus />
            </div>
          </div>
          <div>
            <label className="g-label" htmlFor="agent-description">Description</label>
            <input id="agent-description" value={editing?.description ?? ""} onChange={e => setEditing(p => ({ ...p, description: e.target.value }))}
              className="g-input" placeholder="What does this agent do?" />
          </div>
          <div>
            <label className="g-label" htmlFor="agent-system-prompt">System Prompt *</label>
            <textarea id="agent-system-prompt" value={editing?.system_prompt ?? ""} onChange={e => setEditing(p => ({ ...p, system_prompt: e.target.value }))}
              className="g-input" style={{ minHeight: 200, lineHeight: 1.6 }} placeholder="You are an expert in…" />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ flex: 1 }}>
              <label className="g-label" htmlFor="agent-model">Model</label>
              <select id="agent-model" value={editing?.model ?? "claude-sonnet-4-6"} onChange={e => setEditing(p => ({ ...p, model: e.target.value }))} className="g-input">
                <option value="claude-sonnet-4-6">Sonnet 4.6 (recommended)</option>
                <option value="claude-opus-4-8">Opus 4.8 (most capable)</option>
                <option value="claude-haiku-4-5-20251001">Haiku 4.5 (fastest)</option>
              </select>
            </div>
            <div style={{ width: 100 }}>
              <label className="g-label" htmlFor="agent-temperature">Temperature</label>
              <input id="agent-temperature" type="number" min={0} max={1} step={0.1} value={editing?.temperature ?? 1}
                onChange={e => setEditing(p => ({ ...p, temperature: parseFloat(e.target.value) }))} className="g-input" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <GoldButton
              onClick={() => void saveAgent()}
              disabled={saving || !editing?.name?.trim() || !editing?.system_prompt?.trim()}
            >{saving ? "Saving…" : "Save Agent"}</GoldButton>
            <GoldButton variant="ghost" onClick={() => { setView("list"); setEditing(null); }}>Cancel</GoldButton>
          </div>
        </div>
      </div>
    );
  }

  // ── List view ─────────────────────────────────────────────────────────────
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
      {loading && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: 12 }}>
          {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 140, borderRadius: 14 }} />)}
        </div>
      )}

      {!loading && agents.length === 0 && (
        <div className="empty-state" style={{ padding: "60px 24px" }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" style={{ color: "var(--t5)", marginBottom: 12 }}>
            <path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/>
            <path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/>
          </svg>
          <div style={{ fontWeight: 600, color: "var(--t1)", marginBottom: 6 }}>No agents yet</div>
          <div style={{ color: "var(--t4)", fontSize: 13, marginBottom: 16 }}>Create your first agent or start from a template below</div>
          <GoldButton onClick={() => openForm()}>+ New Agent</GoldButton>
        </div>
      )}

      {!loading && agents.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 12 }}>MY AGENTS</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: 12 }}>
            {agents.map(a => {
              const modelLabel = a.model?.includes("opus") ? "Opus" : a.model?.includes("haiku") ? "Haiku" : "Sonnet";
              const modelVar = a.model?.includes("opus") ? "var(--ta)" : a.model?.includes("haiku") ? "var(--green)" : "var(--blue)";
              const modelDim = a.model?.includes("opus") ? "var(--accent-dim)" : a.model?.includes("haiku") ? "var(--green-dim)" : "var(--blue-dim)";
              return (
                <GlassCard key={a.id} lift={false} style={{ position: "relative", overflow: "hidden" }}>
                  <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, ${modelVar}, transparent)` }} />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ display: "flex", gap: 12, alignItems: "center", flex: 1, minWidth: 0 }}>
                      <AgentAvatar name={a.name} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
                          <span style={{ flexShrink: 0, fontSize: 10, fontWeight: 600, padding: "1px 7px", borderRadius: 20, background: modelDim, color: modelVar, border: "1px solid var(--border)" }}>{modelLabel}</span>
                        </div>
                        {a.description && <div style={{ fontSize: 12, color: "var(--t4)", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.description}</div>}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
                      <button onClick={() => onChatWith(a.id)} className="btn-icon" title="Chat" style={{ width: 30, height: 30 }}>
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                      </button>
                      <button onClick={() => openForm(a)} className="btn-icon" title="Edit" style={{ width: 30, height: 30 }}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                      </button>
                      <button onClick={() => void deleteAgent(a.id, a.name)} className="btn-icon" title="Delete" style={{ width: 30, height: 30, color: "var(--red)" }}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>
                      </button>
                    </div>
                  </div>
                  <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)", display: "flex", gap: 16, alignItems: "center" }}>
                    <span style={{ fontSize: 11, color: "var(--t4)" }}>{a.message_count ?? 0} messages</span>
                    <span style={{ fontSize: 11, color: "var(--t4)" }}>{relTime(a.created_at)}</span>
                    <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 5 }}>
                      <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)" }} />
                      <span style={{ fontSize: 11, color: "var(--green)" }}>Ready</span>
                    </div>
                  </div>
                </GlassCard>
              );
            })}
          </div>
        </div>
      )}

      {/* Templates */}
      <div>
        <div className="section-label" style={{ marginBottom: 12 }}>QUICK START TEMPLATES</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: 12 }}>
          {AGENT_TEMPLATES.map(t => (
            <div
              key={t.name}
              className="project-card"
              role="button" tabIndex={0}
              style={{ cursor: "pointer" }}
              onClick={() => openForm({ name: t.name, avatar: t.avatar, description: t.description, system_prompt: t.system_prompt, model: "claude-sonnet-4-6", temperature: 1 })}
              onKeyDown={e => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  openForm({ name: t.name, avatar: t.avatar, description: t.description, system_prompt: t.system_prompt, model: "claude-sonnet-4-6", temperature: 1 });
                }
              }}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, background: "var(--bg-hover)", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, flexShrink: 0 }}>{t.avatar}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 4 }}>{t.name}</div>
                  <div style={{ fontSize: 12, color: "var(--t4)", lineHeight: 1.5 }}>{t.description}</div>
                </div>
              </div>
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 11, color: "var(--t4)" }}>Template</span>
                <span style={{ fontSize: 11, color: "var(--blue)", display: "flex", alignItems: "center", gap: 4 }}>
                  Use template
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
