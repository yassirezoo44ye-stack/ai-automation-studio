import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON, API } from "../../utils/api";
import { useAppContext } from "../../contexts/app";
import { useLangContext } from "../../contexts/lang";
import { S } from "../../styles/theme";
import { GlassCard } from "../../shared/ui/gold";
import AxonLogo from "../../AxonLogo";

// Local inline-code pill — S.code used a stale pre-rebrand gold-bg/purple-text
// combo; this uses live accent tokens so it stays correct across themes.
const codeStyle: React.CSSProperties = {
  background: "var(--accent-dim)", padding: "2px 8px",
  borderRadius: 6, fontSize: 12, color: "var(--accent-2)",
  fontFamily: "var(--font-mono)",
};

type SettingsTab = "system" | "ai" | "appearance" | "about";

interface RuntimeInfo { available?: boolean; version?: string | null }

// ── User preferences persisted to localStorage ────────────────────────────────
const PREFS_KEY = "axon-prefs";

interface UserPrefs {
  chatModel:    string;
  buildModel:   string;
  sidebarMode:  "expanded" | "collapsed";
}

const DEFAULT_PREFS: UserPrefs = {
  chatModel:   "claude-sonnet-4-6",
  buildModel:  "claude-sonnet-4-6",
  sidebarMode: "expanded",
};

function loadPrefs(): UserPrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    return raw ? { ...DEFAULT_PREFS, ...JSON.parse(raw) } : { ...DEFAULT_PREFS };
  } catch { return { ...DEFAULT_PREFS }; }
}

function savePrefs(p: UserPrefs) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, padding: "3px 0" }}>
      <span style={{ color: "var(--t4)", fontWeight: 500 }}>{label}</span>
      <span style={{ color: "var(--t2)", fontWeight: 500, textAlign: "right" as const }}>{value}</span>
    </div>
  );
}

