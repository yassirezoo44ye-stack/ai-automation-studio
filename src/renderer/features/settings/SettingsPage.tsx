import { useState, useEffect } from "react";
import { apiFetch, parseJSON, API } from "../../utils/api";
import { useAppContext } from "../../contexts/AppContext";
import { S } from "../../styles/theme";
import AxonLogo from "../../AxonLogo";

type SettingsTab = "system" | "ai" | "appearance" | "about";

const SETTINGS_NAV: { id: SettingsTab; label: string; icon: React.JSX.Element }[] = [
  { id: "system",     label: "System",     icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg> },
  { id: "ai",         label: "AI & Models",icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg> },
  { id: "appearance", label: "Appearance", icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20"/></svg> },
  { id: "about",      label: "About",      icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg> },
];

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

// Export so other components can read the preferred model
export function getPrefs(): UserPrefs { return loadPrefs(); }

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, padding: "3px 0" }}>
      <span style={{ color: "var(--t4)", fontWeight: 500 }}>{label}</span>
      <span style={{ color: "var(--t2)", fontWeight: 500, textAlign: "right" as const }}>{value}</span>
    </div>
  );
}

export function SettingsPage() {
  const { theme, setTheme, setSidebarCollapsed } = useAppContext();
  const [tab, setTab]         = useState<SettingsTab>("system");
  const [health, setHealth]   = useState<Record<string, string> | null>(null);
  const [stats, setStats]     = useState<Record<string, number> | null>(null);
  const [runtimes, setRuntimes] = useState<Record<string, any> | null>(null);
  const [prefs, setPrefs]     = useState<UserPrefs>(loadPrefs);
  const [saved, setSaved]     = useState(false);

  useEffect(() => {
    fetch(`${API}/health`).then(r => parseJSON<Record<string, string>>(r, "/health")).then(setHealth).catch(() => {});
    apiFetch(`/api/stats`).then(r => parseJSON<Record<string, number>>(r, "/api/stats")).then(setStats).catch(() => {});
    apiFetch(`/api/runtimes`).then(r => parseJSON<{ runtimes?: Record<string, unknown> }>(r, "/api/runtimes")).then(d => setRuntimes(d.runtimes ?? {})).catch(() => {});
  }, []);

  function updatePref<K extends keyof UserPrefs>(key: K, val: UserPrefs[K]) {
    const next = { ...prefs, [key]: val };
    setPrefs(next);
    savePrefs(next);
    if (key === "sidebarMode") setSidebarCollapsed(val === "collapsed");
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  }

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
    { id: "dark"  as const, label: "Dark",  bg: "#05070f" },
    { id: "light" as const, label: "Light", bg: "#f8f9fb" },
  ];

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Settings</span>
        {saved && (
          <span style={{ fontSize: 12, color: "var(--green)", fontWeight: 500, display: "flex", alignItems: "center", gap: 5 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            Saved
          </span>
        )}
      </header>
      <div style={{ flex: 1, overflow: "hidden", display: "flex" }}>
        {/* Left nav */}
        <div style={{ width: 200, flexShrink: 0, padding: "20px 12px", borderRight: "1px solid rgba(255,255,255,0.06)", display: "flex", flexDirection: "column", gap: 2 }}>
          <div className="section-label" style={{ marginBottom: 10, paddingLeft: 10 }}>Settings</div>
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
                <div className="section-label" style={{ marginBottom: 12 }}>Backend</div>
                <div style={S.card}>
                  {health ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#34d399", flexShrink: 0, boxShadow: "0 0 8px #34d399" }} />
                        <span style={{ fontSize: 13, fontWeight: 600, color: "#34d399" }}>Backend online</span>
                      </div>
                      <hr className="divider" />
                      <Row label="Status"     value={health.status} />
                      <Row label="Database"   value={health.db} />
                      <Row label="PostgreSQL" value={health.pg_version?.split(" on ")[0]} />
                    </div>
                  ) : (
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#f87171", flexShrink: 0 }} />
                      <span style={{ fontSize: 13, color: "#f87171" }}>Backend offline — run <code style={S.code}>python main.py</code></span>
                    </div>
                  )}
                </div>
              </div>

              {runtimes && Object.keys(runtimes).length > 0 && (
                <div>
                  <div className="section-label" style={{ marginBottom: 12 }}>Runtimes</div>
                  <div style={S.card}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {Object.entries(runtimes).map(([name, info]: [string, any]) => (
                        <div key={name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13 }}>
                          <span style={{ color: "var(--t3)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{name}</span>
                          <span className={`badge badge-${info?.available ? "green" : "muted"}`}>{info?.available ? (info.version ?? "available") : "not found"}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {stats && (
                <div>
                  <div className="section-label" style={{ marginBottom: 12 }}>Usage</div>
                  <div style={S.card}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <Row label="Projects"      value={String(stats.projects ?? 0)} />
                      <Row label="Conversations" value={String(stats.conversations ?? 0)} />
                      <Row label="Messages"      value={String(stats.messages ?? 0)} />
                      <Row label="Agent Runs"    value={String(stats.agent_runs ?? 0)} />
                      <Row label="Success Rate"  value={<span style={{ color: "#34d399", fontWeight: 600 }}>{stats.success_rate ?? 0}%</span>} />
                    </div>
                  </div>
                </div>
              )}

              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>Keyboard Shortcuts</div>
                <div style={S.card}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    {([
                      ["Global",         null,                        null],
                      [null,             "⌘K / Ctrl+K",              "Open command palette"],
                      [null,             "Esc",                       "Close modals / palette"],
                      [null,             "↑↓ + Enter",                "Navigate command palette"],
                      ["Chat",           null,                        null],
                      [null,             "Enter",                     "Send message"],
                      [null,             "Shift+Enter",               "New line in message"],
                      ["Design Studio",  null,                        null],
                      [null,             "Ctrl+Z / ⌘Z",              "Undo"],
                      [null,             "Ctrl+Y / Ctrl+Shift+Z",    "Redo"],
                      [null,             "Ctrl+S / ⌘S",              "Save canvas"],
                      [null,             "Delete / Backspace",        "Delete selected objects"],
                      [null,             "Ctrl+C / ⌘C",              "Copy selected"],
                      [null,             "Ctrl+V / ⌘V",              "Paste"],
                      [null,             "Ctrl+A / ⌘A",              "Select all"],
                      [null,             "Ctrl++ / Ctrl+-",           "Zoom in / out"],
                      [null,             "Ctrl+0 / ⌘0",              "Reset zoom"],
                      [null,             "Esc",                       "Deselect / cancel tool"],
                      [null,             "R",                         "Rectangle tool"],
                      [null,             "C",                         "Circle tool"],
                      [null,             "T",                         "Text tool"],
                    ] as [string | null, string | null, string | null][]).map(([section, kbd, desc], i) =>
                      section ? (
                        <div key={i} style={{ fontSize: 11, fontWeight: 700, color: "var(--ta)", letterSpacing: "0.08em", textTransform: "uppercase", marginTop: i === 0 ? 0 : 12, marginBottom: 4 }}>{section}</div>
                      ) : (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, padding: "3px 0" }}>
                          <span style={{ color: "var(--t4)" }}>{desc}</span>
                          <code style={{ ...S.code, fontSize: 11 }}>{kbd}</code>
                        </div>
                      )
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === "ai" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>Anthropic API</div>
                <div style={S.card}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 14px", borderRadius: 10, background: "rgba(99,102,241,0.08)", border: "1px solid rgba(99,102,241,0.2)" }}>
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                      <div style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6 }}>
                        Set <code style={S.code}>ANTHROPIC_API_KEY</code> in your <code style={S.code}>.env</code> file and restart the backend. Keys are never stored in the browser.
                      </div>
                    </div>
                    <a href="https://console.anthropic.com/settings/billing" target="_blank" rel="noopener noreferrer"
                      style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#6c8ef7" }}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                      Manage billing at console.anthropic.com
                    </a>
                  </div>
                </div>
              </div>

              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>Default Models</div>
                <div style={S.card}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div>
                      <label style={S.label}>Chat Model</label>
                      <select
                        style={S.textInput}
                        value={prefs.chatModel}
                        onChange={e => updatePref("chatModel", e.target.value)}
                      >
                        {CHAT_MODELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                      <div style={{ ...S.muted, marginTop: 5, fontSize: 11 }}>Used in the AI Workspace chat.</div>
                    </div>
                    <div>
                      <label style={S.label}>Build Model</label>
                      <select
                        style={S.textInput}
                        value={prefs.buildModel}
                        onChange={e => updatePref("buildModel", e.target.value)}
                      >
                        {BUILD_MODELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                      <div style={{ ...S.muted, marginTop: 5, fontSize: 11 }}>Used in the Dev Workspace code builder.</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === "appearance" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>Theme</div>
                <div style={S.card}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div style={{ display: "flex", gap: 10 }}>
                      {THEME_OPTIONS.map(t => (
                        <button
                          key={t.id}
                          onClick={() => setTheme(t.id)}
                          style={{
                            flex: 1, border: `2px solid ${theme === t.id ? "#8b5cf6" : "rgba(255,255,255,0.08)"}`,
                            borderRadius: 12, padding: 12, cursor: "pointer",
                            textAlign: "center" as const, background: "transparent",
                          }}
                        >
                          <div style={{ width: "100%", height: 50, borderRadius: 8, background: t.bg, marginBottom: 8, border: "1px solid rgba(128,128,128,0.15)" }} />
                          <div style={{ fontSize: 12, fontWeight: 500, color: theme === t.id ? "#a78bfa" : "var(--t3)" }}>{t.label}</div>
                        </button>
                      ))}
                    </div>
                    <hr className="divider" />
                    <div>
                      <label style={S.label}>Sidebar default</label>
                      <select
                        style={S.textInput}
                        value={prefs.sidebarMode}
                        onChange={e => updatePref("sidebarMode", e.target.value as UserPrefs["sidebarMode"])}
                      >
                        <option value="expanded">Expanded</option>
                        <option value="collapsed">Collapsed</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === "about" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
              <div style={{ ...S.card, display: "flex", gap: 20, alignItems: "center" }}>
                <AxonLogo size={52} />
                <div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.4px" }}>Axon</div>
                  <div style={{ fontSize: 13, color: "var(--t4)", marginTop: 2 }}>AI Automation Studio · v3.0.0</div>
                  <div style={{ fontSize: 12, color: "var(--t5)", marginTop: 6 }}>Powered by Claude</div>
                </div>
              </div>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>Stack</div>
                <div style={S.card}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <Row label="Frontend" value="React 19 + Vite 8 + TypeScript" />
                    <Row label="Backend"  value="FastAPI + asyncpg" />
                    <Row label="Database" value="PostgreSQL" />
                    <Row label="AI"       value="Anthropic Claude" />
                    <Row label="Runtime"  value="Python 3.11 + Node.js 20 LTS" />
                  </div>
                </div>
              </div>
              <div>
                <div className="section-label" style={{ marginBottom: 12 }}>License</div>
                <div style={S.card}>
                  <div style={{ fontSize: 13, color: "var(--t4)", lineHeight: 1.7 }}>
                    © {new Date().getFullYear()} Axon AI. All rights reserved.
                  </div>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
