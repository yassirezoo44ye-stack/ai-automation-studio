/**
 * Training Studio — Phase 1 Production UI
 *
 * Architecture:
 * - Left sub-nav (200px) + main content, same pattern as Design Studio
 * - All API calls via trainingService (real backend)
 * - Reuses GoldButton, GlassCard, Dialog, KpiCard, EmptyState, SkeletonCard
 * - Sections: Overview | Courses | Video Studio | Scripts | Quizzes |
 *             Localization | Learners | Analytics
 * - RTL: no hardcoded directions; inherits app-level [dir] attribute
 * - Responsive: flex-column on narrow viewports
 * - Dark/light: 100% CSS token usage, no hardcoded colors
 */
import {
  useState, useEffect, useCallback, Fragment,
  type ReactNode, type FormEvent, type CSSProperties, type MouseEvent,
} from "react";
import { useTranslation } from "react-i18next";
import {
  GoldButton, GlassCard, Dialog, KpiCard,
} from "../../shared/ui/gold";
import { EmptyState }    from "../../shared/ui/EmptyState";
import { SkeletonCard }  from "../../shared/ui/SkeletonLoader";
import { StatusBadge }   from "../../shared/ui/StatusBadge";
import type { StatusBadgeKind } from "../../shared/lib/theme";
import {
  listCourses, createCourse, updateCourse,
  listLessons, createLesson, updateLesson, deleteLesson,
  listScripts, createScript,
  listVideos, createVideo, generateVideo,
  listQuizzes, createQuiz, addQuestion,
  listLearners, createLearner,
  listJobs,
  type Course, type Lesson, type Script,
  type Video, type Quiz, type Question, type Learner, type Job,
} from "./services/trainingService";

// ── Section type ─────────────────────────────────────────────────────────────

type Section =
  | "overview"
  | "courses"
  | "videoStudio"
  | "scripts"
  | "quizzes"
  | "localization"
  | "learners"
  | "analytics";

const SECTIONS: { id: Section; icon: ReactNode }[] = [
  { id: "overview",     icon: <GridIcon /> },
  { id: "courses",      icon: <BookIcon /> },
  { id: "videoStudio",  icon: <VideoIcon /> },
  { id: "scripts",      icon: <ScriptIcon /> },
  { id: "quizzes",      icon: <QuizIcon /> },
  { id: "localization", icon: <GlobeIcon /> },
  { id: "learners",     icon: <UsersIcon /> },
  { id: "analytics",    icon: <BarChartIcon /> },
];

// ── Root page ────────────────────────────────────────────────────────────────