export function SettingsPage() {
  const { t } = useTranslation("settings");
  const { theme, setTheme, setSidebarCollapsed } = useAppContext();
  const { lang, setLang } = useLangContext();
  const [tab, setTab]         = useState<SettingsTab>("system");
  const [health, setHealth]   = useState<Record<string, string> | null>(null);
  const [stats, setStats]     = useState<Record<string, number> | null>(null);
  const [runtimes, setRuntimes] = useState<Record<string, RuntimeInfo> | null>(null);
  const [prefs, setPrefs]     = useState<UserPrefs>(loadPrefs);
  const [saved, setSaved]     = useState(false);

  useEffect(() => {
    fetch(`${API}/health`).then(r => parseJSON<Record<string, string>>(r, "/health")).then(setHealth).catch(() => {});
    apiFetch(`/api/stats`).then(r => parseJSON<Record<string, number>>(r, "/api/stats")).then(setStats).catch(() => {});
    apiFetch(`/api/runtimes`).then(r => parseJSON<{ runtimes?: Record<string, RuntimeInfo> }>(r, "/api/runtimes")).then(d => setRuntimes(d.runtimes ?? {})).catch(() => {});
  }, []);

  function updatePref<K extends keyof UserPrefs>(key: K, val: UserPrefs[K]) {
    const next = { ...prefs, [key]: val };
    setPrefs(next);
    savePrefs(next);
    if (key === "sidebarMode") setSidebarCollapsed(val === "collapsed");
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  }

  const SETTINGS_NAV: { id: SettingsTab; label: string; icon: React.JSX.Element }[] = [
    { id: "system",     label: t("nav.system"),     icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg> },
    { id: "ai",         label: t("nav.ai"),         icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg> },
    { id: "appearance", label: t("nav.appearance"), icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20"/></svg> },
    { id: "about",      label: t("nav.about"),      icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg> },
  ];

  const CHAT_MODELS = [
    ["claude-sonnet-4-6",        "Claude Sonnet 4.6 (Recommended)"],
    ["claude-opus-4-8",          "Claude Opus 4.8 (Most Capable)"],
    ["claude-haiku-4-5-20251001","Claude Haiku 4.5 (Fastest)"],
  ] as const;

  const BUILD_MODELS = [
    ["claude-sonnet-4-6", "Claude Sonnet 4.6"],
    ["claude-opus-4-8",   "Claude Opus 4.8"],
  ] as const;

  const THEME_OPTIONS = [
    { id: "dark"          as const, label: t("appearance.themeDark"),         bg: "#15121F" },
    { id: "light"         as const, label: t("appearance.themeLight"),        bg: "#F5F4FA" },
    { id: "high-contrast" as const, label: t("appearance.themeHighContrast"), bg: "#000000", swatchBorder: "#FFFF00" },
  ];

  const LANG_OPTIONS = [
    { id: "en" as const, label: "English" },
    { id: "ar" as const, label: "العربية" },
  ];

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>{t("title")}</span>
        {saved && (
          <span style={{ fontSize: 12, color: "var(--green)", fontWeight: 500, display: "flex", alignItems: "center", gap: 5 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            {t("saved")}
          </span>
        )}
      </header>
      <div style={{ flex: 1, overflow: "hidden", display: "flex" }}>
        {/* Left nav */}
        <div style={{ width: 200, flexShrink: 0, padding: "20px 12px", borderInlineEnd: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 2 }}>
          <div className="section-label" style={{ marginBottom: 10, paddingInlineStart: 10 }}>{t("nav.label")}</div>
          {SETTINGS_NAV.map(n => (
            <div key={n.id} className={`settings-nav-item${tab === n.id ? " active" : ""}`} onClick={() => setTab(n.id)} role="button" tabIndex={0} onKeyDown={e => e.key === "Enter" && setTab(n.id)}>
              {n.icon}
              {n.label}
            </div>
          ))}
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: "auto", padding: 28 }}>

          {tab === "system" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("system.backend")}</div>
                <GlassCard lift={false}>
                  {health ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--green)", flexShrink: 0, boxShadow: "0 0 8px var(--green)" }} />
                        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--green)" }}>{t("system.backendOnline")}</span>
                      </div>
                      <hr className="divider" />
                      <Row label={t("system.status")}     value={health.status} />
                      <Row label={t("system.database")}   value={health.db} />
                      <Row label={t("system.postgresql")} value={health.pg_version?.split(" on ")[0]} />
                    </div>
                  ) : (
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--red)", flexShrink: 0 }} />
                      <span style={{ fontSize: 13, color: "var(--red)" }}>{t("system.backendOffline")} <code style={codeStyle}>python main.py</code></span>
                    </div>
                  )}
                </GlassCard>
              </div>

              {runtimes && Object.keys(runtimes).length > 0 && (
                <div>
                  <div className="section-label" style={{ marginBottom: 12 }}>{t("system.runtimes")}</div>
                  <GlassCard lift={false}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {Object.entries(runtimes).map(([name, info]) => (
                        <div key={name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13 }}>
                          <span style={{ color: "var(--t3)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{name}</span>
                          <span className={`badge badge-${info?.available ? "green" : "muted"}`}>{info?.available ? (info.version ?? "available") : "not found"}</span>
                        </div>
                      ))}
                    </div>
                  </GlassCard>
                </div>
              )}

              {stats && (
                <div>
                  <div className="section-label" style={{ marginBottom: 12 }}>{t("system.usage")}</div>
                  <GlassCard lift={false}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <Row label={t("system.projects")}      value={String(stats.projects ?? 0)} />
                      <Row label={t("system.conversations")} value={String(stats.conversations ?? 0)} />
                      <Row label={t("system.messages")}      value={String(stats.messages ?? 0)} />
                      <Row label={t("system.agentRuns")}     value={String(stats.agent_runs ?? 0)} />
                      <Row label={t("system.successRate")}   value={<span style={{ color: "var(--green)", fontWeight: 600 }}>{stats.success_rate ?? 0}%</span>} />
                    </div>
                  </GlassCard>
                </div>
              )}

              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("system.shortcuts")}</div>
                <GlassCard lift={false}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    {([
                      [t("system.sectionGlobal"),        null,                        null],
                      [null,             "⌘K / Ctrl+K",              t("system.kbd.openPalette")],
                      [null,             "Esc",                       t("system.kbd.closeModals")],
                      [null,             "↑↓ + Enter",                t("system.kbd.navigatePalette")],
                      [t("system.sectionChat"),           null,                        null],
                      [null,             "Enter",                     t("system.kbd.sendMessage")],
                      [null,             "Shift+Enter",               t("system.kbd.newLine")],
                      [t("system.sectionDesignStudio"),  null,                        null],
                      [null,             "Ctrl+Z / ⌘Z",              t("system.kbd.undo")],
                      [null,             "Ctrl+Y / Ctrl+Shift+Z",    t("system.kbd.redo")],
                      [null,             "Ctrl+S / ⌘S",              t("system.kbd.saveCanvas")],
                      [null,             "Delete / Backspace",        t("system.kbd.deleteSelected")],
                      [null,             "Ctrl+C / ⌘C",              t("system.kbd.copySelected")],
                      [null,             "Ctrl+V / ⌘V",              t("system.kbd.paste")],
                      [null,             "Ctrl+A / ⌘A",              t("system.kbd.selectAll")],
                      [null,             "Ctrl++ / Ctrl+-",           t("system.kbd.zoom")],
                      [null,             "Ctrl+0 / ⌘0",              t("system.kbd.resetZoom")],
                      [null,             "Esc",                       t("system.kbd.deselect")],
                      [null,             "R",                         t("system.kbd.rectangleTool")],
                      [null,             "C",                         t("system.kbd.circleTool")],
                      [null,             "T",                         t("system.kbd.textTool")],
                    ] as [string | null, string | null, string | null][]).map(([section, kbd, desc], i) =>
                      section ? (
                        <div key={i} style={{ fontSize: 11, fontWeight: 700, color: "var(--ta)", letterSpacing: "0.08em", textTransform: "uppercase", marginTop: i === 0 ? 0 : 12, marginBottom: 4 }}>{section}</div>
                      ) : (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, padding: "3px 0" }}>
                          <span style={{ color: "var(--t4)" }}>{desc}</span>
                          <code style={{ ...codeStyle, fontSize: 11 }}>{kbd}</code>
                        </div>
                      )
                    )}
                  </div>
                </GlassCard>
              </div>
            </div>
          )}

          {tab === "ai" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("ai.anthropicApi")}</div>
                <GlassCard lift={false}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 14px", borderRadius: 10, background: "var(--accent-dim)", border: "1px solid var(--accent-border)" }}>
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--accent-2)" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                      <div style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6 }}>
                        {t("ai.apiKeyHint", { key: "ANTHROPIC_API_KEY", envFile: ".env" })}
                      </div>
                    </div>
                    <a href="https://console.anthropic.com/settings/billing" target="_blank" rel="noopener noreferrer"
                      style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--accent-2)" }}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                      {t("ai.manageBilling")}
                    </a>
                  </div>
                </GlassCard>
              </div>

              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("ai.defaultModels")}</div>
                <GlassCard lift={false}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div>
                      <label className="g-label" htmlFor="settings-chat-model">{t("ai.chatModel")}</label>
                      <select
                        id="settings-chat-model"
                        className="g-input"
                        value={prefs.chatModel}
                        onChange={e => updatePref("chatModel", e.target.value)}
                      >
                        {CHAT_MODELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                      <div style={{ color: "var(--t4)", marginTop: 5, fontSize: 11 }}>{t("ai.chatModelHint")}</div>
                    </div>
                    <div>
                      <label className="g-label" htmlFor="settings-build-model">{t("ai.buildModel")}</label>
                      <select
                        id="settings-build-model"
                        className="g-input"
                        value={prefs.buildModel}
                        onChange={e => updatePref("buildModel", e.target.value)}
                      >
                        {BUILD_MODELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                      <div style={{ color: "var(--t4)", marginTop: 5, fontSize: 11 }}>{t("ai.buildModelHint")}</div>
                    </div>
                  </div>
                </GlassCard>
              </div>
            </div>
          )}

          {tab === "appearance" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("appearance.theme")}</div>
                <GlassCard lift={false}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div style={{ display: "flex", gap: 10 }}>
                      {THEME_OPTIONS.map(opt => (
                        <button
                          key={opt.id}
                          onClick={() => setTheme(opt.id)}
                          aria-pressed={theme === opt.id}
                          style={{
                            flex: 1, border: `2px solid ${theme === opt.id ? "var(--accent)" : "var(--b1)"}`,
                            borderRadius: 12, padding: 12, cursor: "pointer",
                            textAlign: "center" as const, background: "transparent",
                          }}
                        >
                          {/* Swatch previews the theme's own raw colors, not the live tokens — this button lets you pick a theme you're not currently in. */}
                          <div style={{ width: "100%", height: 50, borderRadius: 8, background: opt.bg, marginBottom: 8, border: `1px solid ${"swatchBorder" in opt ? opt.swatchBorder : "rgba(128,128,128,0.15)"}` }} />
                          <div style={{ fontSize: 12, fontWeight: 500, color: theme === opt.id ? "var(--accent)" : "var(--t3)" }}>{opt.label}</div>
                        </button>
                      ))}
                    </div>
                    <hr className="divider" />
                    <div>
                      <label className="g-label" htmlFor="settings-sidebar-mode">{t("appearance.sidebarDefault")}</label>
                      <select
                        id="settings-sidebar-mode"
                        className="g-input"
                        value={prefs.sidebarMode}
                        onChange={e => updatePref("sidebarMode", e.target.value as UserPrefs["sidebarMode"])}
                      >
                        <option value="expanded">{t("appearance.sidebarExpanded")}</option>
                        <option value="collapsed">{t("appearance.sidebarCollapsed")}</option>
                      </select>
                    </div>
                  </div>
                </GlassCard>
              </div>

              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("appearance.language")}</div>
                <GlassCard lift={false}>
                  <div style={{ display: "flex", gap: 10 }}>
                    {LANG_OPTIONS.map(l => (
                      <button
                        key={l.id}
                        onClick={() => setLang(l.id)}
                        aria-pressed={lang === l.id}
                        style={{
                          flex: 1, border: `2px solid ${lang === l.id ? "var(--accent)" : "var(--b1)"}`,
                          borderRadius: 12, padding: 12, cursor: "pointer",
                          textAlign: "center" as const, background: "transparent",
                          fontSize: 13, fontWeight: 500, color: lang === l.id ? "var(--accent)" : "var(--t3)",
                        }}
                      >
                        {l.label}
                      </button>
                    ))}
                  </div>
                </GlassCard>
              </div>
            </div>
          )}

          {tab === "about" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
              <GlassCard lift={false} style={{ display: "flex", gap: 20, alignItems: "center" }}>
                <AxonLogo size={52} />
                <div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.4px" }}>Flow</div>
                  <div style={{ fontSize: 13, color: "var(--t4)", marginTop: 2 }}>{t("about.tagline")}</div>
                  <div style={{ fontSize: 12, color: "var(--t5)", marginTop: 6 }}>{t("about.poweredBy")}</div>
                </div>
              </GlassCard>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("about.stack")}</div>
                <GlassCard lift={false}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <Row label={t("about.frontend")} value="React 19 + Vite 8 + TypeScript" />
                    <Row label={t("about.backend")}  value="FastAPI + asyncpg" />
                    <Row label={t("about.database")} value="PostgreSQL" />
                    <Row label={t("about.ai")}       value="Anthropic Claude" />
                    <Row label={t("about.runtime")}  value="Python 3.11 + Node.js 20 LTS" />
                  </div>
                </GlassCard>
              </div>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>{t("about.license")}</div>
                <GlassCard lift={false}>
                  <div style={{ fontSize: 13, color: "var(--t4)", lineHeight: 1.7 }}>
                    {t("about.copyright", { year: new Date().getFullYear() })}
                  </div>
                </GlassCard>
              </div>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
