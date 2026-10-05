import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON, APIError } from "../../shared/utils/api";
import { useOrg } from "../../contexts/OrgContext";
import { useToast } from "../../contexts/toast";
import { C } from "../../styles/theme";
import { GoldButton, GlassCard } from "../../shared/ui/gold";
import { relTime } from "../../utils/time";

interface Lead {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  source: string | null;
  status: "new" | "qualified" | "contacted" | "won" | "lost";
  ai_score: number | null;
  ai_notes: string | null;
  created_at: string;
  updated_at: string;
}

// ─── Lead Follow-up Automation Card ─────────────────────────────────────────

interface AutomationDefinition {
  id: string;
  name: string;
  definition: Record<string, unknown>;
  is_active: boolean;
}

interface AutomationListResponse {
  items: AutomationDefinition[];
  total: number;
}

function makeFollowupPayload(subject: string, bodyText: string) {
  return {
    name: "lead-followup",
    description: "Automatic email follow-up for new leads",
    definition: {
      // String literal required — leads.py queries: definition->>'lead_followup' = 'true'
      lead_followup: "true",
      steps: [{ kind: "email", subject, body: bodyText }],
    },
    triggers: [] as unknown[],
    is_active: true,
  };
}

export function LeadFollowupCard({ orgId }: { orgId: string | null }) {
  const { t } = useTranslation("leads");
  const toast = useToast();
  const [def, setDef] = useState<AutomationDefinition | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [permDenied, setPermDenied] = useState(false);
  const [subject, setSubject] = useState("");
  const [emailBody, setEmailBody] = useState("");

  useEffect(() => {
    if (!orgId) return;
    apiFetch("/api/automations?active_only=false&limit=50")
      .then(r => parseJSON<AutomationListResponse>(r, "/api/automations"))
      .then(data => {
        const found = data.items.find(d => d.definition?.lead_followup === "true");
        if (found) {
          setDef(found);
          const step = (found.definition.steps as Array<{ subject?: string; body?: string }> | undefined)?.[0];
          setSubject(step?.subject ?? t("followUpSetup.defaultSubject"));
          setEmailBody(step?.body ?? t("followUpSetup.defaultBody"));
        } else {
          setDef(null);
          setSubject(t("followUpSetup.defaultSubject"));
          setEmailBody(t("followUpSetup.defaultBody"));
        }
      })
      .catch(() => setDef(null));
  }, [orgId, t]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setPermDenied(false);
    const payload = makeFollowupPayload(subject.trim(), emailBody.trim());
    try {
      let saved: AutomationDefinition;
      if (def) {
        // Existing definition — update in place, never create a duplicate
        const res = await apiFetch(`/api/automations/${def.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        saved = await parseJSON<AutomationDefinition>(res, `/api/automations/${def.id}`);
      } else {
        const res = await apiFetch("/api/automations", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (res.status === 409) {
          // Race: another session created the definition between our GET and this POST.
          // Fetch it and update in place.
          const listRes = await apiFetch("/api/automations?active_only=false&limit=50");
          const listData = await parseJSON<AutomationListResponse>(listRes, "/api/automations");
          const existing = listData.items.find(d => d.definition?.lead_followup === "true");
          if (!existing) throw new Error("Conflict but no existing definition found");
          const putRes = await apiFetch(`/api/automations/${existing.id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          saved = await parseJSON<AutomationDefinition>(putRes, `/api/automations/${existing.id}`);
        } else {
          saved = await parseJSON<AutomationDefinition>(res, "/api/automations");
        }
      }
      setDef(saved);
      setOpen(false);
      toast(t("followUpSetup.saved"), "ok");
    } catch (err) {
      if (err instanceof APIError && err.details.status === 403) {
        setPermDenied(true);
      } else {
        toast(t("states.error"), "err");
      }
    } finally {
      setSaving(false);
    }
  }

  // Suppress flash during initial load; hide entirely when no org is selected
  if (!orgId || def === undefined) return null;

  const isActive = def !== null && def.is_active;

  return (
    <GlassCard
      style={{
        padding: "14px 18px",
        marginBottom: 16,
        borderLeft: `3px solid ${isActive ? C.green : C.amber}`,
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 13, color: "var(--t1)" }}>
            {t("followUpSetup.title")}
          </span>
          {isActive ? (
            <span style={{ fontSize: 11, fontWeight: 600, color: C.green, background: C.green + "22", padding: "2px 8px", borderRadius: 10 }}>
              ✓ {t("followUpSetup.active")}
            </span>
          ) : (
            <span style={{ fontSize: 11, fontWeight: 600, color: C.amber, background: C.amber + "22", padding: "2px 8px", borderRadius: 10 }}>
              {t("followUpSetup.setup")}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => { setOpen(v => !v); setPermDenied(false); }}
          style={{ background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 12 }}
        >
          {open ? "▲" : (isActive ? t("followUpSetup.edit") : t("followUpSetup.configure"))}
        </button>
      </div>

      {/* Subtitle when not yet configured */}
      {!open && !isActive && (
        <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--t4)" }}>
          {t("followUpSetup.subtitle")}
        </p>
      )}

      {/* Permission denied — shown inline, not as toast */}
      {permDenied && (
        <div
          role="alert"
          style={{
            marginTop: 8, fontSize: 12, color: C.amber,
            background: C.amber + "11", padding: "8px 12px", borderRadius: 6,
          }}
        >
          {t("followUpSetup.permissionDenied")}
        </div>
      )}

      {/* Configuration form */}
      {open && (
        <form onSubmit={handleSave} style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
            {t("followUpSetup.subjectLabel")}
          </label>
          <input
            value={subject}
            onChange={e => setSubject(e.target.value)}
            required
            placeholder={t("followUpSetup.defaultSubject")}
            style={{
              background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8, padding: "8px 12px", fontSize: 13, color: "var(--t1)", outline: "none",
            }}
          />
          <label style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
            {t("followUpSetup.bodyLabel")}
          </label>
          <textarea
            value={emailBody}
            onChange={e => setEmailBody(e.target.value)}
            required
            rows={3}
            placeholder={t("followUpSetup.defaultBody")}
            style={{
              background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8, padding: "8px 12px", fontSize: 13, color: "var(--t1)", outline: "none",
              resize: "vertical", fontFamily: "inherit",
            }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <GoldButton type="submit" disabled={saving || !subject.trim() || !emailBody.trim()}>
              {saving ? "…" : t("followUpSetup.activate")}
            </GoldButton>
            <button
              type="button"
              onClick={() => { setOpen(false); setPermDenied(false); }}
              style={{ background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 13 }}
            >
              {t("followUpSetup.cancel")}
            </button>
          </div>
        </form>
      )}
    </GlassCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<Lead["status"], string> = {
  new:       C.gray,
  qualified: C.blue,
  contacted: C.amber,
  won:       C.green,
  lost:      C.red,
};

function ScoreBadge({ score }: { score: number | null }) {
  const { t } = useTranslation("leads");
  if (score === null) return <span style={{ color: "var(--t4)", fontSize: 12 }}>{t("score.na")}</span>;
  const color = score >= 7 ? C.green : score >= 4 ? C.amber : C.red;
  return (
    <span style={{ fontWeight: 700, fontSize: 13, color }}>
      {t("score.label", { score })}
    </span>
  );
}

function AddLeadForm({ onAdd }: { onAdd: (lead: Lead) => void }) {
  const { t } = useTranslation("leads");
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", phone: "", source: "" });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const res = await apiFetch("/api/leads", {
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          email: form.email.trim() || undefined,
          phone: form.phone.trim() || undefined,
          source: form.source.trim() || undefined,
        }),
      });
      const data = await parseJSON<Lead & { follow_up_status?: string }>(res, "/api/leads");
      onAdd(data);
      setForm({ name: "", email: "", phone: "", source: "" });
      setOpen(false);
      const followKey = data.follow_up_status as keyof typeof t | undefined;
      const followMsg = followKey ? t(`followUp.${followKey}` as never, { defaultValue: "" }) : "";
      toast(followMsg || t("actions.addLead"), "ok");
    } catch {
      toast(t("states.error"), "err");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <GoldButton onClick={() => setOpen(true)} style={{ marginBottom: 16 }}>
        + {t("actions.addLead")}
      </GoldButton>
    );
  }

  return (
    <GlassCard style={{ padding: "18px 20px", marginBottom: 20 }}>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {(["name", "email", "phone", "source"] as const).map(field => (
            <input
              key={field}
              required={field === "name"}
              placeholder={t(`form.${field}Placeholder` as never)}
              value={form[field]}
              onChange={e => setForm(p => ({ ...p, [field]: e.target.value }))}
              style={{
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 8,
                padding: "8px 12px",
                fontSize: 13,
                color: "var(--t1)",
                outline: "none",
              }}
            />
          ))}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <GoldButton type="submit" disabled={saving || !form.name.trim()}>
            {saving ? "…" : t("actions.addLead")}
          </GoldButton>
          <button
            type="button"
            onClick={() => setOpen(false)}
            style={{ background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 13 }}
          >
            Cancel
          </button>
        </div>
      </form>
    </GlassCard>
  );
}