export function TrainingStudioPage() {
  const { t } = useTranslation("trainingStudio");
  const [section, setSection] = useState<Section>("overview");

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden", background: "var(--bg-base)" }}>
      {/* ── Left sub-nav ──────────────────────────────────────────────────── */}
      <aside style={{
        width: 200, flexShrink: 0,
        borderInlineEnd: "1px solid var(--b1)",
        background: "var(--bg-surface)",
        display: "flex", flexDirection: "column",
        overflowY: "auto",
      }}>
        {/* Header */}
        <div style={{
          padding: "16px 16px 14px",
          borderBottom: "1px solid var(--b1)",
        }}>
          <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--t1)", letterSpacing: "-0.2px" }}>
            {t("title")}
          </div>
          <div style={{ fontSize: 10.5, color: "var(--t5)", marginTop: 3, lineHeight: 1.4 }}>
            {t("subtitle")}
          </div>
        </div>

        {/* Nav */}
        <nav style={{ padding: "8px 0", flex: 1 }} aria-label={t("title")}>
          {SECTIONS.map(({ id, icon }) => {
            const active = section === id;
            return (
              <button
                key={id}
                onClick={() => setSection(id)}
                aria-current={active ? "page" : undefined}
                style={{
                  display: "flex", alignItems: "center", gap: 9,
                  padding: "8px 14px", width: "100%",
                  background: active ? "var(--accent-dim)" : "transparent",
                  border: "none",
                  borderInlineStart: active ? "2px solid var(--accent)" : "2px solid transparent",
                  color: active ? "var(--accent)" : "var(--t3)",
                  fontSize: 12.5, fontWeight: active ? 600 : 400,
                  cursor: "pointer", textAlign: "start",
                  transition: "background 0.1s, color 0.1s",
                  outline: "none",
                }}
                onFocus={e => { if (!active) e.currentTarget.style.background = "var(--bg-hover)"; }}
                onBlur={e => { if (!active) e.currentTarget.style.background = "transparent"; }}
              >
                <span style={{ opacity: active ? 1 : 0.55, display: "flex", flexShrink: 0 }}>
                  {icon}
                </span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t(`nav.${id}`)}
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      {/* ── Main content ──────────────────────────────────────────────────── */}
      <main style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>
        <SectionRouter section={section} onNavigate={setSection} />
      </main>
    </div>
  );
}

function SectionRouter({ section, onNavigate }: { section: Section; onNavigate: (s: Section) => void }) {
  switch (section) {
    case "overview":     return <OverviewSection onNavigate={onNavigate} />;
    case "courses":      return <CoursesSection />;
    case "videoStudio":  return <VideoStudioSection />;
    case "scripts":      return <ScriptsSection />;
    case "quizzes":      return <QuizzesSection />;
    case "localization": return <LocalizationSection />;
    case "learners":     return <LearnersSection />;
    case "analytics":    return <AnalyticsSection />;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// OVERVIEW
// ─────────────────────────────────────────────────────────────────────────────

function OverviewSection({ onNavigate }: { onNavigate: (s: Section) => void }) {
  const { t } = useTranslation("trainingStudio");
  const [courses,  setCourses]  = useState<Course[]>([]);
  const [learners, setLearners] = useState<Learner[]>([]);
  const [jobs,     setJobs]     = useState<Job[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      listCourses({ limit: 100 }),
      listLearners({ limit: 100 }),
      listJobs({ limit: 20 }),
    ])
      .then(([c, l, j]) => { setCourses(c); setLearners(l); setJobs(j); })
      .catch(() => setError(t("errors.loadFailed")))
      .finally(() => setLoading(false));
  }, [t]);

  const published     = courses.filter(c => c.status === "published").length;
  const activeJobs    = jobs.filter(j => j.status === "queued" || j.status === "processing");
  const recentCourses = [...courses].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 5);

  return (
    <PageShell title={t("overview.title")}>
      {loading ? (
        <SkeletonGrid />
      ) : error ? (
        <ErrorBanner message={error} />
      ) : (
        <>
          {/* KPI row */}
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 28 }}>
            <KpiCard label={t("overview.totalCourses")}  value={courses.length}  icon={<BookIcon />} />
            <KpiCard label={t("overview.published")}     value={published}       icon={<CheckCircleIcon />} accent />
            <KpiCard label={t("overview.totalLearners")} value={learners.length} icon={<UsersIcon />} />
            <KpiCard label={t("overview.activeJobs")}    value={activeJobs.length} icon={<SpinnerIcon />} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
            {/* Recent courses */}
            <GlassCard lift={false}>
              <SectionHeader label={t("overview.recentActivity")} />
              {recentCourses.length === 0 ? (
                <p style={{ fontSize: 13, color: "var(--t4)", margin: "12px 0 4px" }}>
                  {t("overview.noActivity")}
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
                  {recentCourses.map(c => (
                    <button
                      key={c.id}
                      onClick={() => onNavigate("courses")}
                      style={{
                        display: "flex", alignItems: "center", gap: 10,
                        background: "var(--bg-base)", border: "1px solid var(--b1)",
                        borderRadius: 10, padding: "10px 12px", cursor: "pointer",
                        textAlign: "start", width: "100%",
                        transition: "border-color 0.12s",
                      }}
                      onMouseEnter={e => e.currentTarget.style.borderColor = "var(--accent-border)"}
                      onMouseLeave={e => e.currentTarget.style.borderColor = "var(--b1)"}
                    >
                      <div style={{
                        width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                        background: "var(--accent-dim)", display: "flex", alignItems: "center", justifyContent: "center",
                        color: "var(--accent)",
                      }}>
                        <BookIcon />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {c.title}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
                          {c.language.toUpperCase()} · {t(`courses.status.${c.status}`)}
                        </div>
                      </div>
                      <StatusBadge kind={statusKind(c.status)} label={t(`courses.status.${c.status}`)} />
                    </button>
                  ))}
                </div>
              )}
            </GlassCard>

            {/* Active jobs */}
            <GlassCard lift={false}>
              <SectionHeader label={t("overview.activeJobs")} />
              {activeJobs.length === 0 ? (
                <p style={{ fontSize: 13, color: "var(--t4)", margin: "12px 0 4px" }}>
                  {t("overview.noActivity")}
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
                  {activeJobs.map(j => (
                    <div key={j.id} style={{
                      display: "flex", alignItems: "center", gap: 10,
                      background: "var(--bg-base)", border: "1px solid var(--b1)",
                      borderRadius: 10, padding: "10px 12px",
                    }}>
                      <div style={{ width: 8, height: 8, borderRadius: "50%", background: j.status === "processing" ? "var(--blue)" : "var(--yellow)", flexShrink: 0 }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {j.job_type.replace(/_/g, " ")}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--t4)" }}>{t(`jobs.status.${j.status}`)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </GlassCard>
          </div>
        </>
      )}
    </PageShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COURSES — list + builder
// ─────────────────────────────────────────────────────────────────────────────

function CoursesSection() {
  const { t } = useTranslation("trainingStudio");
  const [courses,  setCourses]  = useState<Course[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [search,   setSearch]   = useState("");
  const [filter,   setFilter]   = useState<"" | "draft" | "published" | "archived">("");
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Course | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    listCourses({ limit: 100 })
      .then(setCourses)
      .catch(() => setError(t("errors.loadFailed")))
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const filtered = courses.filter(c => {
    const matchSearch = !search || c.title.toLowerCase().includes(search.toLowerCase());
    const matchFilter = !filter || c.status === filter;
    return matchSearch && matchFilter;
  });

  if (selected) {
    return (
      <CourseBuilder
        course={selected}
        onBack={() => { setSelected(null); load(); }}
      />
    );
  }

  return (
    <PageShell
      title={t("courses.title")}
      action={
        <GoldButton onClick={() => setCreating(true)} variant="primary">
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> {t("courses.create")}
        </GoldButton>
      }
    >
      {/* Toolbar */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={t("courses.search")}
        />
        <select
          value={filter}
          onChange={e => setFilter(e.target.value as typeof filter)}
          aria-label={t("courses.filter")}
          style={selectStyle}
        >
          <option value="">{t("courses.all")}</option>
          <option value="draft">{t("courses.status.draft")}</option>
          <option value="published">{t("courses.status.published")}</option>
          <option value="archived">{t("courses.status.archived")}</option>
        </select>
      </div>

      {loading ? (
        <SkeletonGrid />
      ) : error ? (
        <ErrorBanner message={error} onRetry={load} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<BookIconLg />}
          title={t("courses.empty")}
          description=""
          action={
            <GoldButton onClick={() => setCreating(true)} variant="primary">
              {t("courses.create")}
            </GoldButton>
          }
        />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))", gap: 14 }}>
          {filtered.map(c => (
            <CourseCard key={c.id} course={c} onClick={() => setSelected(c)} />
          ))}
        </div>
      )}

      {/* Create dialog */}
      <CreateCourseDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreate={c => { setCourses(prev => [c, ...prev]); setSelected(c); setCreating(false); }}
      />
    </PageShell>
  );
}

function CourseCard({ course, onClick }: { course: Course; onClick: () => void }) {
  const { t, i18n } = useTranslation("trainingStudio");
  return (
    <GlassCard onClick={onClick} lift>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10, flexShrink: 0,
          background: "var(--accent-dim)", color: "var(--accent)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <BookIcon />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {course.title}
          </div>
          <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
            {course.language.toUpperCase()}
          </div>
        </div>
        <StatusBadge kind={statusKind(course.status)} label={t(`courses.status.${course.status}`)} />
      </div>
      {course.description && (
        <p style={{ fontSize: 12.5, color: "var(--t3)", margin: "0 0 10px", lineHeight: 1.5, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
          {course.description}
        </p>
      )}
      <div style={{ fontSize: 11, color: "var(--t5)", marginTop: "auto" }}>
        {relativeDate(course.updated_at, i18n.language)}
      </div>
    </GlassCard>
  );
}

function CreateCourseDialog({ open, onClose, onCreate }: {
  open: boolean;
  onClose: () => void;
  onCreate: (c: Course) => void;
}) {
  const { t } = useTranslation("trainingStudio");
  const [title, setTitle]   = useState("");
  const [desc,  setDesc]    = useState("");
  const [lang,  setLang]    = useState("en");
  const [busy,  setBusy]    = useState(false);
  const [err,   setErr]     = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true); setErr(null);
    try {
      const c = await createCourse({ title: title.trim(), description: desc.trim() || undefined, language: lang });
      setTitle(""); setDesc(""); setLang("en");
      onCreate(c);
    } catch {
      setErr(t("errors.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title={t("courses.create")} width={440}>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field label={t("courseBuilder.courseTitle")} required>
          <input
            type="text" value={title} onChange={e => setTitle(e.target.value)}
            placeholder={t("courseBuilder.courseTitle")}
            required autoFocus
            style={inputStyle}
          />
        </Field>
        <Field label={t("courseBuilder.description")}>
          <textarea
            value={desc} onChange={e => setDesc(e.target.value)}
            rows={3} style={{ ...inputStyle, resize: "vertical" }}
          />
        </Field>
        <Field label={t("courseBuilder.language")}>
          <select value={lang} onChange={e => setLang(e.target.value)} style={selectStyle}>
            {LANGS.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </Field>
        {err && <ErrorBanner message={err} />}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 4 }}>
          <GoldButton variant="ghost" onClick={onClose} type="button">{t("actions.cancel")}</GoldButton>
          <GoldButton variant="primary" type="submit" disabled={busy || !title.trim()}>
            {busy ? t("actions.saving") : t("courses.create")}
          </GoldButton>
        </div>
      </form>
    </Dialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COURSE BUILDER (split panel)
// ─────────────────────────────────────────────────────────────────────────────

function CourseBuilder({ course, onBack }: { course: Course; onBack: () => void }) {
  const { t } = useTranslation("trainingStudio");
  const [lessons,     setLessons]     = useState<Lesson[]>([]);
  const [activeLesson, setActiveLesson] = useState<Lesson | null>(null);
  const [loadingL,    setLoadingL]    = useState(true);
  const [dirty,       setDirty]       = useState(false);
  const [saving,      setSaving]      = useState(false);

  // course title edit
  const [editTitle, setEditTitle] = useState(course.title);
  const [editDesc,  setEditDesc]  = useState(course.description ?? "");

  const loadLessons = useCallback(() => {
    setLoadingL(true);
    listLessons(course.id)
      .then(ls => {
        setLessons(ls);
        // Functional update: auto-selects first lesson only if none is selected yet.
        setActiveLesson(prev => prev ?? ls[0] ?? null);
      })
      .catch(() => {})
      .finally(() => setLoadingL(false));
  }, [course.id]);

  useEffect(() => { loadLessons(); }, [loadLessons]);

  const saveCourse = async () => {
    if (!dirty) return;
    setSaving(true);
    try {
      await updateCourse(course.id, { title: editTitle, description: editDesc || undefined });
      setDirty(false);
    } catch {
      // keep dirty so user can retry
    } finally {
      setSaving(false);
    }
  };

  const publishCourse = async () => {
    const newStatus = course.status === "published" ? "draft" : "published";
    try { await updateCourse(course.id, { status: newStatus }); } catch {}
  };

  const addLesson = async () => {
    const pos = lessons.length;
    try {
      const l = await createLesson(course.id, {
        title: t("courseBuilder.lessons.defaultTitle", { n: pos + 1 }),
        position: pos,
      });
      setLessons(prev => [...prev, l]);
      setActiveLesson(l);
    } catch {}
  };

  const removeLesson = async (id: string) => {
    if (!window.confirm(t("courseBuilder.lessons.confirmDelete"))) return;
    try {
      await deleteLesson(id);
      setLessons(prev => prev.filter(l => l.id !== id));
      setActiveLesson(prev => prev?.id === id ? null : prev);
    } catch {}
  };

  const moveLesson = async (id: string, dir: -1 | 1) => {
    const idx = lessons.findIndex(l => l.id === id);
    if (idx < 0) return;
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= lessons.length) return;
    const reordered = [...lessons];
    [reordered[idx], reordered[newIdx]] = [reordered[newIdx], reordered[idx]];
    setLessons(reordered);
    // persist positions
    await Promise.all(reordered.map((l, i) => updateLesson(l.id, { position: i }).catch(() => {})));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Top bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "12px 20px", borderBottom: "1px solid var(--b1)",
        background: "var(--bg-surface)", flexShrink: 0, flexWrap: "wrap",
      }}>
        <button
          onClick={onBack}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)", display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}
          aria-label={t("courseBuilder.back")}
        >
          <ChevronLeftIcon /> {t("courseBuilder.back")}
        </button>
        <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8 }}>
          <input
            value={editTitle}
            onChange={e => { setEditTitle(e.target.value); setDirty(true); }}
            style={{ ...inputStyle, fontSize: 14.5, fontWeight: 700, padding: "6px 10px", flex: 1, maxWidth: 400 }}
            aria-label={t("courseBuilder.courseTitle")}
          />
          {dirty && <span style={{ fontSize: 11, color: "var(--yellow)", fontWeight: 600 }}>● {t("courseBuilder.unsaved")}</span>}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <GoldButton variant="ghost" onClick={saveCourse} disabled={!dirty || saving}>
            {saving ? t("courseBuilder.saving") : t("courseBuilder.save")}
          </GoldButton>
          <GoldButton variant="primary" onClick={publishCourse}>
            {course.status === "published" ? t("courseBuilder.unpublish") : t("courseBuilder.publish")}
          </GoldButton>
        </div>
      </div>

      {/* Split layout */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Lesson list */}
        <div style={{
          width: 220, flexShrink: 0,
          borderInlineEnd: "1px solid var(--b1)",
          background: "var(--bg-surface)",
          display: "flex", flexDirection: "column",
          overflowY: "auto",
        }}>
          <div style={{ padding: "12px 14px 8px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {t("courseBuilder.lessons.title")}
            </span>
            <button
              onClick={addLesson}
              title={t("courseBuilder.lessons.add")}
              aria-label={t("courseBuilder.lessons.add")}
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--accent)", fontSize: 18, lineHeight: 1, padding: "2px 4px" }}
            >+</button>
          </div>

          {loadingL ? (
            <div style={{ padding: 14 }}><SkeletonCard /></div>
          ) : lessons.length === 0 ? (
            <div style={{ padding: "24px 14px", textAlign: "center", color: "var(--t4)", fontSize: 12 }}>
              {t("courseBuilder.lessons.empty")}
            </div>
          ) : (
            lessons.map((l, i) => {
              const active = activeLesson?.id === l.id;
              return (
                <div
                  key={l.id}
                  style={{
                    display: "flex", alignItems: "center",
                    padding: "8px 10px 8px 14px",
                    background: active ? "var(--accent-dim)" : "transparent",
                    borderInlineStart: active ? "2px solid var(--accent)" : "2px solid transparent",
                    cursor: "pointer",
                    gap: 6,
                  }}
                  onClick={() => setActiveLesson(l)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={e => e.key === "Enter" && setActiveLesson(l)}
                >
                  <span style={{ fontSize: 10, color: "var(--t5)", minWidth: 16 }}>{String(i + 1).padStart(2, "0")}</span>
                  <span style={{ flex: 1, fontSize: 12.5, color: active ? "var(--accent)" : "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: active ? 600 : 400 }}>
                    {l.title}
                  </span>
                  <div style={{ display: "flex", flexDirection: "column", gap: 1, flexShrink: 0 }}>
                    <MoveBtn dir="up"   disabled={i === 0}               onClick={e => { e.stopPropagation(); moveLesson(l.id, -1); }} />
                    <MoveBtn dir="down" disabled={i === lessons.length-1} onClick={e => { e.stopPropagation(); moveLesson(l.id,  1); }} />
                  </div>
                  <button
                    onClick={e => { e.stopPropagation(); removeLesson(l.id); }}
                    title={t("courseBuilder.lessons.delete")}
                    aria-label={t("courseBuilder.lessons.delete")}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", fontSize: 13, padding: "0 2px", lineHeight: 1 }}
                  >×</button>
                </div>
              );
            })
          )}

          {lessons.length > 0 && (
            <div style={{ padding: "10px 14px", borderTop: "1px solid var(--b1)", marginTop: "auto" }}>
              <button
                onClick={addLesson}
                style={{ width: "100%", background: "none", border: "1px dashed var(--b2)", borderRadius: 8, padding: "7px 0", color: "var(--t4)", fontSize: 12, cursor: "pointer" }}
              >
                + {t("courseBuilder.lessons.add")}
              </button>
            </div>
          )}
        </div>

        {/* Lesson editor */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px" }}>
          {activeLesson ? (
            <LessonEditor
              lesson={activeLesson}
              courseId={course.id}
              onChange={updated => setLessons(prev => prev.map(l => l.id === updated.id ? updated : l))}
            />
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--t4)", fontSize: 13 }}>
              {t("courseBuilder.lessons.empty")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MoveBtn({ dir, disabled, onClick }: { dir: "up" | "down"; disabled: boolean; onClick: (e: MouseEvent<HTMLButtonElement>) => void }) {
  return (
    <button
      onClick={onClick} disabled={disabled}
      style={{ background: "none", border: "none", cursor: disabled ? "default" : "pointer", color: disabled ? "var(--b2)" : "var(--t4)", fontSize: 9, padding: "1px", lineHeight: 1 }}
      aria-label={dir === "up" ? "Move up" : "Move down"}
    >
      {dir === "up" ? "▲" : "▼"}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LESSON EDITOR
// ─────────────────────────────────────────────────────────────────────────────

function LessonEditor({ lesson, courseId, onChange }: {
  lesson: Lesson;
  courseId: string;
  onChange: (l: Lesson) => void;
}) {
  const { t } = useTranslation("trainingStudio");
  const [title,  setTitle]  = useState(lesson.title);
  const [desc,   setDesc]   = useState(lesson.description ?? "");
  const [dirty,  setDirty]  = useState(false);
  const [saving, setSaving] = useState(false);

  const [scripts, setScripts] = useState<Script[]>([]);
  const [videos,  setVideos]  = useState<Video[]>([]);
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [loadingData, setLoadingData] = useState(true);

  // Script editor modal
  const [scriptOpen, setScriptOpen] = useState(false);
  const [scriptContent, setScriptContent] = useState("");
  const [savingScript,  setSavingScript]  = useState(false);

  // Quiz creation modal
  const [quizOpen,    setQuizOpen]    = useState(false);
  const [quizTitle,   setQuizTitle]   = useState("");
  const [savingQuiz,  setSavingQuiz]  = useState(false);

  // Video generation
  const [generatingVideo, setGeneratingVideo] = useState<string | null>(null);

  useEffect(() => {
    setTitle(lesson.title);
    setDesc(lesson.description ?? "");
    setDirty(false);
    setLoadingData(true);
    Promise.all([
      listScripts(lesson.id),
      listVideos(lesson.id),
      listQuizzes(lesson.id),
    ])
      .then(([s, v, q]) => { setScripts(s); setVideos(v); setQuizzes(q); })
      .catch(() => {})
      .finally(() => setLoadingData(false));
  }, [lesson.id, lesson.title, lesson.description]);

  const saveLesson = async () => {
    setSaving(true);
    try {
      const updated = await updateLesson(lesson.id, { title: title.trim(), description: desc.trim() || undefined });
      onChange(updated);
      setDirty(false);
    } catch {} finally { setSaving(false); }
  };

  const createVideoForLesson = async () => {
    try {
      const v = await createVideo(lesson.id, { title: `${lesson.title} video`, language: "en" });
      setVideos(prev => [...prev, v]);
    } catch {}
  };

  const handleGenerateVideo = async (videoId: string) => {
    setGeneratingVideo(videoId);
    try {
      const updated = await generateVideo(videoId);
      setVideos(prev => prev.map(v => v.id === videoId ? updated : v));
    } catch {} finally { setGeneratingVideo(null); }
  };

  const saveScript = async (e: FormEvent) => {
    e.preventDefault();
    setSavingScript(true);
    try {
      const s = await createScript(lesson.id, { content: scriptContent.trim() });
      setScripts(prev => [s, ...prev]);
      setScriptOpen(false);
      setScriptContent("");
    } catch {} finally { setSavingScript(false); }
  };

  const saveQuiz = async (e: FormEvent) => {
    e.preventDefault();
    setSavingQuiz(true);
    try {
      const q = await createQuiz(lesson.id, { title: quizTitle.trim() });
      setQuizzes(prev => [...prev, q]);
      setQuizOpen(false);
      setQuizTitle("");
    } catch {} finally { setSavingQuiz(false); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
      {/* Lesson meta */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", margin: 0, flex: 1 }}>
            {t("courseBuilder.lessonEditor.title")}
          </h2>
          <StatusBadge kind={statusKind(lesson.status)} label={t(`courses.status.${lesson.status}`)} />
          {dirty && (
            <GoldButton variant="ghost" onClick={saveLesson} disabled={saving}>
              {saving ? t("courseBuilder.saving") : t("courseBuilder.save")}
            </GoldButton>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <input
            value={title}
            onChange={e => { setTitle(e.target.value); setDirty(true); }}
            style={{ ...inputStyle, fontSize: 14, fontWeight: 600 }}
            aria-label={t("courseBuilder.lessonEditor.title")}
          />
          <textarea
            value={desc}
            onChange={e => { setDesc(e.target.value); setDirty(true); }}
            placeholder={t("courseBuilder.description")}
            rows={2} style={{ ...inputStyle, resize: "vertical" }}
          />
        </div>
      </div>

      {loadingData ? <SkeletonCard /> : (
        <>
          {/* Script */}
          <ContentSection
            label={t("courseBuilder.lessonEditor.script")}
            icon={<ScriptIcon />}
            action={<GoldButton variant="ghost" onClick={() => setScriptOpen(true)}>+ {t("courseBuilder.lessonEditor.addScript")}</GoldButton>}
          >
            {scripts.length === 0 ? (
              <EmptyLine>{t("courseBuilder.lessonEditor.scriptEmpty")}</EmptyLine>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {scripts.slice(0, 2).map(s => (
                  <div key={s.id} style={{ background: "var(--bg-base)", border: "1px solid var(--b1)", borderRadius: 10, padding: "10px 14px" }}>
                    <div style={{ fontSize: 12, color: "var(--t4)", marginBottom: 6 }}>
                      {s.generated_by === "ai" ? "🤖 AI" : "✍️ Manual"} · {s.language.toUpperCase()} · {wordCount(s.content)} words
                    </div>
                    <p style={{ fontSize: 13, color: "var(--t2)", margin: 0, lineHeight: 1.6, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" }}>
                      {s.content}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </ContentSection>

          {/* Video */}
          <ContentSection
            label={t("courseBuilder.lessonEditor.video")}
            icon={<VideoIcon />}
            action={
              videos.length === 0
                ? <GoldButton variant="ghost" onClick={createVideoForLesson}>+ {t("courseBuilder.lessonEditor.addVideo")}</GoldButton>
                : null
            }
          >
            {videos.length === 0 ? (
              <EmptyLine>{t("courseBuilder.lessonEditor.videoEmpty")}</EmptyLine>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {videos.map(v => (
                  <div key={v.id} style={{ display: "flex", alignItems: "center", gap: 12, background: "var(--bg-base)", border: "1px solid var(--b1)", borderRadius: 10, padding: "10px 14px" }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--t2)" }}>{v.title || "Video"}</div>
                      <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 3 }}>{v.provider} · {v.language.toUpperCase()}</div>
                    </div>
                    <StatusBadge kind={videoStatusKind(v.status)} label={t(`videoStudio.videoStatus.${v.status}`)} />
                    {v.status === "completed" && v.url && (
                      <a href={v.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, color: "var(--accent)" }}>
                        {t("videoStudio.preview")}
                      </a>
                    )}
                    {(v.status === "draft" || v.status === "failed") && (
                      <GoldButton variant="ghost" onClick={() => handleGenerateVideo(v.id)} disabled={generatingVideo === v.id}>
                        {generatingVideo === v.id ? t("videoStudio.generating") : t("courseBuilder.lessonEditor.generateVideo")}
                      </GoldButton>
                    )}
                  </div>
                ))}
              </div>
            )}
          </ContentSection>

          {/* Quiz */}
          <ContentSection
            label={t("courseBuilder.lessonEditor.quiz")}
            icon={<QuizIcon />}
            action={<GoldButton variant="ghost" onClick={() => setQuizOpen(true)}>+ {t("courseBuilder.lessonEditor.addQuiz")}</GoldButton>}
          >
            {quizzes.length === 0 ? (
              <EmptyLine>{t("courseBuilder.lessonEditor.quizEmpty")}</EmptyLine>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {quizzes.map(q => (
                  <div key={q.id} style={{ background: "var(--bg-base)", border: "1px solid var(--b1)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10 }}>
                    <QuizIcon />
                    <span style={{ flex: 1, fontSize: 13, color: "var(--t2)", fontWeight: 600 }}>{q.title}</span>
                    <span style={{ fontSize: 11, color: "var(--t4)" }}>{t("quizzes.passScore")}: {q.pass_score}%</span>
                  </div>
                ))}
              </div>
            )}
          </ContentSection>
        </>
      )}

      {/* Script modal */}
      <Dialog open={scriptOpen} onClose={() => setScriptOpen(false)} title={t("courseBuilder.lessonEditor.addScript")}>
        <form onSubmit={saveScript} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <textarea
            value={scriptContent}
            onChange={e => setScriptContent(e.target.value)}
            placeholder={t("scripts.content")}
            rows={6} required autoFocus
            style={{ ...inputStyle, resize: "vertical" }}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <GoldButton variant="ghost" onClick={() => setScriptOpen(false)} type="button">{t("actions.cancel")}</GoldButton>
            <GoldButton variant="primary" type="submit" disabled={savingScript || !scriptContent.trim()}>
              {savingScript ? t("actions.saving") : t("scripts.save")}
            </GoldButton>
          </div>
        </form>
      </Dialog>

      {/* Quiz modal */}
      <Dialog open={quizOpen} onClose={() => setQuizOpen(false)} title={t("courseBuilder.lessonEditor.addQuiz")}>
        <form onSubmit={saveQuiz} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label={t("quizzes.title")} required>
            <input
              type="text" value={quizTitle} onChange={e => setQuizTitle(e.target.value)}
              placeholder={t("quizzes.title")} required autoFocus style={inputStyle}
            />
          </Field>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <GoldButton variant="ghost" onClick={() => setQuizOpen(false)} type="button">{t("actions.cancel")}</GoldButton>
            <GoldButton variant="primary" type="submit" disabled={savingQuiz || !quizTitle.trim()}>
              {savingQuiz ? t("actions.saving") : t("quizzes.add")}
            </GoldButton>
          </div>
        </form>
      </Dialog>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VIDEO STUDIO
// ─────────────────────────────────────────────────────────────────────────────

function VideoStudioSection() {
  const { t } = useTranslation("trainingStudio");
  const [courses,  setCourses]  = useState<Course[]>([]);
  const [lessons,  setLessons]  = useState<Lesson[]>([]);
  const [videos,   setVideos]   = useState<Video[]>([]);
  const [selCourse, setSelCourse] = useState<Course | null>(null);
  const [selLesson, setSelLesson] = useState<Lesson | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [generating, setGenerating] = useState<string | null>(null);

  useEffect(() => {
    listCourses({ limit: 100 })
      .then(cs => { setCourses(cs); if (cs.length > 0) setSelCourse(cs[0]); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selCourse) return;
    listLessons(selCourse.id)
      .then(ls => { setLessons(ls); setSelLesson(ls[0] ?? null); })
      .catch(() => setLessons([]));
  }, [selCourse]);

  useEffect(() => {
    if (!selLesson) { setVideos([]); return; }
    listVideos(selLesson.id).then(setVideos).catch(() => setVideos([]));
  }, [selLesson]);

  const handleGenerate = async (videoId: string) => {
    setGenerating(videoId);
    try {
      const updated = await generateVideo(videoId);
      setVideos(prev => prev.map(v => v.id === videoId ? updated : v));
    } catch {} finally { setGenerating(null); }
  };

  const createAndGenerate = async () => {
    if (!selLesson) return;
    try {
      const v = await createVideo(selLesson.id, { title: selLesson.title, language: "en" });
      setVideos(prev => [...prev, v]);
      await handleGenerate(v.id);
    } catch {}
  };

  return (
    <div style={{ display: "flex", height: "100%" }}>
      {/* Left: course + lesson selector */}
      <aside style={{ width: 220, flexShrink: 0, borderInlineEnd: "1px solid var(--b1)", background: "var(--bg-surface)", display: "flex", flexDirection: "column", overflowY: "auto" }}>
        <div style={{ padding: "14px 14px 8px" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
            {t("courses.title")}
          </div>
          {loading ? <SkeletonCard /> : (
            <select
              value={selCourse?.id ?? ""}
              onChange={e => setSelCourse(courses.find(c => c.id === e.target.value) ?? null)}
              style={{ ...selectStyle, width: "100%" }}
            >
              {courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
          )}
        </div>
        <div style={{ padding: "8px 14px 8px", borderTop: "1px solid var(--b1)" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
            {t("courseBuilder.lessons.title")}
          </div>
          {lessons.map(l => (
            <button
              key={l.id}
              onClick={() => setSelLesson(l)}
              style={{
                display: "block", width: "100%", textAlign: "start",
                padding: "7px 10px", borderRadius: 8, border: "none",
                background: selLesson?.id === l.id ? "var(--accent-dim)" : "transparent",
                color: selLesson?.id === l.id ? "var(--accent)" : "var(--t2)",
                fontSize: 12.5, fontWeight: selLesson?.id === l.id ? 600 : 400,
                cursor: "pointer", marginBottom: 2,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}
            >{l.title}</button>
          ))}
        </div>
      </aside>

      {/* Center: video preview */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto" }}>
        <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--t1)", flex: 1 }}>
            {selLesson?.title || t("videoStudio.selectLesson")}
          </h2>
          {selLesson && (
            <GoldButton variant="primary" onClick={createAndGenerate} disabled={!!generating}>
              {generating ? t("videoStudio.generating") : t("videoStudio.generate")}
            </GoldButton>
          )}
        </div>

        <div style={{ padding: "20px 24px" }}>
          {!selLesson ? (
            <EmptyState icon={<VideoIconLg />} title={t("videoStudio.selectLesson")} description="" />
          ) : videos.length === 0 ? (
            <EmptyState
              icon={<VideoIconLg />}
              title={t("videoStudio.noVideo")}
              description=""
              action={
                <GoldButton variant="primary" onClick={createAndGenerate}>
                  {t("videoStudio.generate")}
                </GoldButton>
              }
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {videos.map(v => (
                <VideoCard key={v.id} video={v} onGenerate={handleGenerate} generating={generating} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right: properties */}
      <aside style={{ width: 220, flexShrink: 0, borderInlineStart: "1px solid var(--b1)", background: "var(--bg-surface)", padding: "16px 14px", overflowY: "auto" }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", marginBottom: 14 }}>
          {t("videoStudio.properties.title")}
        </div>
        <ComingSoonPill label={t("videoStudio.properties.avatar")} />
        <ComingSoonPill label={t("videoStudio.properties.voice")} />
        <ComingSoonPill label={t("videoStudio.properties.captions")} />
        <p style={{ fontSize: 11.5, color: "var(--t4)", marginTop: 14, lineHeight: 1.6 }}>
          {t("videoStudio.properties.comingSoon")}
        </p>
      </aside>
    </div>
  );
}

function VideoCard({ video, onGenerate, generating }: { video: Video; onGenerate: (id: string) => void; generating: string | null }) {
  const { t } = useTranslation("trainingStudio");
  return (
    <GlassCard lift={false}>
      {/* Preview area */}
      {video.url && video.status === "completed" ? (
        <video
          src={video.url}
          controls
          style={{ width: "100%", borderRadius: 10, maxHeight: 360, background: "#000" }}
          aria-label={video.title ?? "Training Video"}
        />
      ) : (
        <div style={{
          width: "100%", paddingTop: "56.25%", borderRadius: 10,
          background: "var(--bg-base)", border: "1px solid var(--b1)",
          position: "relative", marginBottom: 12,
        }}>
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
            <VideoIconLg />
            <StatusBadge kind={videoStatusKind(video.status)} label={t(`videoStudio.videoStatus.${video.status}`)} />
          </div>
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{video.title || "Video"}</div>
          <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>{video.provider} · {video.language.toUpperCase()}</div>
        </div>
        {(video.status === "draft" || video.status === "failed") && (
          <GoldButton variant="ghost" onClick={() => onGenerate(video.id)} disabled={generating === video.id}>
            {generating === video.id ? t("videoStudio.generating") : t("videoStudio.regenerate")}
          </GoldButton>
        )}
      </div>
    </GlassCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SCRIPTS
// ─────────────────────────────────────────────────────────────────────────────

function ScriptsSection() {
  const { t, i18n } = useTranslation("trainingStudio");
  const [courses,  setCourses]  = useState<Course[]>([]);
  const [lessons,  setLessons]  = useState<Lesson[]>([]);
  const [scripts,  setScripts]  = useState<Script[]>([]);
  const [selCourse, setSelCourse] = useState<Course | null>(null);
  const [selLesson, setSelLesson] = useState<Lesson | null>(null);
  const [loading,   setLoading]  = useState(true);
  const [adding,    setAdding]   = useState(false);
  const [content,   setContent]  = useState("");
  const [saving,    setSaving]   = useState(false);

  useEffect(() => {
    listCourses({ limit: 100 })
      .then(cs => { setCourses(cs); if (cs.length > 0) setSelCourse(cs[0]); })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selCourse) return;
    listLessons(selCourse.id).then(ls => { setLessons(ls); setSelLesson(ls[0] ?? null); }).catch(() => {});
  }, [selCourse]);

  useEffect(() => {
    if (!selLesson) { setScripts([]); return; }
    listScripts(selLesson.id).then(setScripts).catch(() => setScripts([]));
  }, [selLesson]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!selLesson) return;
    setSaving(true);
    try {
      const s = await createScript(selLesson.id, { content: content.trim() });
      setScripts(prev => [s, ...prev]);
      setContent(""); setAdding(false);
    } catch {} finally { setSaving(false); }
  };

  return (
    <PageShell
      title={t("scripts.title")}
      action={selLesson ? <GoldButton variant="primary" onClick={() => setAdding(true)}>+ {t("scripts.add")}</GoldButton> : undefined}
    >
      {/* Selectors */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        {loading ? null : (
          <>
            <select value={selCourse?.id ?? ""} onChange={e => setSelCourse(courses.find(c => c.id === e.target.value) ?? null)} style={selectStyle}>
              {courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
            <select value={selLesson?.id ?? ""} onChange={e => setSelLesson(lessons.find(l => l.id === e.target.value) ?? null)} style={selectStyle}>
              {lessons.map(l => <option key={l.id} value={l.id}>{l.title}</option>)}
            </select>
          </>
        )}
      </div>

      {!selLesson ? (
        <EmptyState icon={<ScriptIconLg />} title={t("scripts.selectLesson")} description="" />
      ) : scripts.length === 0 ? (
        <EmptyState
          icon={<ScriptIconLg />}
          title={t("scripts.empty")}
          description=""
          action={<GoldButton variant="primary" onClick={() => setAdding(true)}>+ {t("scripts.add")}</GoldButton>}
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {scripts.map(s => (
            <GlassCard key={s.id} lift={false}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <span style={{ fontSize: 11, background: "var(--bg-base)", border: "1px solid var(--b1)", borderRadius: 6, padding: "2px 8px", color: "var(--t3)" }}>
                  {s.generated_by === "ai" ? "🤖 AI" : "✍️ Manual"}
                </span>
                <span style={{ fontSize: 11, color: "var(--t4)" }}>{s.language.toUpperCase()}</span>
                <span style={{ fontSize: 11, color: "var(--t5)", marginInlineStart: "auto" }}>{wordCount(s.content)} words · {relativeDate(s.created_at, i18n.language)}</span>
              </div>
              <p style={{ fontSize: 13, color: "var(--t2)", margin: 0, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{s.content}</p>
            </GlassCard>
          ))}
        </div>
      )}

      <Dialog open={adding} onClose={() => setAdding(false)} title={t("scripts.add")} width={560}>
        <form onSubmit={save} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <textarea
            value={content} onChange={e => setContent(e.target.value)}
            placeholder={t("scripts.content")} rows={8} required autoFocus
            style={{ ...inputStyle, resize: "vertical" }}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <GoldButton variant="ghost" onClick={() => setAdding(false)} type="button">{t("actions.cancel")}</GoldButton>
            <GoldButton variant="primary" type="submit" disabled={saving || !content.trim()}>
              {saving ? t("actions.saving") : t("scripts.save")}
            </GoldButton>
          </div>
        </form>
      </Dialog>
    </PageShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// QUIZZES
// ─────────────────────────────────────────────────────────────────────────────

function QuizzesSection() {
  const { t } = useTranslation("trainingStudio");
  const [courses,  setCourses]  = useState<Course[]>([]);
  const [lessons,  setLessons]  = useState<Lesson[]>([]);
  const [quizzes,  setQuizzes]  = useState<Quiz[]>([]);
  const [selCourse, setSelCourse] = useState<Course | null>(null);
  const [selLesson, setSelLesson] = useState<Lesson | null>(null);
  const [selQuiz,   setSelQuiz]   = useState<Quiz | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [creating,  setCreating]  = useState(false);
  const [quizTitle, setQuizTitle] = useState("");
  const [savingQ,   setSavingQ]   = useState(false);
  const [preview,   setPreview]   = useState(false);

  // Question form
  const [qText,    setQText]    = useState("");
  const [qType,    setQType]    = useState<"multiple_choice"|"true_false"|"knowledge_check">("multiple_choice");
  const [qOpts,    setQOpts]    = useState(["", "", "", ""]);
  const [qCorrect, setQCorrect] = useState<number>(0);
  const [qExpl,    setQExpl]    = useState("");
  const [addingQ,  setAddingQ]  = useState(false);
  const [savingQQ, setSavingQQ] = useState(false);

  useEffect(() => {
    listCourses({ limit: 100 })
      .then(cs => { setCourses(cs); if (cs.length > 0) setSelCourse(cs[0]); })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selCourse) return;
    listLessons(selCourse.id).then(ls => { setLessons(ls); setSelLesson(ls[0] ?? null); }).catch(() => {});
  }, [selCourse]);

  useEffect(() => {
    if (!selLesson) { setQuizzes([]); setSelQuiz(null); return; }
    listQuizzes(selLesson.id).then(qs => { setQuizzes(qs); setSelQuiz(qs[0] ?? null); }).catch(() => setQuizzes([]));
  }, [selLesson]);

  const createQ = async (e: FormEvent) => {
    e.preventDefault();
    setSavingQ(true);
    try {
      const q = await createQuiz(selLesson!.id, { title: quizTitle.trim() });
      setQuizzes(prev => [...prev, q]);
      setSelQuiz(q); setCreating(false); setQuizTitle("");
    } catch {} finally { setSavingQ(false); }
  };

  const addQ = async (e: FormEvent) => {
    e.preventDefault();
    if (!selQuiz) return;
    setSavingQQ(true);
    try {
      await addQuestion(selQuiz.id, {
        question_text: qText.trim(),
        question_type: qType,
        options: qOpts.filter(Boolean),
        correct_answer: qCorrect,
        explanation: qExpl.trim() || undefined,
        position: 0,
      });
      setQText(""); setQOpts(["","","",""]); setQExpl(""); setAddingQ(false);
    } catch {} finally { setSavingQQ(false); }
  };

  return (
    <PageShell title={t("quizzes.title")}>
      {/* Selectors */}
      {!loading && (
        <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
          <select value={selCourse?.id ?? ""} onChange={e => setSelCourse(courses.find(c => c.id === e.target.value) ?? null)} style={selectStyle}>
            {courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
          <select value={selLesson?.id ?? ""} onChange={e => setSelLesson(lessons.find(l => l.id === e.target.value) ?? null)} style={selectStyle}>
            {lessons.map(l => <option key={l.id} value={l.id}>{l.title}</option>)}
          </select>
          {selLesson && <GoldButton variant="primary" onClick={() => setCreating(true)}>+ {t("quizzes.add")}</GoldButton>}
        </div>
      )}

      {!selLesson ? (
        <EmptyState icon={<QuizIconLg />} title={t("quizzes.selectLesson")} description="" />
      ) : quizzes.length === 0 ? (
        <EmptyState icon={<QuizIconLg />} title={t("quizzes.empty")} description="" action={<GoldButton variant="primary" onClick={() => setCreating(true)}>+ {t("quizzes.add")}</GoldButton>} />
      ) : (
        <div style={{ display: "flex", gap: 20 }}>
          {/* Quiz list */}
          <div style={{ width: 200, flexShrink: 0 }}>
            {quizzes.map(q => (
              <button
                key={q.id}
                onClick={() => setSelQuiz(q)}
                style={{
                  display: "block", width: "100%", textAlign: "start",
                  padding: "9px 12px", borderRadius: 9, border: "none",
                  background: selQuiz?.id === q.id ? "var(--accent-dim)" : "transparent",
                  color: selQuiz?.id === q.id ? "var(--accent)" : "var(--t2)",
                  fontSize: 13, fontWeight: selQuiz?.id === q.id ? 600 : 400,
                  cursor: "pointer", marginBottom: 4,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}
              >{q.title}</button>
            ))}
          </div>

          {/* Quiz editor */}
          {selQuiz && (
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--t1)", flex: 1 }}>{selQuiz.title}</h3>
                <span style={{ fontSize: 12, color: "var(--t4)" }}>{t("quizzes.passScore")}: {selQuiz.pass_score}%</span>
                <GoldButton variant="ghost" onClick={() => setPreview(v => !v)}>
                  {preview ? t("quizzes.previewClose") : t("quizzes.preview")}
                </GoldButton>
                <GoldButton variant="ghost" onClick={() => setAddingQ(true)}>+ {t("quizzes.addQuestion")}</GoldButton>
              </div>
              {preview ? (
                <QuizPreview quiz={selQuiz} />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {/* Questions would be fetched here — Phase 2 enhancement */}
                  <p style={{ fontSize: 13, color: "var(--t4)" }}>
                    {t("quizzes.addQuestion")} — {t("comingSoon")} (question list view)
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Create quiz dialog */}
      <Dialog open={creating} onClose={() => setCreating(false)} title={t("quizzes.add")}>
        <form onSubmit={createQ} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label={t("quizzes.title")} required>
            <input type="text" value={quizTitle} onChange={e => setQuizTitle(e.target.value)} autoFocus required style={inputStyle} />
          </Field>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <GoldButton variant="ghost" onClick={() => setCreating(false)} type="button">{t("actions.cancel")}</GoldButton>
            <GoldButton variant="primary" type="submit" disabled={savingQ || !quizTitle.trim()}>
              {savingQ ? t("actions.saving") : t("quizzes.add")}
            </GoldButton>
          </div>
        </form>
      </Dialog>

      {/* Add question dialog */}
      <Dialog open={addingQ} onClose={() => setAddingQ(false)} title={t("quizzes.addQuestion")} width={520}>
        <form onSubmit={addQ} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label={t("quizzes.questionText")} required>
            <textarea value={qText} onChange={e => setQText(e.target.value)} rows={3} required autoFocus style={inputStyle} />
          </Field>
          <Field label={t("quizzes.questionType")}>
            <select value={qType} onChange={e => setQType(e.target.value as typeof qType)} style={selectStyle}>
              <option value="multiple_choice">{t("quizzes.types.multiple_choice")}</option>
              <option value="true_false">{t("quizzes.types.true_false")}</option>
              <option value="knowledge_check">{t("quizzes.types.knowledge_check")}</option>
            </select>
          </Field>
          {qType === "multiple_choice" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label style={labelStyle}>{t("quizzes.options")}</label>
              {qOpts.map((opt, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="radio" name="correct" checked={qCorrect === i}
                    onChange={() => setQCorrect(i)} aria-label={`Correct answer: option ${i+1}`}
                  />
                  <input
                    type="text" value={opt} onChange={e => setQOpts(prev => prev.map((o, j) => j === i ? e.target.value : o))}
                    placeholder={`Option ${i + 1}`} style={{ ...inputStyle, flex: 1 }}
                  />
                </div>
              ))}
              <p style={{ fontSize: 11, color: "var(--t4)", margin: 0 }}>{t("quizzes.correctAnswer")}: option {qCorrect + 1}</p>
            </div>
          )}
          {qType === "true_false" && (
            <Field label={t("quizzes.correctAnswer")}>
              <select value={qCorrect} onChange={e => setQCorrect(Number(e.target.value))} style={selectStyle}>
                <option value={0}>{t("quizzes.true")}</option>
                <option value={1}>{t("quizzes.false")}</option>
              </select>
            </Field>
          )}
          <Field label={t("quizzes.explanation")}>
            <textarea value={qExpl} onChange={e => setQExpl(e.target.value)} rows={2} style={inputStyle} />
          </Field>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <GoldButton variant="ghost" onClick={() => setAddingQ(false)} type="button">{t("actions.cancel")}</GoldButton>
            <GoldButton variant="primary" type="submit" disabled={savingQQ || !qText.trim()}>
              {savingQQ ? t("actions.saving") : t("quizzes.addQuestion")}
            </GoldButton>
          </div>
        </form>
      </Dialog>
    </PageShell>
  );
}

function QuizPreview({ quiz }: { quiz: Quiz }) {
  const { t } = useTranslation("trainingStudio");
  return (
    <GlassCard lift={false}>
      <h4 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{quiz.title}</h4>
      <p style={{ fontSize: 13, color: "var(--t4)", margin: 0 }}>
        {t("quizzes.passScore")}: {quiz.pass_score}%
      </p>
      <p style={{ fontSize: 12.5, color: "var(--t4)", marginTop: 16 }}>
        — {t("comingSoon")}: question list will load here in Phase 2 —
      </p>
    </GlassCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LOCALIZATION — Phase 3 placeholder
// ─────────────────────────────────────────────────────────────────────────────

const LOCALIZATION_LANGS = [
  { code: "ar", flag: "🇸🇦" },
  { code: "fr", flag: "🇫🇷" },
  { code: "es", flag: "🇪🇸" },
  { code: "de", flag: "🇩🇪" },
  { code: "zh", flag: "🇨🇳" },
  { code: "pt", flag: "🇧🇷" },
];

function LocalizationSection() {
  const { t } = useTranslation("trainingStudio");
  return (
    <PageShell title={t("localization.title")}>
      <div style={{ maxWidth: 680 }}>
        <p style={{ fontSize: 13.5, color: "var(--t3)", marginBottom: 24, lineHeight: 1.7 }}>
          {t("localization.description")}
        </p>

        {/* Preview table */}
        <GlassCard lift={false}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, paddingBottom: 12, borderBottom: "1px solid var(--b1)" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              {t("localization.title")} — Phase 3
            </div>
            <span style={{ marginInlineStart: "auto", fontSize: 11, background: "var(--yellow-dim)", color: "var(--yellow)", border: "1px solid var(--yellow)", borderRadius: 99, padding: "2px 10px", fontWeight: 600 }}>
              {t("comingSoon")}
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: "8px 12px", alignItems: "center" }}>
            {(["language","status","voice","actions"] as const).map(h => (
              <div key={h} style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.04em", padding: "4px 0" }}>
                {t(`localization.tableHeaders.${h}`)}
              </div>
            ))}
            {LOCALIZATION_LANGS.map(l => (
              <Fragment key={l.code}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--t2)" }}>
                  <span style={{ fontSize: 16 }}>{l.flag}</span>
                  {t(`localization.languages.${l.code}`)}
                </div>
                <div>
                  <StatusBadge kind="neutral" label={t("localization.status.pending")} />
                </div>
                <div style={{ fontSize: 12, color: "var(--t4)" }}>—</div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button disabled style={{ fontSize: 11.5, padding: "4px 10px", borderRadius: 7, border: "1px solid var(--b1)", background: "transparent", color: "var(--t4)", cursor: "not-allowed" }}>
                    {t("localization.actions.generate")}
                  </button>
                </div>
              </Fragment>
            ))}
          </div>
          <p style={{ fontSize: 12, color: "var(--t5)", marginTop: 18, fontStyle: "italic" }}>
            {t("localization.comingSoon")}
          </p>
        </GlassCard>
      </div>
    </PageShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LEARNERS
// ─────────────────────────────────────────────────────────────────────────────

function LearnersSection() {
  const { t, i18n } = useTranslation("trainingStudio");
  const [learners, setLearners] = useState<Learner[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [search,   setSearch]   = useState("");
  const [adding,   setAdding]   = useState(false);
  const [email,    setEmail]    = useState("");
  const [name,     setName]     = useState("");
  const [saving,   setSaving]   = useState(false);
  const [addErr,   setAddErr]   = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    listLearners({ limit: 200 })
      .then(setLearners)
      .catch(() => setError(t("errors.loadFailed")))
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const filtered = learners.filter(l =>
    !search || l.email.includes(search) || (l.name ?? "").toLowerCase().includes(search.toLowerCase())
  );

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setAddErr(null);
    try {
      const l = await createLearner({ email: email.trim(), name: name.trim() || undefined });
      setLearners(prev => [l, ...prev]);
      setEmail(""); setName(""); setAdding(false);
    } catch {
      setAddErr(t("errors.saveFailed"));
    } finally { setSaving(false); }
  };

  return (
    <PageShell
      title={t("learners.title")}
      action={<GoldButton variant="primary" onClick={() => setAdding(true)}>+ {t("learners.add")}</GoldButton>}
    >
      <div style={{ marginBottom: 16 }}>
        <SearchInput value={search} onChange={setSearch} placeholder={t("learners.search")} />
      </div>

      {loading ? <SkeletonGrid /> :
       error   ? <ErrorBanner message={error} onRetry={load} /> :
       filtered.length === 0 ? (
         <EmptyState icon={<UsersIconLg />} title={t("learners.empty")} description="" action={<GoldButton variant="primary" onClick={() => setAdding(true)}>+ {t("learners.add")}</GoldButton>} />
       ) : (
         <div style={{ overflowX: "auto" }}>
           <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
             <thead>
               <tr style={{ borderBottom: "1px solid var(--b1)" }}>
                 {[t("learners.email"), t("learners.name"), t("learners.enrolled")].map(h => (
                   <th key={h} style={{ textAlign: "start", padding: "8px 12px", fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.04em" }}>{h}</th>
                 ))}
               </tr>
             </thead>
             <tbody>
               {filtered.map((l, i) => (
                 <tr key={l.id} style={{ background: i % 2 === 0 ? "transparent" : "var(--bg-base)", borderBottom: "1px solid var(--b1)" }}>
                   <td style={{ padding: "10px 12px", color: "var(--t1)", fontWeight: 500 }}>{l.email}</td>
                   <td style={{ padding: "10px 12px", color: "var(--t2)" }}>{l.name ?? "—"}</td>
                   <td style={{ padding: "10px 12px", color: "var(--t4)", fontSize: 12 }}>{relativeDate(l.created_at, i18n.language)}</td>
                 </tr>
               ))}
             </tbody>
           </table>
         </div>
       )
      }

      <Dialog open={adding} onClose={() => setAdding(false)} title={t("learners.modal.title")} width={400}>
        <form onSubmit={handleAdd} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label={t("learners.modal.email")} required>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus style={inputStyle} />
          </Field>
          <Field label={t("learners.modal.name")}>
            <input type="text" value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
          </Field>
          {addErr && <ErrorBanner message={addErr} />}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <GoldButton variant="ghost" onClick={() => setAdding(false)} type="button">{t("learners.modal.cancel")}</GoldButton>
            <GoldButton variant="primary" type="submit" disabled={saving || !email.trim()}>
              {saving ? t("actions.saving") : t("learners.modal.save")}
            </GoldButton>
          </div>
        </form>
      </Dialog>
    </PageShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS — Phase 3 placeholder
// ─────────────────────────────────────────────────────────────────────────────

function AnalyticsSection() {
  const { t } = useTranslation("trainingStudio");
  return (
    <PageShell title={t("analytics.title")}>
      <div style={{ maxWidth: 560 }}>
        <p style={{ fontSize: 13.5, color: "var(--t3)", marginBottom: 24, lineHeight: 1.7 }}>
          {t("analytics.description")}
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
          {["Completion Rate", "Avg. Quiz Score", "Training Minutes"].map(label => (
            <GlassCard key={label} lift={false}>
              <div style={{ fontSize: 11, color: "var(--t4)", marginBottom: 8, fontWeight: 600 }}>{label}</div>
              <div style={{ fontSize: 28, fontWeight: 700, color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>—</div>
              <span style={{ fontSize: 10, color: "var(--t5)" }}>{t("comingSoon")}</span>
            </GlassCard>
          ))}
        </div>
        <p style={{ fontSize: 12, color: "var(--t5)", marginTop: 20, fontStyle: "italic" }}>
          {t("analytics.comingSoon")}
        </p>
      </div>
    </PageShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SHARED UI COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

function PageShell({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Page header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "16px 24px", borderBottom: "1px solid var(--b1)",
        background: "var(--bg-surface)", flexShrink: 0, flexWrap: "wrap",
      }}>
        <h1 style={{ margin: 0, fontSize: 15.5, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.2px", flex: 1 }}>
          {title}
        </h1>
        {action}
      </div>
      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
        {children}
      </div>
    </div>
  );
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
      {label}
    </div>
  );
}

function ContentSection({ label, icon, action, children }: { label: string; icon: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ color: "var(--t3)", display: "flex" }}>{icon}</span>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--t2)" }}>{label}</span>
        {action && <span style={{ marginInlineStart: "auto" }}>{action}</span>}
      </div>
      {children}
    </div>
  );
}

function EmptyLine({ children }: { children: ReactNode }) {
  return (
    <p style={{ fontSize: 12.5, color: "var(--t4)", margin: "4px 0", fontStyle: "italic" }}>{children}</p>
  );
}

function ComingSoonPill({ label }: { label: string }) {
  const { t } = useTranslation("trainingStudio");
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--b1)" }}>
      <span style={{ fontSize: 12.5, color: "var(--t2)" }}>{label}</span>
      <span style={{ fontSize: 10, color: "var(--t5)", background: "var(--bg-base)", border: "1px solid var(--b1)", borderRadius: 6, padding: "2px 7px" }}>
        {t("comingSoon")}
      </span>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={labelStyle}>
        {label}{required && <span style={{ color: "var(--red)", marginInlineStart: 2 }}>*</span>}
      </label>
      {children}
    </div>
  );
}

function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div style={{ position: "relative", flex: 1, maxWidth: 320 }}>
      <span style={{ position: "absolute", insetInlineStart: 10, top: "50%", transform: "translateY(-50%)", color: "var(--t4)", pointerEvents: "none", display: "flex" }}>
        <SearchIcon />
      </span>
      <input
        type="search" value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ ...inputStyle, paddingInlineStart: 34, width: "100%" }}
        aria-label={placeholder}
      />
    </div>
  );
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useTranslation("trainingStudio");
  return (
    <div role="alert" style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", background: "var(--red-dim)", border: "1px solid var(--red)", borderRadius: 10, fontSize: 13, color: "var(--red)" }}>
      <span style={{ flex: 1 }}>{message}</span>
      {onRetry && (
        <button onClick={onRetry} style={{ background: "none", border: "none", color: "var(--red)", cursor: "pointer", fontWeight: 600, fontSize: 12 }}>
          {t("actions.retry")}
        </button>
      )}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 14 }}>
      {[1,2,3].map(i => <SkeletonCard key={i} />)}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// STYLES
// ─────────────────────────────────────────────────────────────────────────────

const inputStyle: CSSProperties = {
  width: "100%", fontSize: 13,
  background: "var(--bg-input)", border: "1px solid var(--b1)",
  borderRadius: 9, padding: "10px 14px",
  color: "var(--t1)", boxSizing: "border-box",
  outline: "none", transition: "border-color .18s, box-shadow .18s",
  fontFamily: "inherit",
};

const selectStyle: CSSProperties = {
  fontSize: 12.5, background: "var(--bg-input)", color: "var(--t1)",
  border: "1px solid var(--b1)", borderRadius: 9, padding: "8px 12px",
  cursor: "pointer", outline: "none", fontFamily: "inherit",
};

const labelStyle: CSSProperties = {
  fontSize: 12, fontWeight: 600, color: "var(--t3)",
};

// ─────────────────────────────────────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────────────────────────────────────

const LANGS = [
  { code: "en", label: "English" },
  { code: "ar", label: "العربية" },
  { code: "fr", label: "Français" },
  { code: "es", label: "Español" },
  { code: "de", label: "Deutsch" },
  { code: "zh", label: "中文" },
];

function statusKind(status: string): StatusBadgeKind {
  switch (status) {
    case "published": return "success";
    case "archived":  return "neutral";
    case "draft":
    default:          return "info";
  }
}

function videoStatusKind(status: string): StatusBadgeKind {
  switch (status) {
    case "completed":  return "success";
    case "failed":     return "error";
    case "processing":
    case "queued":     return "warning";
    default:           return "neutral";
  }
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

/** Locale-aware relative time using the browser's Intl.RelativeTimeFormat. */
function relativeDate(iso: string, locale = "en"): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  const rtf  = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (secs < 60)  return rtf.format(-secs, "second");
  const mins = Math.floor(secs / 60);
  if (mins < 60)  return rtf.format(-mins, "minute");
  const hrs  = Math.floor(mins / 60);
  if (hrs  < 24)  return rtf.format(-hrs, "hour");
  return rtf.format(-Math.floor(hrs / 24), "day");
}

// ─────────────────────────────────────────────────────────────────────────────
// ICONS — inline SVG, no external deps
// ─────────────────────────────────────────────────────────────────────────────

function BookIcon()   { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>; }
function BookIconLg() { return <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>; }
function VideoIcon()  { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18"/><path d="M10 15l5-3-5-3v6z"/></svg>; }
function VideoIconLg(){ return <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18"/><path d="M10 15l5-3-5-3v6z"/></svg>; }
function ScriptIcon() { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>; }
function ScriptIconLg(){return <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>; }
function QuizIcon()   { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>; }
function QuizIconLg() { return <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>; }
function GlobeIcon()  { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>; }
function UsersIcon()  { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>; }
function UsersIconLg(){ return <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>; }
function BarChartIcon(){return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/></svg>; }
function GridIcon()   { return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>; }
function SearchIcon() { return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>; }
function ChevronLeftIcon(){return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>; }
function CheckCircleIcon(){return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>; }
function SpinnerIcon(){return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>; }
