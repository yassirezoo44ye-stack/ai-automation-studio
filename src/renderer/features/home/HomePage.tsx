/**
 * FLOW Home — minimal build-first entry point.
 *
 * Progressive Disclosure: show only what matters at first glance.
 *   1. Build prompt hero  (the single primary CTA)
 *   2. Quick-idea chips   (6 starter prompts)
 *   3. Recent projects    (simple rows, max 5)
 *
 * All existing routes / navigation handlers are preserved.
 * Advanced sections (KPIs, agents, automations, activity) live in the
 * sidebar pages — not on the home screen.
 */
import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useLangContext } from "../../contexts/lang";
import { apiFetch, parseJSON } from "../../utils/api";
import { relTime } from "../../utils/time";
import { useAsyncData } from "../../shared/hooks/useAsyncData";
import type { Project } from "../../types";

// ── Rotating placeholder prompts ──────────────────────────────────────────

const EXAMPLE_PROMPTS = [
  "ابنِ نظام CRM لفريق المبيعات مع جهات الاتصال والصفقات",
  "أنشئ نظام إدارة المخزون مع تنبيهات المخزون المنخفض",
  "ابنِ بوابة إعداد الموظفين مع قوائم المهام",
  "أنشئ نظام تذاكر دعم العملاء مع الفرز الذكي",
  "ابنِ تطبيق تتبع المشاريع مع تسجيل الوقت",
];

// ── Quick-idea chips (AR labels → full prompt) ────────────────────────────

const QUICK_IDEAS: { label: string; prompt: string }[] = [
  { label: "نظام CRM",              prompt: "ابنِ نظام CRM لفريق المبيعات مع جهات الاتصال والصفقات والمتابعات" },
  { label: "إدارة المخزون",         prompt: "أنشئ نظام إدارة مخزون مع تتبع المنتجات وتنبيهات المخزون المنخفض" },
  { label: "بوابة الموارد البشرية", prompt: "ابنِ بوابة موارد بشرية لـ 50 موظفاً مع تأهيل الموظفين وإدارة الإجازات" },
  { label: "دعم العملاء",           prompt: "أنشئ نظام تذاكر دعم العملاء مع الردود التلقائية وقواعد التصعيد" },
  { label: "إدارة المشاريع",        prompt: "ابنِ أداة إدارة مشاريع مع لوحات المهام وتتبع الوقت والتعاون الجماعي" },
  { label: "نظام الفواتير",         prompt: "أنشئ نظام فوترة وإدارة العملاء مع تتبع المدفوعات والتقارير" },
];

const STATUS_COLOR: Record<string, string> = {
  active:   "var(--green)",
  building: "var(--blue)",
  error:    "var(--red)",
  draft:    "var(--t4)",
};

