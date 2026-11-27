/**
 * Business Lab — Business Plan & Validation Engine
 *
 * UI structure:
 *   Left:  Plan list + "New Plan" button
 *   Right: Plan detail with tabs:
 *     Overview → live progress timeline
 *     Sections → each section's content with status badges
 *     Facts    → Fact Registry with evidence badges
 *     Competitors → table
 *     Score    → readiness score breakdown
 *     Export   → download buttons
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { businessService, type Plan, type PlanDetail, type Section } from "./services/businessService";
import "./business-lab.css";

// ── Status badge colours ──────────────────────────────────────────────────────
const STATUS_BADGE: Record<string, { bg: string; color: string }> = {
  VERIFIED:     { bg: "#d1fae5", color: "#065f46" },
  UNVERIFIED:   { bg: "#fef3c7", color: "#92400e" },
  ASSUMPTION:   { bg: "#fee2e2", color: "#991b1b" },
  MISSING:      { bg: "#f3f4f6", color: "#6b7280" },
  CONFLICTING:  { bg: "#ede9fe", color: "#5b21b6" },
  COMPLETED:    { bg: "#d1fae5", color: "#065f46" },
  RUNNING:      { bg: "#dbeafe", color: "#1e40af" },
  PENDING:      { bg: "#f3f4f6", color: "#6b7280" },
  FAILED:       { bg: "#fee2e2", color: "#991b1b" },
  NEEDS_REVIEW: { bg: "#fef3c7", color: "#92400e" },
};

function Badge({ label }: { label: string }) {
  const { t } = useTranslation("businessLab");
  const s = STATUS_BADGE[label] ?? { bg: "#f3f4f6", color: "#374151" };
  return (
    <span style={{
      display: "inline-block", fontSize: 10, fontWeight: 700,
      padding: "2px 7px", borderRadius: 20,
      background: s.bg, color: s.color, letterSpacing: "0.04em",
    }}>
      {t(`status.${label}`, { defaultValue: label })}
    </span>
  );
}

// ── Score ring ────────────────────────────────────────────────────────────────
function ScoreRing({ score }: { score: number }) {
  const r = 36, circ = 2 * Math.PI * r;
  const dash = (score / 100) * circ;
  const color = score >= 70 ? "#10b981" : score >= 40 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ position: "relative", width: 90, height: 90 }}>
      <svg width="90" height="90">
        <circle cx="45" cy="45" r={r} fill="none" stroke="var(--b2,#e5e7eb)" strokeWidth="7" />
        <circle cx="45" cy="45" r={r} fill="none" stroke={color} strokeWidth="7"
          strokeDasharray={`${dash} ${circ}`} strokeDashoffset={circ * 0.25}
          strokeLinecap="round" style={{ transition: "stroke-dasharray 0.6s ease" }} />
      </svg>
      <div style={{
        position: "absolute", inset: 0, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
      }}>
        <span style={{ fontSize: 22, fontWeight: 800, color }}>{score}</span>
        <span style={{ fontSize: 9, color: "var(--t4,#9ca3af)" }}>/ 100</span>
      </div>
    </div>
  );
}

// ── Progress timeline ─────────────────────────────────────────────────────────
const STAGE_ORDER = [
  "intake", "company_description", "market_intelligence", "competitor_intelligence",
  "offer_pricing", "go_to_market", "ops_finance", "full_plan", "assumption_audit",
  "adversarial_review",
];


function Timeline({ sections }: { sections: Section[] }) {
  const { t } = useTranslation("businessLab");
  const secMap = Object.fromEntries(sections.map(s => [s.section_key, s]));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {STAGE_ORDER.map(key => {
        const sec = secMap[key];
        const status = sec?.status ?? "PENDING";
        const dotColor = status === "COMPLETED" ? "#10b981"
          : status === "RUNNING" ? "#3b82f6"
          : status === "FAILED"  ? "#ef4444"
          : "var(--b3,#d1d5db)";
        return (
          <div key={key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
            <span style={{ fontSize: 13, color: "var(--t2,#374151)", flex: 1 }}>
              {t(`stages.${key}`)}
            </span>
            <Badge label={status} />
            {sec?.elapsed_ms ? (
              <span style={{ fontSize: 10, color: "var(--t5,#9ca3af)" }}>
                {(sec.elapsed_ms / 1000).toFixed(1)}s
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ── New Plan form ─────────────────────────────────────────────────────────────
function NewPlanForm({ onCreated }: { onCreated: (plan: Plan) => void }) {
  const [idea, setIdea]       = useState("");
  const [industry, setIndustry] = useState("");
  const [stage, setStage]     = useState("IDEA");
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState<string | null>(null);
  const { t } = useTranslation("businessLab");

  const submit = async () => {
    if (idea.trim().length < 10) { setErr(t("form.tooShort")); return; }
    setLoading(true); setErr(null);
    try {
      const plan = await businessService.createPlan({
        idea_raw: idea.trim(),
        industry: industry || undefined,
        stage,
      });
      onCreated(plan);
      setIdea(""); setIndustry(""); setStage("IDEA");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : t("form.genericError"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: "var(--bg-card,#fff)", border: "1px solid var(--b1,#e5e7eb)",
      borderRadius: 12, padding: 20, display: "flex", flexDirection: "column", gap: 12,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: "var(--t1,#111)" }}>{t("form.title")}</div>

      <textarea
        aria-label={t("form.ideaLabel")}
        maxLength={4000}
        value={idea} onChange={e => setIdea(e.target.value)}
        placeholder={t("form.ideaPlaceholder")}
        rows={4} style={{
          width: "100%", resize: "vertical", padding: "10px 12px",
          border: "1px solid var(--b1,#e5e7eb)", borderRadius: 8,
          fontSize: 13, color: "var(--t1,#111)", background: "var(--bg-input,#f9fafb)",
          fontFamily: "inherit", boxSizing: "border-box",
        }}
      />

      <div style={{ display: "flex", gap: 10 }}>
        <input value={industry} onChange={e => setIndustry(e.target.value)}
          placeholder={t("form.industryPlaceholder")} style={{
            flex: 1, padding: "8px 12px", border: "1px solid var(--b1,#e5e7eb)",
            borderRadius: 8, fontSize: 13, background: "var(--bg-input,#f9fafb)", color: "var(--t1,#111)",
          }} />

        <select value={stage} onChange={e => setStage(e.target.value)} style={{
          padding: "8px 12px", border: "1px solid var(--b1,#e5e7eb)", borderRadius: 8,
          fontSize: 13, background: "var(--bg-input,#f9fafb)", color: "var(--t1,#111)",
        }}>
          <option value="IDEA">{t("form.stageIdea")}</option>
          <option value="MVP">{t("form.stageMvp")}</option>
          <option value="GROWTH">{t("form.stageGrowth")}</option>
          <option value="SCALE">{t("form.stageScale")}</option>
        </select>
      </div>

      {err && <div style={{ fontSize: 12, color: "#dc2626" }}>{err}</div>}

      <button onClick={submit} disabled={loading} style={{
        padding: "9px 18px", borderRadius: 8, border: "none",
        background: loading ? "var(--b2,#e5e7eb)" : "var(--accent,#8b5cf6)",
        color: "#fff", fontWeight: 700, fontSize: 13, cursor: loading ? "default" : "pointer",
      }}>
        {loading ? t("form.submitting") : t("form.submit")}
      </button>
    </div>
  );
}

// ── Section viewer ────────────────────────────────────────────────────────────
function SectionCard({ section }: { section: Section }) {
  const { t } = useTranslation("businessLab");
  const [open, setOpen] = useState(section.status === "COMPLETED");
  return (
    <div style={{
      border: "1px solid var(--b1,#e5e7eb)", borderRadius: 10,
      overflow: "hidden", marginBottom: 8,
    }}>
      <div
        onClick={() => setOpen(o => !o)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen(o => !o); }}
        role="button"
        tabIndex={0}
        style={{
          display: "flex", alignItems: "center", gap: 8, padding: "10px 14px",
          cursor: "pointer", background: "var(--bg-card,#fff)",
        }}
      >
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: "var(--t1,#111)" }}>
          {section.title || t(`stages.${section.section_key}`, { defaultValue: section.section_key })}
        </span>
        <Badge label={section.status} />
        {section.tokens_used > 0 && (
          <span style={{ fontSize: 10, color: "var(--t5,#9ca3af)" }}>
            {t("tokens", { n: section.tokens_used.toLocaleString() })}
          </span>
        )}
        <span style={{ fontSize: 11, color: "var(--t4,#9ca3af)" }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && section.content && (
        <div style={{
          padding: "12px 16px", borderTop: "1px solid var(--b1,#e5e7eb)",
          background: "var(--bg-subtle,#f9fafb)",
          fontSize: 13, lineHeight: 1.7, color: "var(--t2,#374151)",
          whiteSpace: "pre-wrap", maxHeight: 400, overflowY: "auto",
        }}>
          {section.content}
        </div>
      )}
      {open && section.error_msg && (
        <div style={{ padding: "10px 16px", background: "#fef2f2", color: "#dc2626", fontSize: 12 }}>
          ⚠ {section.error_msg}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
type Tab = "overview" | "sections" | "facts" | "competitors" | "score" | "export";

export function BusinessLabPage() {
  const { t } = useTranslation("businessLab");
  const [plans, setPlans]         = useState<Plan[]>([]);
  const [selected, setSelected]   = useState<string | null>(null);
  const [detail, setDetail]       = useState<PlanDetail | null>(null);
  const [tab, setTab]             = useState<Tab>("overview");
  const [showNew, setShowNew]     = useState(false);
  const [loading, setLoading]     = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const actionPending = useRef(false);
  const selectionVersion = useRef(0);
  const stopStream                = useRef<(() => void) | null>(null);

  // Load plan list
  const loadPlans = useCallback(async () => {
    setListError(null);
    try { setPlans(await businessService.listPlans()); }
    catch (error) { setListError(error instanceof Error ? error.message : t("errors.loadPlans")); }
  }, [t]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadPlans(); }, [loadPlans]);

  // Load detail + start stream when plan selected
  const selectPlan = useCallback(async (id: string) => {
    const version = ++selectionVersion.current;
    setDetailError(null);
    setSelected(id); setTab("overview"); setDetail(null);
    stopStream.current?.(); stopStream.current = null;
    setLoading(true);
    try {
      const d = await businessService.getPlan(id);
      if (version !== selectionVersion.current) return;
      setDetail(d);

      // Stream live updates for in-progress plans
      if (d.plan.status === "GENERATING" || d.plan.status === "DRAFT") {
        const stop = businessService.streamStatus(id, (data) => {
          setDetail(prev => {
            if (!prev || prev.plan.id !== id || version !== selectionVersion.current) return prev;
            const evt = data as Record<string, unknown>;
            const secs = (evt.sections ?? {}) as Record<string, { status: string; tokens_used: number; error_msg: string | null }>;
            const updatedSections = prev.sections.map(s =>
              secs[s.section_key]
                ? { ...s, status: secs[s.section_key].status, tokens_used: secs[s.section_key].tokens_used ?? s.tokens_used }
                : s,
            );
            const planPatch = {
              status:          (evt.plan_status as string) ?? prev.plan.status,
              readiness_score: (evt.readiness_score as number | null) ?? prev.plan.readiness_score,
            };
            if (evt.done) { void loadPlans(); }
            return { ...prev, plan: { ...prev.plan, ...planPatch }, sections: updatedSections };
          });
        });
        stopStream.current = stop;
      }
    } catch (error) {
      if (version === selectionVersion.current) setDetailError(error instanceof Error ? error.message : t("errors.loadPlan"));
    } finally {
      if (version === selectionVersion.current) setLoading(false);
    }
  }, [loadPlans, t]);

  // Cleanup on unmount
  useEffect(() => () => { ++selectionVersion.current; stopStream.current?.(); }, []);

  const handleRetry = async (keys: string[]) => {
    if (!selected) return;
    await runAction(async () => { await businessService.retrySections(selected, keys); await selectPlan(selected); });
  };

  const handleCancel = async () => {
    if (!selected) return;
    await runAction(async () => { await businessService.cancelPlan(selected); await selectPlan(selected); });
  };

  const handleExport = async (variant: string) => {
    if (!selected) return;
    await runAction(() => businessService.exportPlan(selected, "markdown", variant));
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!window.confirm(t("confirmDelete"))) return;
    await runAction(async () => {
    await businessService.deletePlan(selected);
    ++selectionVersion.current;
    stopStream.current?.(); stopStream.current = null;
    setSelected(null); setDetail(null);
    await loadPlans();
    });
  };

  const runAction = async (action: () => Promise<unknown>) => {
    if (actionPending.current) return;
    actionPending.current = true; setActionError(null);
    try { await action(); }
    catch (error) { setActionError(error instanceof Error ? error.message : t("errors.action")); }
    finally { actionPending.current = false; }
  };

  return (
    <div className="business-lab" style={{
      display: "flex", height: "100%", overflow: "hidden",
      background: "var(--bg,#f9fafb)", fontFamily: "inherit",
    }}>
      {/* ── Sidebar: plan list ── */}
      <div className="business-lab-sidebar" style={{
        width: 260, flexShrink: 0, borderRight: "1px solid var(--b1,#e5e7eb)",
        display: "flex", flexDirection: "column", background: "var(--bg-card,#fff)",
        overflowY: "auto",
      }}>
        <div style={{ padding: "16px 14px 10px", borderBottom: "1px solid var(--b1,#e5e7eb)" }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: "var(--t1,#111)", marginBottom: 10 }}>
            {t("title")}
          </div>
          <button onClick={() => setShowNew(v => !v)} style={{
            width: "100%", padding: "8px", borderRadius: 8, border: "none",
            background: "var(--accent,#8b5cf6)", color: "#fff",
            fontWeight: 700, fontSize: 12, cursor: "pointer",
          }}>
            {t("newPlanButton")}
          </button>
        </div>

        {showNew && (
          <div style={{ padding: 12, borderBottom: "1px solid var(--b1,#e5e7eb)" }}>
            <NewPlanForm onCreated={async (plan) => {
              setShowNew(false);
              await loadPlans();
              await selectPlan(plan.id);
            }} />
          </div>
        )}

        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
          {listError && <div role="alert" style={{ padding: 16 }}>
            <p>{listError}</p>
            <button onClick={() => void loadPlans()}>{t("reloadPlans")}</button>
          </div>}
          {!listError && plans.length === 0 && (
            <div style={{ padding: 16, fontSize: 12, color: "var(--t4,#9ca3af)", textAlign: "center" }}>
              {t("emptyPlans")}<br />{t("emptyPlansHint")}
            </div>
          )}
          {plans.map(p => (
            <div key={p.id}
              onClick={() => void selectPlan(p.id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") void selectPlan(p.id); }}
              role="button"
              tabIndex={0}
              style={{
              padding: "10px 14px", cursor: "pointer",
              background: selected === p.id ? "var(--accent-subtle,#ede9fe)" : "transparent",
              borderRight: selected === p.id ? "3px solid var(--accent,#8b5cf6)" : "3px solid transparent",
              marginRight: -1,
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1,#111)", marginBottom: 3 }}>
                {p.title || p.idea_raw.slice(0, 40) + "…"}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Badge label={p.status} />
                {p.readiness_score !== null && (
                  <span style={{ fontSize: 10, color: "var(--accent,#8b5cf6)", fontWeight: 700 }}>
                    {p.readiness_score}/100
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Main content ── */}
      <div className="business-lab-content" style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto" }}>
        {actionError && <div role="alert" style={{ padding: 20 }}>{actionError}</div>}
        {detailError && <div role="alert" style={{ padding: 20 }}><p>{detailError}</p><button onClick={() => selected && void selectPlan(selected)}>{t("reloadPlan")}</button></div>}
        {!selected && (
          <div style={{
            flex: 1, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 12, color: "var(--t4,#9ca3af)",
          }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{t("pickPlan")}</div>
          </div>
        )}

        {selected && (
          <>
            {/* Tab bar */}
            <div style={{
              display: "flex", gap: 2, padding: "12px 16px 0",
              borderBottom: "1px solid var(--b1,#e5e7eb)",
              background: "var(--bg-card,#fff)",
            }}>
              {([
                ["overview",     t("tabs.overview")],
                ["sections",     t("tabs.sections")],
                ["facts",        t("tabs.facts")],
                ["competitors",  t("tabs.competitors")],
                ["score",        t("tabs.score")],
                ["export",       t("tabs.export")],
              ] as [Tab, string][]).map(([key, label]) => (
                <button key={key} onClick={() => setTab(key)} style={{
                  padding: "7px 14px", border: "none", borderRadius: "8px 8px 0 0",
                  background: tab === key ? "var(--bg,#f9fafb)" : "transparent",
                  color: tab === key ? "var(--accent,#8b5cf6)" : "var(--t3,#6b7280)",
                  fontWeight: tab === key ? 700 : 500, fontSize: 12, cursor: "pointer",
                  borderBottom: tab === key ? "2px solid var(--accent,#8b5cf6)" : "2px solid transparent",
                }}>
                  {label}
                </button>
              ))}

              <div style={{ marginLeft: "auto", display: "flex", gap: 6, paddingBottom: 4 }}>
                {detail?.plan.status === "GENERATING" && (
                  <button onClick={handleCancel} style={{
                    padding: "4px 10px", borderRadius: 6, border: "1px solid var(--b2,#e5e7eb)",
                    background: "transparent", color: "var(--t3,#6b7280)", fontSize: 11, cursor: "pointer",
                  }}>{t("cancel")}</button>
                )}
                <button onClick={handleDelete} style={{
                  padding: "4px 10px", borderRadius: 6, border: "1px solid #fee2e2",
                  background: "transparent", color: "#dc2626", fontSize: 11, cursor: "pointer",
                }}>{t("delete")}</button>
              </div>
            </div>

            <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
              {loading && <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>{t("loading")}</div>}

              {!loading && detail && (
                <>
                  {/* ── Overview ── */}
                  {tab === "overview" && (
                    <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                      <div style={{ flex: 1, minWidth: 260 }}>
                        <div style={{ marginBottom: 14 }}>
                          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--t1,#111)", marginBottom: 4 }}>
                            {detail.plan.title || t("untitled")}
                          </div>
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <Badge label={detail.plan.status} />
                            {detail.plan.industry && (
                              <span style={{ fontSize: 11, color: "var(--t4,#9ca3af)" }}>
                                📂 {detail.plan.industry}
                              </span>
                            )}
                            <span style={{ fontSize: 11, color: "var(--t4,#9ca3af)" }}>
                              🚀 {detail.plan.stage}
                            </span>
                          </div>
                        </div>
                        <Timeline sections={detail.sections} />
                      </div>

                      {detail.score && (
                        <div style={{
                          display: "flex", flexDirection: "column", alignItems: "center",
                          gap: 8, minWidth: 120,
                        }}>
                          <ScoreRing score={detail.score.overall_score} />
                          <div style={{ fontSize: 11, color: "var(--t4,#9ca3af)" }}>{t("readiness")}</div>
                          <div style={{ fontSize: 10, color: "var(--t5,#9ca3af)" }}>
                            {t("counts", { evidence: detail.score.evidence_count, assumptions: detail.score.assumption_count, missing: detail.score.missing_count })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* ── Sections ── */}
                  {tab === "sections" && (
                    <div>
                      {detail.sections.length === 0 && (
                        <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>
                          {t("noSections")}
                        </div>
                      )}
                      {detail.sections
                        .filter(s => STAGE_ORDER.includes(s.section_key))
                        .sort((a, b) => STAGE_ORDER.indexOf(a.section_key) - STAGE_ORDER.indexOf(b.section_key))
                        .map(s => <SectionCard key={s.id} section={s} />)
                      }
                      {detail.sections.some(s => s.status === "FAILED") && (
                        <button onClick={() => void handleRetry(
                          detail.sections.filter(s => s.status === "FAILED").map(s => s.section_key)
                        )} style={{
                          marginTop: 12, padding: "8px 16px", borderRadius: 8, border: "none",
                          background: "#fef3c7", color: "#92400e", fontWeight: 700,
                          fontSize: 12, cursor: "pointer",
                        }}>
                          {t("retryFailed")}
                        </button>
                      )}
                    </div>
                  )}

                  {/* ── Facts ── */}
                  {tab === "facts" && (
                    <div>
                      <div style={{ fontSize: 12, color: "var(--t4,#9ca3af)", marginBottom: 10 }}>
                        {t("factsTitle", { count: detail.facts.length })}
                      </div>
                      {detail.facts.length === 0 && (
                        <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>
                          {t("noFacts")}
                        </div>
                      )}
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {detail.facts.map(f => (
                          <div key={f.id} style={{
                            display: "flex", alignItems: "flex-start", gap: 8,
                            padding: "8px 12px", borderRadius: 8,
                            background: "var(--bg-card,#fff)", border: "1px solid var(--b1,#e5e7eb)",
                          }}>
                            <Badge label={f.status} />
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1,#111)" }}>
                                {f.fact_key}
                              </div>
                              <div style={{ fontSize: 11, color: "var(--t3,#6b7280)", marginTop: 2 }}>
                                {String(f.value).slice(0, 120)}
                              </div>
                            </div>
                            <div style={{ textAlign: "right", flexShrink: 0 }}>
                              <div style={{ fontSize: 10, color: "var(--t5,#9ca3af)" }}>{f.source_type}</div>
                              <div style={{ fontSize: 10, color: "var(--t5,#9ca3af)" }}>
                                {t("confidence", { pct: Math.round(f.confidence * 100) })}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* ── Competitors ── */}
                  {tab === "competitors" && (
                    <div>
                      {detail.competitors.length === 0 && (
                        <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>
                          {t("noCompetitors")}
                        </div>
                      )}
                      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {detail.competitors.map(c => (
                          <div key={c.id} style={{
                            padding: "12px 14px", borderRadius: 10,
                            background: "var(--bg-card,#fff)", border: "1px solid var(--b1,#e5e7eb)",
                          }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                              <span style={{ fontSize: 14, fontWeight: 700, color: "var(--t1,#111)" }}>{c.name}</span>
                              {c.verified && <Badge label="VERIFIED" />}
                              {c.website && (
                                <a href={c.website} target="_blank" rel="noopener noreferrer"
                                  style={{ fontSize: 10, color: "var(--accent,#8b5cf6)" }}>
                                  🔗 {c.website}
                                </a>
                              )}
                            </div>
                            {c.description && (
                              <div style={{ fontSize: 12, color: "var(--t3,#6b7280)", marginBottom: 8 }}>
                                {c.description}
                              </div>
                            )}
                            <div style={{ display: "flex", gap: 16 }}>
                              {c.strengths.length > 0 && (
                                <div>
                                  <div style={{ fontSize: 10, color: "#065f46", fontWeight: 700, marginBottom: 3 }}>{t("strengths")}</div>
                                  {c.strengths.map((s, i) => (
                                    <div key={i} style={{ fontSize: 11, color: "var(--t3,#6b7280)" }}>• {s}</div>
                                  ))}
                                </div>
                              )}
                              {c.weaknesses.length > 0 && (
                                <div>
                                  <div style={{ fontSize: 10, color: "#991b1b", fontWeight: 700, marginBottom: 3 }}>{t("weaknesses")}</div>
                                  {c.weaknesses.map((s, i) => (
                                    <div key={i} style={{ fontSize: 11, color: "var(--t3,#6b7280)" }}>• {s}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* ── Score ── */}
                  {tab === "score" && detail.score && (
                    <div style={{ maxWidth: 480 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 20 }}>
                        <ScoreRing score={detail.score.overall_score} />
                        <div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: "var(--t1,#111)" }}>
                            {t("readinessValue", { score: detail.score.overall_score })}
                          </div>
                          <div style={{ fontSize: 12, color: "var(--t4,#9ca3af)", marginTop: 4 }}>
                            {t("countsLong", { evidence: detail.score.evidence_count, assumptions: detail.score.assumption_count, missing: detail.score.missing_count })}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {Object.entries(detail.score.breakdown).map(([dim, val]) => (
                          <div key={dim}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
                              <span style={{ color: "var(--t2,#374151)" }}>{dim}</span>
                              <span style={{ fontWeight: 700, color: "var(--t1,#111)" }}>{val}</span>
                            </div>
                            <div style={{ height: 6, background: "var(--b2,#e5e7eb)", borderRadius: 3 }}>
                              <div style={{
                                height: 6, borderRadius: 3,
                                background: "var(--accent,#8b5cf6)",
                                width: `${Math.min(100, (val / 20) * 100)}%`,
                                transition: "width 0.4s ease",
                              }} />
                            </div>
                          </div>
                        ))}
                      </div>
                      <button onClick={() => void runAction(async () => {
                        const s = await businessService.recomputeScore(selected);
                        setDetail(prev => prev?.plan.id === selected ? { ...prev, score: s } : prev);
                      })} style={{
                        marginTop: 16, padding: "8px 14px", borderRadius: 8,
                        border: "1px solid var(--b1,#e5e7eb)", background: "transparent",
                        color: "var(--t2,#374151)", fontSize: 12, cursor: "pointer",
                      }}>
                        {t("recompute")}
                      </button>
                    </div>
                  )}
                  {tab === "score" && !detail.score && (
                    <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>
                      {t("scoreNotReady")}
                    </div>
                  )}

                  {/* ── Export ── */}
                  {tab === "export" && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 380 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1,#111)" }}>
                        {t("export.title")}
                      </div>
                      {[
                        { variant: "standard",  label: t("export.standard"),  desc: t("export.standardDesc") },
                        { variant: "investor",  label: t("export.investor"),  desc: t("export.investorDesc") },
                        { variant: "lender",    label: t("export.lender"),    desc: t("export.lenderDesc") },
                      ].map(({ variant, label, desc }) => (
                        <div key={variant} style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "12px 14px", borderRadius: 10,
                          border: "1px solid var(--b1,#e5e7eb)", background: "var(--bg-card,#fff)",
                        }}>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1,#111)" }}>{label}</div>
                            <div style={{ fontSize: 11, color: "var(--t4,#9ca3af)" }}>{desc}</div>
                          </div>
                          <button onClick={() => void handleExport(variant)} style={{
                            padding: "6px 14px", borderRadius: 7, border: "none",
                            background: "var(--accent,#8b5cf6)", color: "#fff",
                            fontWeight: 700, fontSize: 12, cursor: "pointer",
                          }}>
                            {t("export.download")}
                          </button>
                        </div>
                      ))}
                      <div style={{ fontSize: 11, color: "var(--t5,#9ca3af)" }}>
                        {t("export.soon")}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
