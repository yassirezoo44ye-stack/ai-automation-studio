import { useState, useEffect, useCallback } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON, APIError } from "../../shared/utils/api";
import { useOrg } from "../../contexts/OrgContext";
import { useToast } from "../../contexts/toast";
import { C } from "../../styles/theme";
import { GoldButton, GlassCard } from "../../shared/ui/gold";
import { EmptyState } from "../../shared/ui/EmptyState";
import { relTime } from "../../utils/time";
import "./leads.css";

interface Lead {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  source: string | null;
  status: "new" | "qualified" | "contacted" | "won" | "lost";
  ai_score: number | null;
  ai_tier?: "hot" | "warm" | "cold" | null;
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
      // Engine (_execute_definition) requires each step to have an 'id' field.
      // _make_email_step_fn reads subject/body from spec["args"], not top-level.
      steps: [{ id: "send-followup-email", kind: "email", args: { subject, body: bodyText } }],
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
          const step = (found.definition.steps as Array<{ args?: { subject?: string; body?: string } }> | undefined)?.[0];
          setSubject(step?.args?.subject ?? t("followUpSetup.defaultSubject"));
          setEmailBody(step?.args?.body ?? t("followUpSetup.defaultBody"));
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

type Tier = "hot" | "warm" | "cold";
type Column = Tier | "unscored";
const STATUSES: Lead["status"][] = ["new", "qualified", "contacted", "won", "lost"];
const COLUMNS: Column[] = ["hot", "warm", "cold", "unscored"];
const columnOf = (lead: Lead): Column => lead.ai_tier ?? "unscored";

type Brief = {
  stats: { total: number; open: number; tiers: Record<Column, number> };
  summary: string | null;
  actions: { lead_id: string; name: string; action: string }[];
};
type FollowupDraft = { leadId: string; name: string; email: string | null; subject: string; body: string };

function aiErrorKey(err: unknown): "ai.failed" | "ai.quota" | "states.actionError" {
  // AI routes answer 502 when the model's answer is unusable and 429 on quota.
  if (err instanceof APIError && err.details.status === 502) return "ai.failed";
  if (err instanceof APIError && err.details.status === 429) return "ai.quota";
  return "states.actionError";
}

function language(lang: string) {
  return lang.startsWith("ar") ? "ar" : "en";
}

function ScoreRing({ score, tier }: { score: number | null; tier?: Lead["ai_tier"] }) {
  const { t } = useTranslation("leads");
  if (score === null) return <span className="leads-ring is-empty" role="img" aria-label={t("score.na")}><span>–</span></span>;
  return (
    <span className={`leads-ring is-${tier ?? "unscored"}`} style={{ "--score": score * 10 } as CSSProperties}
      role="img" aria-label={t("score.aria", { score })}>
      <span>{score}</span>
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
      toast(t("states.actionError"), "err");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return <GoldButton onClick={() => setOpen(true)}>+ {t("actions.addLead")}</GoldButton>;
  }

  return (
    <GlassCard className="leads-add">
      <form onSubmit={handleSubmit}>
        <p className="leads-muted"><b className="leads-ai-badge">AI</b>{t("form.aiNote")}</p>
        <div className="leads-add-grid">
          {(["name", "email", "phone", "source"] as const).map(field => (
            <label key={field}>{t(`form.${field}`)}
              <input
                required={field === "name"}
                type={field === "email" ? "email" : field === "phone" ? "tel" : "text"}
                placeholder={t(`form.${field}Placeholder` as never)}
                value={form[field]}
                onChange={e => setForm(p => ({ ...p, [field]: e.target.value }))}
              />
            </label>
          ))}
        </div>
        <div className="leads-row">
          <GoldButton type="submit" disabled={saving || !form.name.trim()}>
            {saving ? t("ai.working") : t("actions.addLead")}
          </GoldButton>
          <button type="button" className="leads-link" onClick={() => setOpen(false)}>{t("form.cancel")}</button>
        </div>
      </form>
    </GlassCard>
  );
}

function LeadCard({ lead, highlighted, busy, onStatus, onRequalify, onDraft }: {
  lead: Lead;
  highlighted: boolean;
  busy: string | null;
  onStatus: (lead: Lead, status: Lead["status"]) => void;
  onRequalify: (lead: Lead) => void;
  onDraft: (lead: Lead) => void;
}) {
  const { t } = useTranslation("leads");
  const working = busy !== null;
  return (
    <article id={`lead-${lead.id}`} className={`leads-card is-${columnOf(lead)}${highlighted ? " is-highlighted" : ""}`}>
      <header>
        <ScoreRing score={lead.ai_score} tier={lead.ai_tier} />
        <div className="leads-card-title">
          <h3>{lead.name}</h3>
          <p>{lead.source || t("card.noSource")} · {relTime(lead.created_at)}</p>
        </div>
        {lead.ai_tier && <span className={`leads-pill is-${lead.ai_tier}`}>{t(`tier.${lead.ai_tier}`)}</span>}
      </header>
      {(lead.email || lead.phone) && (
        <p className="leads-contact">
          {lead.email && <a href={`mailto:${lead.email}`}>{lead.email}</a>}
          {lead.phone && <a href={`tel:${lead.phone}`}>{lead.phone}</a>}
        </p>
      )}
      <p className="leads-notes">{lead.ai_notes || t("card.noNotes")}</p>
      <div className="leads-row">
        <select aria-label={t("card.statusFor", { name: lead.name })} value={lead.status} disabled={working}
          className={`leads-status is-${lead.status}`}
          onChange={e => onStatus(lead, e.target.value as Lead["status"])}>
          {STATUSES.map(s => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
        </select>
        <button type="button" className="leads-ai-button" disabled={working} onClick={() => onDraft(lead)}>
          {busy === `draft-${lead.id}` ? t("ai.working") : t("actions.draftFollowup")}
        </button>
        <button type="button" className="leads-ghost" disabled={working} onClick={() => onRequalify(lead)}>
          {busy === `qualify-${lead.id}` ? t("ai.working") : t("actions.requalifyAi")}
        </button>
      </div>
    </article>
  );
}

function BriefPanel({ brief, busy, onRun, onJump }: {
  brief: Brief | null; busy: boolean; onRun: () => void; onJump: (id: string) => void;
}) {
  const { t } = useTranslation("leads");
  return (
    <section className="leads-brief" aria-labelledby="leads-brief-title">
      <div className="leads-brief-head">
        <h2 id="leads-brief-title"><b className="leads-ai-badge">AI</b>{t("brief.title")}</h2>
        <button type="button" className="leads-ai-button" disabled={busy} onClick={onRun}>
          {busy ? t("ai.working") : t(brief ? "brief.refresh" : "brief.run")}
        </button>
      </div>
      {!brief && <p className="leads-muted">{t("brief.intro")}</p>}
      {brief && !brief.summary && <p className="leads-muted">{t("brief.empty")}</p>}
      {brief?.summary && <>
        <p>{brief.summary}</p>
        {brief.actions.length > 0 && <>
          <h3>{t("brief.actions")}</h3>
          <ol className="leads-actions">
            {brief.actions.map(a => <li key={a.lead_id}>
              <button type="button" className="leads-link" onClick={() => onJump(a.lead_id)}>{a.name}</button>
              <span>{a.action}</span>
            </li>)}
          </ol>
        </>}
        <p className="leads-muted">{t("brief.note")}</p>
      </>}
    </section>
  );
}

function CreateOrgForm() {
  const { t } = useTranslation("leads");
  const { createOrg } = useOrg();
  const toast = useToast();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      await createOrg(name.trim());
    } catch {
      toast(t("noOrg.createError"), "err");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="leads-row leads-center">
      <input
        aria-label={t("noOrg.namePlaceholder")}
        placeholder={t("noOrg.namePlaceholder")}
        value={name}
        onChange={e => setName(e.target.value)}
      />
      <GoldButton type="submit" disabled={saving || !name.trim()}>
        {saving ? "…" : t("noOrg.create")}
      </GoldButton>
    </form>
  );
}

export function LeadsPage() {
  const { t, i18n } = useTranslation("leads");
  const toast = useToast();
  const { currentOrgId, orgs, loading: orgLoading } = useOrg();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [statusFilter, setStatusFilter] = useState<Lead["status"] | "">("");
  const [view, setView] = useState<"board" | "list">("board");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [draft, setDraft] = useState<FollowupDraft | null>(null);

  useEffect(() => {
    if (!currentOrgId) return;
    const url = "/api/leads?limit=100";
    let active = true;
    apiFetch(url)
      .then(res => parseJSON<{ leads: Lead[] }>(res, url))
      .then(data => {
        if (active) { setLeads(data.leads); setError(false); setLoading(false); }
      })
      .catch(() => {
        if (active) { setError(true); setLoading(false); }
      });
    return () => { active = false; setLoading(true); setError(false); setBrief(null); };
  }, [currentOrgId]);

  useEffect(() => {
    if (!draft) return;
    const close = (e: KeyboardEvent) => { if (e.key === "Escape") setDraft(null); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [draft]);

  const act = useCallback(async (name: string, work: () => Promise<void>) => {
    setBusy(name);
    try { await work(); }
    catch (err) { toast(t(aiErrorKey(err)), "err"); }
    finally { setBusy(null); }
  }, [t, toast]);

  const replace = (lead: Lead) => setLeads(prev => prev.map(l => l.id === lead.id ? { ...l, ...lead } : l));

  function jumpTo(id: string) {
    setStatusFilter(""); setQuery(""); setHighlight(id);
    requestAnimationFrame(() => document.getElementById(`lead-${id}`)?.scrollIntoView?.({ behavior: "smooth", block: "center" }));
  }

  // Lead endpoints are org-scoped: without an organization the list request
  // is never made, so show how to get one instead of an endless "loading".
  if (!orgLoading && !currentOrgId) {
    const hasOrgs = orgs.length > 0;
    return (
      <div className="leads-page">
        <EmptyState
          title={t("noOrg.title")}
          description={hasOrgs ? t("noOrg.descriptionHasOrgs") : t("noOrg.descriptionNoOrgs")}
          action={hasOrgs ? undefined : <CreateOrgForm />}
        />
      </div>
    );
  }

  const needle = query.trim().toLocaleLowerCase();
  const visible = leads.filter(l =>
    (!statusFilter || l.status === statusFilter)
    && (!needle || `${l.name} ${l.email ?? ""} ${l.source ?? ""}`.toLocaleLowerCase().includes(needle)));
  const tierCount = (c: Column) => leads.filter(l => columnOf(l) === c).length;
  const working = busy !== null;

  const card = (lead: Lead) => (
    <LeadCard key={lead.id} lead={lead} highlighted={highlight === lead.id} busy={busy}
      onStatus={(l, status) => void act(`status-${l.id}`, async () => {
        const res = await apiFetch(`/api/leads/${l.id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
        replace(await parseJSON<Lead>(res, `/api/leads/${l.id}/status`));
      })}
      onRequalify={l => void act(`qualify-${l.id}`, async () => {
        const res = await apiFetch(`/api/leads/${l.id}/qualify`, { method: "POST" });
        replace(await parseJSON<Lead>(res, `/api/leads/${l.id}/qualify`));
      })}
      onDraft={l => void act(`draft-${l.id}`, async () => {
        const res = await apiFetch(`/api/leads/${l.id}/ai-followup`, { method: "POST", body: JSON.stringify({ language: language(i18n.language) }) });
        const data = await parseJSON<{ subject: string; body: string }>(res, `/api/leads/${l.id}/ai-followup`);
        setDraft({ leadId: l.id, name: l.name, email: l.email, subject: data.subject, body: data.body });
      })}
    />
  );

  return (
    <div className="leads-page" dir={i18n.dir()}>
      <header className="leads-hero">
        <div>
          <span className="leads-eyebrow">FLOW · LEADS <b className="leads-ai-badge">AI</b></span>
          <h1>{t("page.title")}</h1>
          <p>{t("page.subtitle")}</p>
        </div>
        <dl className="leads-stats">
          <div><dt>{t("stats.total")}</dt><dd>{leads.length}</dd></div>
          {(["hot", "warm", "cold"] as const).map(c => <div key={c} className={`is-${c}`}><dt>{t(`tier.${c}`)}</dt><dd>{tierCount(c)}</dd></div>)}
          <div><dt>{t("stats.won")}</dt><dd>{leads.filter(l => l.status === "won").length}</dd></div>
        </dl>
      </header>

      <div className="leads-toolbar">
        <AddLeadForm onAdd={lead => setLeads(prev => [lead, ...prev])} />
        <label className="leads-search">{t("search.label")}
          <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder={t("search.hint")} />
        </label>
        <div className="leads-segment" role="group" aria-label={t("view.label")}>
          {(["board", "list"] as const).map(v => <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>{t(`view.${v}`)}</button>)}
        </div>
      </div>

      <LeadFollowupCard key={currentOrgId ?? "none"} orgId={currentOrgId} />

      {!loading && !error && leads.length > 0 && (
        <BriefPanel brief={brief} busy={busy === "brief"} onJump={jumpTo} onRun={() => void act("brief", async () => {
          const res = await apiFetch("/api/leads/brief", { method: "POST", body: JSON.stringify({ language: language(i18n.language) }) });
          setBrief(await parseJSON<Brief>(res, "/api/leads/brief"));
        })} />
      )}

      <div className="leads-tabs" role="group" aria-label={t("table.status")}>
        {(["", ...STATUSES] as const).map(s => (
          <button key={s || "all"} type="button" aria-pressed={statusFilter === s} onClick={() => setStatusFilter(s)}>
            {s ? t(`status.${s}`) : t("filter.all")}
            <span>{s ? leads.filter(l => l.status === s).length : leads.length}</span>
          </button>
        ))}
      </div>

      {loading && <div className="leads-skeleton" role="status"><span className="leads-sr">{t("states.loading")}</span><div /><div /><div /></div>}
      {!loading && error && <div role="alert" className="leads-state is-error">{t("states.error")}</div>}
      {!loading && !error && leads.length === 0 && (
        <div role="status" className="leads-state">
          <p><strong>{t("states.empty")}</strong></p>
          <p className="leads-muted">{t("states.emptyHint")}</p>
        </div>
      )}
      {!loading && !error && leads.length > 0 && visible.length === 0 && (
        <div role="status" className="leads-state"><p>{t("states.noMatch")}</p></div>
      )}

      {!loading && !error && visible.length > 0 && (view === "board"
        ? <div className="leads-board">
            {COLUMNS.map(c => {
              const items = visible.filter(l => columnOf(l) === c);
              return (
                <section key={c} className={`leads-column is-${c}`} aria-label={t(`board.${c}`)}>
                  <h2>{t(`board.${c}`)}<span>{items.length}</span></h2>
                  {items.length ? items.map(card) : <p className="leads-muted">{t("board.empty")}</p>}
                </section>
              );
            })}
          </div>
        : <div className="leads-list">{visible.map(card)}</div>
      )}

      {draft && (
        <div className="leads-drawer-backdrop">
          <div className="leads-drawer" role="dialog" aria-modal="true" aria-label={t("draft.title", { name: draft.name })}>
            <header>
              <h2><b className="leads-ai-badge">AI</b>{t("draft.title", { name: draft.name })}</h2>
              <button type="button" className="leads-ghost" onClick={() => setDraft(null)}>{t("draft.close")}</button>
            </header>
            <p className="leads-muted">{t("draft.note")}</p>
            <label>{t("draft.subject")}
              <input value={draft.subject} onChange={e => setDraft({ ...draft, subject: e.target.value })} />
            </label>
            <label className="leads-grow">{t("draft.body")}
              <textarea autoFocus value={draft.body} onChange={e => setDraft({ ...draft, body: e.target.value })} />
            </label>
            <div className="leads-row">
              <GoldButton type="button" disabled={working} onClick={() => void navigator.clipboard?.writeText(`${draft.subject}\n\n${draft.body}`).then(() => toast(t("draft.copied"), "ok"))}>
                {t("draft.copy")}
              </GoldButton>
              {draft.email && (
                <a className="leads-ghost" href={`mailto:${draft.email}?subject=${encodeURIComponent(draft.subject)}&body=${encodeURIComponent(draft.body)}`}>
                  {t("draft.openEmail")}
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