// ══════════════════════════════════════════════════════════════════════════
// HomePage
// ══════════════════════════════════════════════════════════════════════════
export function HomePage() {
  const { t } = useTranslation("home");
  const { setPage } = useAppContext();
  const { lang } = useLangContext();

  const [prompt, setPrompt]     = useState("");
  const [promptIdx, setPromptIdx] = useState(0);
  const promptRef = useRef<HTMLTextAreaElement>(null);

  // Cycle placeholder text every 4 s
  useEffect(() => {
    const id = setInterval(() => setPromptIdx(i => (i + 1) % EXAMPLE_PROMPTS.length), 4000);
    return () => clearInterval(id);
  }, []);

  // ── Data ────────────────────────────────────────────────────────────────
  const projectsQuery = useAsyncData<Project[]>(
    () => apiFetch("/api/projects").then(r => parseJSON<Project[]>(r, "/api/projects")),
    [],
  );
  const projects = projectsQuery.data ?? [];
  const recentProjects = [...projects]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  // ── Handlers ────────────────────────────────────────────────────────────
  function handleBuildApp() {
    if (prompt.trim().length > 3) sessionStorage.setItem("flow_builder_prompt", prompt.trim());
    setPage("app-builder");
  }

  function handleChip(idea: (typeof QUICK_IDEAS)[number]) {
    setPrompt(idea.prompt);
    promptRef.current?.focus();
  }

  // Idea chips: use locale translation if available, otherwise fallback
  const i18nIdeas = t("buildSection.ideas", { returnObjects: true });
  const chips: string[] = Array.isArray(i18nIdeas) && i18nIdeas.length > 0
    ? (i18nIdeas as string[])
    : QUICK_IDEAS.map(c => c.label);

  const isRtl = lang === "ar";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* ── Top bar ──────────────────────────────────────────────────── */}
      <div style={{
        padding: "0 24px", height: 48, minHeight: 48,
        borderBottom: "1px solid var(--b1)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "var(--bg-surface)", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 800, letterSpacing: "-0.4px", color: "var(--t1)" }}>FLOW</span>
          <span style={{
            fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em",
            color: "var(--accent)", background: "var(--accent-dim)",
            padding: "2px 6px", borderRadius: 4,
          }}>AI</span>
        </div>
        <button
          onClick={handleBuildApp}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 14px", borderRadius: 8, border: "none",
            background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
            color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer",
            boxShadow: "0 2px 8px rgba(110,50,224,0.28)",
          }}
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
          </svg>
          {isRtl ? t("header.buildWithAI") || "بناء باستخدام الذكاء الاصطناعي" : t("header.buildWithAI") || "Build with AI"}
        </button>
      </div>

      {/* ── Scrollable body ──────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: "auto" }}>

        {/* ── Hero ───────────────────────────────────────────────────── */}
        <div style={{
          maxWidth: 640, margin: "0 auto",
          padding: "56px 24px 0",
          textAlign: "center",
        }}>

          {/* Eyebrow */}
          <div style={{
            fontSize: 11, fontWeight: 700, letterSpacing: "0.14em",
            color: "var(--accent)", textTransform: "uppercase", marginBottom: 16,
          }}>
            ✦ {t("buildSection.label") || (isRtl ? "مصنع البرمجيات بالذكاء الاصطناعي" : "AI Software Factory")}
          </div>

          {/* Title */}
          <h1
            dir={isRtl ? "rtl" : "ltr"}
            style={{
              fontSize: "clamp(26px, 5vw, 38px)",
              fontWeight: 800, letterSpacing: "-0.8px",
              color: "var(--t1)", margin: "0 0 28px",
              lineHeight: 1.2,
            }}
          >
            {t("buildSection.title") || (isRtl ? "ماذا تريد أن تبني؟" : "What do you want to build?")}
          </h1>

          {/* Prompt textarea */}
          <div style={{ position: "relative", marginBottom: 14 }}>
            <textarea
              ref={promptRef}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleBuildApp(); } }}
              placeholder={EXAMPLE_PROMPTS[promptIdx]}
              dir={isRtl ? "rtl" : "ltr"}
              rows={3}
              style={{
                width: "100%",
                padding: "14px 130px 14px 16px",
                fontSize: 14, lineHeight: 1.6,
                background: "var(--bg-card)", border: "1px solid var(--b1)",
                borderRadius: 12, color: "var(--t1)", resize: "none", outline: "none",
                fontFamily: "inherit", boxSizing: "border-box",
                transition: "border-color 0.15s, box-shadow 0.15s",
                textAlign: isRtl ? "right" : "left",
              }}
              onFocus={e => {
                e.target.style.borderColor = "var(--accent)";
                e.target.style.boxShadow = "0 0 0 3px var(--accent-dim)";
              }}
              onBlur={e => {
                e.target.style.borderColor = "var(--b1)";
                e.target.style.boxShadow = "none";
              }}
            />
            <button
              onClick={handleBuildApp}
              style={{
                position: "absolute",
                insetInlineEnd: 10, top: "50%", transform: "translateY(-50%)",
                padding: "8px 18px", borderRadius: 8, border: "none",
                background: prompt.trim().length > 2
                  ? "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)"
                  : "var(--bg-base)",
                color: prompt.trim().length > 2 ? "white" : "var(--t4)",
                fontSize: 13, fontWeight: 700, cursor: "pointer",
                transition: "all 0.15s", whiteSpace: "nowrap",
                boxShadow: prompt.trim().length > 2 ? "0 2px 10px rgba(110,50,224,0.28)" : "none",
              }}
            >
              {t("buildSection.buildBtn") || (isRtl ? "بناء ←" : "Build →")}
            </button>
          </div>

          {/* Idea chips */}
          <div style={{
            display: "flex", flexWrap: "wrap", gap: 6,
            justifyContent: "center", marginBottom: 52,
          }}>
            {chips.map((chip, idx) => {
              const idea = QUICK_IDEAS[idx] ?? { label: chip, prompt: chip };
              return (
                <button
                  key={chip}
                  onClick={() => handleChip(idea)}
                  style={{
                    padding: "5px 13px", borderRadius: 99,
                    fontSize: 12, fontWeight: 500,
                    background: "var(--bg-card)", border: "1px solid var(--b1)",
                    color: "var(--t3)", cursor: "pointer",
                    transition: "all 0.12s",
                  }}
                  onMouseEnter={e => {
                    const el = e.currentTarget as HTMLButtonElement;
                    el.style.borderColor = "var(--accent)";
                    el.style.color = "var(--accent)";
                    el.style.background = "var(--accent-dim)";
                  }}
                  onMouseLeave={e => {
                    const el = e.currentTarget as HTMLButtonElement;
                    el.style.borderColor = "var(--b1)";
                    el.style.color = "var(--t3)";
                    el.style.background = "var(--bg-card)";
                  }}
                >
                  {chip}
                </button>
              );
            })}
          </div>
        </div>

        {/* ── Recent Projects ─────────────────────────────────────────── */}
        {(projectsQuery.status === "loading" || projects.length > 0) && (
          <div style={{
            maxWidth: 640, margin: "0 auto",
            padding: "0 24px 52px",
          }}>
            <div style={{
              fontSize: 11, fontWeight: 700, letterSpacing: "0.08em",
              color: "var(--t4)", textTransform: "uppercase",
              marginBottom: 10,
              textAlign: isRtl ? "right" : "left",
            }}>
              {isRtl ? "المشاريع الأخيرة" : "Recent Projects"}
            </div>

            {projectsQuery.status === "loading" ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {[1, 2, 3].map(i => (
                  <div key={i} className="skeleton" style={{ height: 46, borderRadius: 10 }} />
                ))}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {recentProjects.map(p => {
                  const sColor = STATUS_COLOR[p.status ?? "draft"] ?? "var(--t5)";
                  return (
                    <button
                      key={p.id}
                      onClick={() => {
                        sessionStorage.setItem("flow_active_project", p.id);
                        setPage("app-builder");
                      }}
                      dir={isRtl ? "rtl" : "ltr"}
                      style={{
                        display: "flex", alignItems: "center", gap: 12,
                        width: "100%", padding: "10px 14px", borderRadius: 10,
                        background: "var(--bg-card)", border: "1px solid var(--b1)",
                        cursor: "pointer", textAlign: "left",
                        transition: "border-color 0.12s, background 0.12s",
                      }}
                      onMouseEnter={e => {
                        (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent)";
                        (e.currentTarget as HTMLButtonElement).style.background = "var(--accent-dim)";
                      }}
                      onMouseLeave={e => {
                        (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)";
                        (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-card)";
                      }}
                    >
                      {/* Avatar */}
                      <div style={{
                        width: 30, height: 30, borderRadius: 8, flexShrink: 0,
                        background: "var(--accent-dim)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "var(--accent)", fontSize: 13, fontWeight: 800,
                      }}>
                        {p.name.charAt(0).toUpperCase()}
                      </div>

                      {/* Name + time */}
                      <div style={{
                        flex: 1, minWidth: 0,
                        textAlign: isRtl ? "right" : "left",
                      }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, color: "var(--t1)",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                          {p.name}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 1 }}>
                          {relTime(p.created_at, lang)}
                        </div>
                      </div>

                      {/* Status dot */}
                      <span style={{
                        width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                        background: sColor,
                      }} />

                      {/* Arrow */}
                      <span style={{ fontSize: 12, color: "var(--t5)", flexShrink: 0 }}>
                        {isRtl ? "←" : "→"}
                      </span>
                    </button>
                  );
                })}

                {projects.length > 5 && (
                  <button
                    onClick={() => setPage("app-builder")}
                    style={{
                      padding: "8px 0", fontSize: 12, fontWeight: 600,
                      color: "var(--accent)", background: "none", border: "none",
                      cursor: "pointer", textAlign: isRtl ? "right" : "left",
                    }}
                  >
                    {isRtl
                      ? `عرض جميع المشاريع (${projects.length}) →`
                      : `View all ${projects.length} projects →`
                    }
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