function LeadRow({ lead, onStatusChange }: {
  lead: Lead;
  onStatusChange: (id: string, status: Lead["status"]) => void;
}) {
  const { t } = useTranslation("leads");
  const toast = useToast();
  const STATUSES: Lead["status"][] = ["new", "qualified", "contacted", "won", "lost"];

  async function handleStatusChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value as Lead["status"];
    try {
      const res = await apiFetch(`/api/leads/${lead.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      await parseJSON(res, `/api/leads/${lead.id}/status`);
      onStatusChange(lead.id, next);
    } catch {
      toast(t("states.error"), "err");
    }
  }

  return (
    <GlassCard style={{ padding: "12px 16px", display: "grid", gridTemplateColumns: "1fr 100px 120px 80px 1fr 90px", gap: 12, alignItems: "center", fontSize: 13 }}>
      <div>
        <div style={{ fontWeight: 600, color: "var(--t1)" }}>{lead.name}</div>
        {lead.email && <div style={{ color: "var(--t3)", fontSize: 11 }}>{lead.email}</div>}
        {lead.phone && <div style={{ color: "var(--t4)", fontSize: 11 }}>{lead.phone}</div>}
      </div>
      <div style={{ color: "var(--t3)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {lead.source || "—"}
      </div>
      <div>
        <select
          value={lead.status}
          onChange={handleStatusChange}
          style={{
            background: "rgba(255,255,255,0.06)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 6,
            padding: "3px 6px",
            color: STATUS_COLOR[lead.status],
            fontSize: 11,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {STATUSES.map(s => (
            <option key={s} value={s}>{t(`status.${s}`)}</option>
          ))}
        </select>
      </div>
      <ScoreBadge score={lead.ai_score} />
      <div style={{ color: "var(--t3)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={lead.ai_notes ?? ""}>
        {lead.ai_notes || "—"}
      </div>
      <div style={{ color: "var(--t4)", fontSize: 11, textAlign: "right" }}>{relTime(lead.created_at)}</div>
    </GlassCard>
  );
}

export function LeadsPage() {
  const { t } = useTranslation("leads");
  const { currentOrgId } = useOrg();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [statusFilter, setStatusFilter] = useState<Lead["status"] | "">("");

  useEffect(() => {
    if (!currentOrgId) return;
    const url = statusFilter
      ? `/api/leads?status=${statusFilter}&limit=100`
      : "/api/leads?limit=100";
    let active = true;
    apiFetch(url)
      .then(res => parseJSON<{ leads: Lead[] }>(res, url))
      .then(data => {
        if (active) { setLeads(data.leads); setError(false); setLoading(false); }
      })
      .catch(() => {
        if (active) { setError(true); setLoading(false); }
      });
    return () => { active = false; setLoading(true); setError(false); };
  }, [currentOrgId, statusFilter]);

  function handleAdd(lead: Lead) {
    setLeads(prev => [lead, ...prev]);
  }

  function handleStatusChange(id: string, status: Lead["status"]) {
    setLeads(prev => prev.map(l => l.id === id ? { ...l, status } : l));
  }

  const STATUSES: Array<Lead["status"] | ""> = ["", "new", "qualified", "contacted", "won", "lost"];

  return (
    <div style={{ padding: "24px 28px", maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", margin: 0 }}>{t("page.title")}</h1>
        <p style={{ fontSize: 13, color: "var(--t3)", margin: "4px 0 0" }}>{t("page.subtitle")}</p>
      </div>

      <AddLeadForm onAdd={handleAdd} />

      <LeadFollowupCard key={currentOrgId ?? "none"} orgId={currentOrgId} />

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {STATUSES.map(s => (
          <button
            key={s || "all"}
            onClick={() => setStatusFilter(s)}
            style={{
              padding: "4px 12px",
              borderRadius: 16,
              border: "1px solid rgba(255,255,255,0.1)",
              background: statusFilter === s ? "rgba(255,255,255,0.12)" : "transparent",
              color: s ? STATUS_COLOR[s] : "var(--t2)",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {s ? t(`status.${s}`) : "All"}
          </button>
        ))}
      </div>

      {loading && (
        <div style={{ textAlign: "center", color: "var(--t3)", padding: 48 }}>{t("states.loading")}</div>
      )}

      {!loading && error && (
        <div role="alert" style={{ textAlign: "center", color: C.red, padding: 48 }}>{t("states.error")}</div>
      )}

      {!loading && !error && leads.length === 0 && (
        <div role="status" style={{ textAlign: "center", padding: 48 }}>
          <p style={{ color: "var(--t2)", fontWeight: 600 }}>{t("states.empty")}</p>
          <p style={{ color: "var(--t4)", fontSize: 13 }}>{t("states.emptyHint")}</p>
        </div>
      )}

      {!loading && !error && leads.length > 0 && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 100px 120px 80px 1fr 90px", gap: 12, padding: "4px 16px", marginBottom: 4 }}>
            {(["name", "source", "status", "aiScore", "aiNotes", "createdAt"] as const).map(col => (
              <div key={col} style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {t(`table.${col}`)}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {leads.map(lead => (
              <LeadRow key={lead.id} lead={lead} onStatusChange={handleStatusChange} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
