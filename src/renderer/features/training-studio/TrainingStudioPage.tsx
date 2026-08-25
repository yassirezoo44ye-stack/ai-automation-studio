/**
 * Training Studio — Phase 1 shell page.
 *
 * Renders a sub-navigation (sidebar tabs) and an empty-state placeholder
 * for each section. Phase 2 replaces the placeholders with real UI.
 *
 * Architecture notes:
 * - Uses OrgContext via apiFetch (same pattern as IntegrationsPage, RunsPage)
 * - All API calls target /api/training/* (registered in factory.py)
 * - i18n namespace: "trainingStudio"
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

type Section =
  | "courses"
  | "videoGen"
  | "scripts"
  | "avatars"
  | "quizzes"
  | "localization"
  | "learners"
  | "analytics";

const SECTIONS: { id: Section; icon: string }[] = [
  { id: "courses",      icon: "🎓" },
  { id: "videoGen",     icon: "🎬" },
  { id: "scripts",      icon: "📝" },
  { id: "avatars",      icon: "🧑‍💻" },
  { id: "quizzes",      icon: "✅" },
  { id: "localization", icon: "🌍" },
  { id: "learners",     icon: "👥" },
  { id: "analytics",    icon: "📊" },
];

export function TrainingStudioPage() {
  const { t } = useTranslation("trainingStudio");
  const [section, setSection] = useState<Section>("courses");

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* ── Left sub-nav ─────────────────────────────────────────────────── */}
      <aside style={{
        width: 200, flexShrink: 0,
        borderRight: "1px solid var(--b1)",
        background: "var(--bg-nav)",
        display: "flex", flexDirection: "column",
        padding: "16px 0",
        overflowY: "auto",
      }}>
        {/* Header */}
        <div style={{
          padding: "0 16px 16px",
          borderBottom: "1px solid var(--b1)",
          marginBottom: 8,
        }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: "var(--t1)", letterSpacing: "-0.3px" }}>
            {t("title")}
          </div>
          <div style={{ fontSize: 10, color: "var(--t5)", marginTop: 2, lineHeight: 1.4 }}>
            {t("subtitle")}
          </div>
        </div>

        {/* Nav items */}
        {SECTIONS.map(({ id, icon }) => (
          <button
            key={id}
            onClick={() => setSection(id)}
            style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 16px", width: "100%",
              background: section === id ? "var(--accent-dim)" : "transparent",
              border: "none", borderLeft: section === id ? "2px solid var(--accent)" : "2px solid transparent",
              color: section === id ? "var(--accent)" : "var(--t3)",
              fontSize: 13, fontWeight: section === id ? 600 : 400,
              cursor: "pointer", textAlign: "start",
              transition: "background 0.1s, color 0.1s",
            }}
          >
            <span style={{ fontSize: 15 }}>{icon}</span>
            <span>{t(`nav.${id}`)}</span>
          </button>
        ))}
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main style={{ flex: 1, overflowY: "auto", padding: "28px 32px" }}>
        <SectionContent section={section} />
      </main>
    </div>
  );
}

function SectionContent({ section }: { section: Section }) {
  const { t } = useTranslation("trainingStudio");

  if (section === "courses") return <CoursesSection />;

  // Phase 2+ placeholder for all other sections
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", height: "100%", gap: 16,
      color: "var(--t4)", textAlign: "center",
    }}>
      <div style={{ fontSize: 48 }}>
        {SECTIONS.find(s => s.id === section)?.icon ?? "🚧"}
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, color: "var(--t2)" }}>
        {t(`nav.${section}`)}
      </div>
      <div style={{ fontSize: 13, color: "var(--t5)", maxWidth: 320 }}>
        {t("comingSoon")}
      </div>
    </div>
  );
}

/** Phase 1 Courses section — list with empty state. Real data in Phase 2. */
function CoursesSection() {
  const { t } = useTranslation("trainingStudio");

  return (
    <div>
      {/* Top bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--t1)", letterSpacing: "-0.4px" }}>
            {t("courses.title")}
          </div>
        </div>
        <button
          style={{
            display: "flex", alignItems: "center", gap: 7,
            padding: "8px 16px", borderRadius: 9,
            background: "var(--accent)", color: "#fff",
            border: "none", fontSize: 13, fontWeight: 600, cursor: "pointer",
            boxShadow: "var(--glow-pink-subtle)",
            transition: "opacity 0.12s",
          }}
          onMouseEnter={e => (e.currentTarget.style.opacity = "0.88")}
          onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
        >
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>
          {t("courses.create")}
        </button>
      </div>

      {/* Empty state */}
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", padding: "80px 0",
        border: "1px dashed var(--b2)", borderRadius: 16,
        color: "var(--t4)", textAlign: "center", gap: 12,
      }}>
        <span style={{ fontSize: 48 }}>🎓</span>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t2)" }}>
          {t("courses.empty")}
        </div>
        <div style={{ fontSize: 12, color: "var(--t5)", maxWidth: 300 }}>
          Build AI-powered training courses from documents, URLs, or from scratch.
          Each course can include videos, quizzes, and multilingual support.
        </div>
      </div>
    </div>
  );
}
