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
import { businessService, type Plan, type PlanDetail, type Section } from "./services/businessService";

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
  const s = STATUS_BADGE[label] ?? { bg: "#f3f4f6", color: "#374151" };
  return (
    <span style={{
      display: "inline-block", fontSize: 10, fontWeight: 700,
      padding: "2px 7px", borderRadius: 20,
      background: s.bg, color: s.color, letterSpacing: "0.04em",
    }}>
      {label}
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
const STAGE_LABELS: Record<string, string> = {
  intake:                  "استيعاب الفكرة",
  company_description:     "وصف الشركة",
  market_intelligence:     "تحليل السوق",
  competitor_intelligence: "تحليل المنافسين",
  offer_pricing:           "العرض والتسعير",
  go_to_market:            "استراتيجية الإطلاق",
  ops_finance:             "العمليات والتمويل",
  full_plan:               "تجميع الخطة",
  assumption_audit:        "تدقيق الافتراضات",
  adversarial_review:      "مراجعة المخاطر",
};

const STAGE_ORDER = Object.keys(STAGE_LABELS);

function Timeline({ sections }: { sections: Section[] }) {
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
              {STAGE_LABELS[key]}
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

  const submit = async () => {
    if (idea.trim().length < 10) { setErr("صف فكرتك بجملتين على الأقل"); return; }
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
      setErr(e instanceof Error ? e.message : "حدث خطأ");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: "var(--bg-card,#fff)", border: "1px solid var(--b1,#e5e7eb)",
      borderRadius: 12, padding: 20, display: "flex", flexDirection: "column", gap: 12,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: "var(--t1,#111)" }}>خطة عمل جديدة ✨</div>

      <textarea
        value={idea} onChange={e => setIdea(e.target.value)}
        placeholder="صف فكرتك بحرية… ماذا تريد أن تبني؟ من هم عملاؤك؟ ما المشكلة التي تحلها؟"
        rows={4} style={{
          width: "100%", resize: "vertical", padding: "10px 12px",
          border: "1px solid var(--b1,#e5e7eb)", borderRadius: 8,
          fontSize: 13, color: "var(--t1,#111)", background: "var(--bg-input,#f9fafb)",
          fontFamily: "inherit", boxSizing: "border-box",
        }}
      />

      <div style={{ display: "flex", gap: 10 }}>
        <input value={industry} onChange={e => setIndustry(e.target.value)}
          placeholder="القطاع (اختياري)" style={{
            flex: 1, padding: "8px 12px", border: "1px solid var(--b1,#e5e7eb)",
            borderRadius: 8, fontSize: 13, background: "var(--bg-input,#f9fafb)", color: "var(--t1,#111)",
          }} />

        <select value={stage} onChange={e => setStage(e.target.value)} style={{
          padding: "8px 12px", border: "1px solid var(--b1,#e5e7eb)", borderRadius: 8,
          fontSize: 13, background: "var(--bg-input,#f9fafb)", color: "var(--t1,#111)",
        }}>
          <option value="IDEA">فكرة</option>
          <option value="MVP">نموذج أولي</option>
          <option value="GROWTH">نمو</option>
          <option value="SCALE">توسع</option>
        </select>
      </div>

      {err && <div style={{ fontSize: 12, color: "#dc2626" }}>{err}</div>}

      <button onClick={submit} disabled={loading} style={{
        padding: "9px 18px", borderRadius: 8, border: "none",
        background: loading ? "var(--b2,#e5e7eb)" : "var(--accent,#8b5cf6)",
        color: "#fff", fontWeight: 700, fontSize: 13, cursor: loading ? "default" : "pointer",
      }}>
        {loading ? "جارٍ الإنشاء…" : "ابدأ التحليل 🚀"}
      </button>
    </div>
  );
}

