import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useOrg } from "../../contexts/OrgContext";
import { useToast } from "../../contexts/toast";
import { S, C } from "../../styles/theme";
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

function StatusBadge({ status }: { status: Lead["status"] }) {
  const { t } = useTranslation("leads");
  return (
    <span style={{
      display: "inline-block",
      padding: "2px 8px",
      borderRadius: 10,
      fontSize: 11,
      fontWeight: 600,
      background: STATUS_COLOR[status] + "22",
      color: STATUS_COLOR[status],
      textTransform: "uppercase",
      letterSpacing: "0.04em",
    }}>
      {t(`status.${status}`)}
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

  const load = useCallback(async () => {
    if (!currentOrgId) return;
    setLoading(true);
    setError(false);
    try {
      const url = statusFilter
        ? `/api/leads?status=${statusFilter}&limit=100`
        : "/api/leads?limit=100";
      const res = await apiFetch(url);
      const data = await parseJSON<{ leads: Lead[] }>(res, url);
      setLeads(data.leads);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [currentOrgId, statusFilter]);

  useEffect(() => { load(); }, [load]);

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