// ── Section viewer ────────────────────────────────────────────────────────────
function SectionCard({ section }: { section: Section }) {
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
          {section.title || STAGE_LABELS[section.section_key] || section.section_key}
        </span>
        <Badge label={section.status} />
        {section.tokens_used > 0 && (
          <span style={{ fontSize: 10, color: "var(--t5,#9ca3af)" }}>
            {section.tokens_used.toLocaleString()} tokens
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
  const [plans, setPlans]         = useState<Plan[]>([]);
  const [selected, setSelected]   = useState<string | null>(null);
  const [detail, setDetail]       = useState<PlanDetail | null>(null);
  const [tab, setTab]             = useState<Tab>("overview");
  const [showNew, setShowNew]     = useState(false);
  const [loading, setLoading]     = useState(false);
  const stopStream                = useRef<(() => void) | null>(null);

  // Load plan list
  const loadPlans = useCallback(async () => {
    try { setPlans(await businessService.listPlans()); } catch { /* ignore */ }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadPlans(); }, [loadPlans]);

  // Load detail + start stream when plan selected
  const selectPlan = useCallback(async (id: string) => {
    setSelected(id); setTab("overview"); setDetail(null);
    stopStream.current?.(); stopStream.current = null;
    setLoading(true);
    try {
      const d = await businessService.getPlan(id);
      setDetail(d);

      // Stream live updates for in-progress plans
      if (d.plan.status === "GENERATING") {
        const stop = businessService.streamStatus(id, (data) => {
          setDetail(prev => {
            if (!prev) return prev;
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
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [loadPlans]);

  // Cleanup on unmount
  useEffect(() => () => stopStream.current?.(), []);

  const handleRetry = async (keys: string[]) => {
    if (!selected) return;
    await businessService.retrySections(selected, keys);
    await selectPlan(selected);
  };

  const handleCancel = async () => {
    if (!selected) return;
    await businessService.cancelPlan(selected);
    await selectPlan(selected);
  };

  const handleExport = async (variant: string) => {
    if (!selected) return;
    await businessService.exportPlan(selected, "markdown", variant);
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!window.confirm("هل تريد حذف هذه الخطة نهائياً؟")) return;
    await businessService.deletePlan(selected);
    setSelected(null); setDetail(null);
    await loadPlans();
  };

  return (
    <div style={{
      display: "flex", height: "100%", overflow: "hidden",
      background: "var(--bg,#f9fafb)", fontFamily: "inherit",
    }}>
      {/* ── Sidebar: plan list ── */}
      <div style={{
        width: 260, flexShrink: 0, borderRight: "1px solid var(--b1,#e5e7eb)",
        display: "flex", flexDirection: "column", background: "var(--bg-card,#fff)",
        overflowY: "auto",
      }}>
        <div style={{ padding: "16px 14px 10px", borderBottom: "1px solid var(--b1,#e5e7eb)" }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: "var(--t1,#111)", marginBottom: 10 }}>
            🧪 مختبر الأعمال
          </div>
          <button onClick={() => setShowNew(v => !v)} style={{
            width: "100%", padding: "8px", borderRadius: 8, border: "none",
            background: "var(--accent,#8b5cf6)", color: "#fff",
            fontWeight: 700, fontSize: 12, cursor: "pointer",
          }}>
            + خطة جديدة
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
          {plans.length === 0 && (
            <div style={{ padding: 16, fontSize: 12, color: "var(--t4,#9ca3af)", textAlign: "center" }}>
              لا توجد خطط بعد.<br />ابدأ بإضافة فكرتك ✨
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
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto" }}>
        {!selected && (
          <div style={{
            flex: 1, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 12, color: "var(--t4,#9ca3af)",
          }}>
            <div style={{ fontSize: 48 }}>🧪</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>اختر خطة أو أنشئ واحدة جديدة</div>
            <div style={{ fontSize: 12 }}>يحلل الذكاء الاصطناعي فكرتك ويبني خطة عمل متكاملة</div>
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
                ["overview",     "📊 نظرة عامة"],
                ["sections",     "📄 الأقسام"],
                ["facts",        "🔍 الحقائق"],
                ["competitors",  "🏆 المنافسون"],
                ["score",        "⭐ الدرجة"],
                ["export",       "📥 تصدير"],
              ] as [Tab, string][]).map(([t, label]) => (
                <button key={t} onClick={() => setTab(t)} style={{
                  padding: "7px 14px", border: "none", borderRadius: "8px 8px 0 0",
                  background: tab === t ? "var(--bg,#f9fafb)" : "transparent",
                  color: tab === t ? "var(--accent,#8b5cf6)" : "var(--t3,#6b7280)",
                  fontWeight: tab === t ? 700 : 500, fontSize: 12, cursor: "pointer",
                  borderBottom: tab === t ? "2px solid var(--accent,#8b5cf6)" : "2px solid transparent",
                }}>
                  {label}
                </button>
              ))}

              <div style={{ marginLeft: "auto", display: "flex", gap: 6, paddingBottom: 4 }}>
                {detail?.plan.status === "GENERATING" && (
                  <button onClick={handleCancel} style={{
                    padding: "4px 10px", borderRadius: 6, border: "1px solid var(--b2,#e5e7eb)",
                    background: "transparent", color: "var(--t3,#6b7280)", fontSize: 11, cursor: "pointer",
                  }}>⏸ إيقاف</button>
                )}
                <button onClick={handleDelete} style={{
                  padding: "4px 10px", borderRadius: 6, border: "1px solid #fee2e2",
                  background: "transparent", color: "#dc2626", fontSize: 11, cursor: "pointer",
                }}>🗑 حذف</button>
              </div>
            </div>

            <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
              {loading && <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>جارٍ التحميل…</div>}

              {!loading && detail && (
                <>
                  {/* ── Overview ── */}
                  {tab === "overview" && (
                    <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                      <div style={{ flex: 1, minWidth: 260 }}>
                        <div style={{ marginBottom: 14 }}>
                          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--t1,#111)", marginBottom: 4 }}>
                            {detail.plan.title || "خطة بدون عنوان"}
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
                          <div style={{ fontSize: 11, color: "var(--t4,#9ca3af)" }}>درجة الجاهزية</div>
                          <div style={{ fontSize: 10, color: "var(--t5,#9ca3af)" }}>
                            {detail.score.evidence_count} دليل ·{" "}
                            {detail.score.assumption_count} افتراض ·{" "}
                            {detail.score.missing_count} مفقود
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
                          لا توجد أقسام بعد — الخطة قيد الإنشاء.
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
                          🔄 إعادة الأقسام الفاشلة
                        </button>
                      )}
                    </div>
                  )}

                  {/* ── Facts ── */}
                  {tab === "facts" && (
                    <div>
                      <div style={{ fontSize: 12, color: "var(--t4,#9ca3af)", marginBottom: 10 }}>
                        سجل الحقائق — {detail.facts.length} إدخال
                      </div>
                      {detail.facts.length === 0 && (
                        <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>
                          لا توجد حقائق مسجلة بعد.
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
                                {Math.round(f.confidence * 100)}% ثقة
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
                          لا توجد بيانات منافسين بعد.
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
                                  <div style={{ fontSize: 10, color: "#065f46", fontWeight: 700, marginBottom: 3 }}>✅ نقاط القوة</div>
                                  {c.strengths.map((s, i) => (
                                    <div key={i} style={{ fontSize: 11, color: "var(--t3,#6b7280)" }}>• {s}</div>
                                  ))}
                                </div>
                              )}
                              {c.weaknesses.length > 0 && (
                                <div>
                                  <div style={{ fontSize: 10, color: "#991b1b", fontWeight: 700, marginBottom: 3 }}>⚠ نقاط الضعف</div>
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
                            درجة الجاهزية: {detail.score.overall_score}/100
                          </div>
                          <div style={{ fontSize: 12, color: "var(--t4,#9ca3af)", marginTop: 4 }}>
                            {detail.score.evidence_count} دليل موثق ·{" "}
                            {detail.score.assumption_count} افتراض ·{" "}
                            {detail.score.missing_count} معلومة مفقودة
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
                      <button onClick={() => void businessService.recomputeScore(selected).then(s => {
                        setDetail(prev => prev ? { ...prev, score: s } : prev);
                      })} style={{
                        marginTop: 16, padding: "8px 14px", borderRadius: 8,
                        border: "1px solid var(--b1,#e5e7eb)", background: "transparent",
                        color: "var(--t2,#374151)", fontSize: 12, cursor: "pointer",
                      }}>
                        🔄 إعادة الحساب
                      </button>
                    </div>
                  )}
                  {tab === "score" && !detail.score && (
                    <div style={{ color: "var(--t4,#9ca3af)", fontSize: 13 }}>
                      لم يُحسب التقييم بعد — انتظر اكتمال الخطة.
                    </div>
                  )}

                  {/* ── Export ── */}
                  {tab === "export" && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 380 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1,#111)" }}>
                        تصدير الخطة
                      </div>
                      {[
                        { variant: "standard",  label: "📄 نسخة قياسية",      desc: "الخطة الكاملة بالتنسيق العربي" },
                        { variant: "investor",  label: "💼 نسخة المستثمرين",  desc: "مع ملحق الحقائق والأدلة" },
                        { variant: "lender",    label: "🏦 نسخة الممولين",    desc: "مع التوقعات المالية والضمانات" },
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
                            تحميل
                          </button>
                        </div>
                      ))}
                      <div style={{ fontSize: 11, color: "var(--t5,#9ca3af)" }}>
                        PDF و DOCX — قريباً 🚧
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
