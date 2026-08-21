import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Icons } from "../../icons";
import type { Page } from "../../types";

type CmdItem = { id: string; label: string; sub?: string; icon: React.JSX.Element; action: () => void; kbd?: string };

export function CommandPalette({ onNavigate, onClose }: { onNavigate: (p: Page) => void; onClose: () => void }) {
  const { t } = useTranslation("common");
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const pg = (key: string) => t(`cmdPalette.pages.${key}.label`);
  const pgSub = (key: string) => t(`cmdPalette.pages.${key}.sub`);
  const ac = (key: string) => t(`cmdPalette.actions.${key}.label`);
  const acSub = (key: string) => t(`cmdPalette.actions.${key}.sub`);

  const pages: CmdItem[] = [
    { id: "home",       label: pg("home"),       sub: pgSub("home"),       icon: Icons.home(),       action: () => onNavigate("home")       },
    { id: "ai",         label: pg("ai"),         sub: pgSub("ai"),         icon: Icons.ai(),         action: () => onNavigate("ai")         },
    { id: "dev",        label: pg("dev"),        sub: pgSub("dev"),        icon: Icons.dev(),        action: () => onNavigate("dev")        },
    { id: "design",     label: pg("design"),     sub: pgSub("design"),     icon: Icons.design(),     action: () => onNavigate("design")     },
    { id: "automation", label: pg("automation"), sub: pgSub("automation"), icon: Icons.automation(), action: () => onNavigate("automation") },
    { id: "agentos",     label: pg("agentos"),     sub: pgSub("agentos"),     icon: Icons.agentos(),     action: () => onNavigate("agentos")     },
    { id: "marketplace", label: pg("marketplace"), sub: pgSub("marketplace"), icon: Icons.marketplace(), action: () => onNavigate("marketplace") },
    { id: "organizations", label: pg("organizations"), sub: pgSub("organizations"), icon: Icons.organizations(), action: () => onNavigate("organizations") },
    { id: "teams",          label: pg("teams"),          sub: pgSub("teams"),          icon: Icons.teams(),         action: () => onNavigate("teams")         },
    { id: "billing",        label: pg("billing"),       sub: pgSub("billing"),          icon: Icons.billing(),       action: () => onNavigate("billing")       },
    { id: "app-builder",   label: pg("app-builder"),   sub: pgSub("app-builder"),   icon: Icons["app-builder"](),       action: () => onNavigate("app-builder")   },
    { id: "live-preview",  label: pg("live-preview"),  sub: pgSub("live-preview"),  icon: Icons["live-preview"](),      action: () => onNavigate("live-preview")  },
    { id: "integrations",  label: pg("integrations"),  sub: pgSub("integrations"),  icon: Icons.integrations(),         action: () => onNavigate("integrations")  },
    { id: "runs",          label: pg("runs"),          sub: pgSub("runs"),          icon: Icons.runs(),                 action: () => onNavigate("runs")          },
    { id: "publish-center",label: pg("publish-center"),sub: pgSub("publish-center"),icon: Icons["publish-center"](),    action: () => onNavigate("publish-center")},
    { id: "social",        label: pg("social"),        sub: pgSub("social"),        icon: Icons.social(),               action: () => onNavigate("social")        },
    { id: "settings",      label: pg("settings"),      sub: pgSub("settings"),      icon: Icons.settings(),             action: () => onNavigate("settings")      },
  ];

  const actions: CmdItem[] = [
    { id: "new-chat",    label: ac("newChat"),    sub: acSub("newChat"), icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="10" y1="10" x2="14" y2="10"/></svg>, action: () => { onNavigate("ai"); onClose(); }, kbd: "N" },
    { id: "new-build",   label: ac("newBuild"),   sub: acSub("newBuild"),    icon: Icons.dev(),    action: () => { onNavigate("dev"); onClose(); } },
    { id: "new-agent",   label: ac("newAgent"),   sub: acSub("newAgent"),   icon: Icons.ai(),     action: () => { onNavigate("ai");  onClose(); } },
    { id: "new-project", label: ac("newProject"), sub: acSub("newProject"),     icon: Icons.home(),   action: () => { onNavigate("home"); onClose(); } },
  ];

  const allItems = [...actions, ...pages];
  const filtered = q.trim()
    ? allItems.filter(i => i.label.toLowerCase().includes(q.toLowerCase()) || i.sub?.toLowerCase().includes(q.toLowerCase()))
    : allItems;

  function run(item: CmdItem) { item.action(); onClose(); }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown")  { e.preventDefault(); setActive(a => Math.min(a + 1, filtered.length - 1)); }
    if (e.key === "ArrowUp")    { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
    if (e.key === "Enter")      { e.preventDefault(); if (filtered[active]) run(filtered[active]); }
    if (e.key === "Escape")     { onClose(); }
  }

  const pageItems = filtered.filter(i => pages.find(p => p.id === i.id));
  const actionItems = filtered.filter(i => actions.find(a => a.id === i.id));
  let idx = 0;

  function renderGroup(label: string, items: CmdItem[]) {
    if (items.length === 0) return null;
    return (
      <div key={label}>
        <p className="cmd-group-label">{label}</p>
        {items.map(item => {
          const myIdx = idx++;
          return (
            <div key={item.id} className={`cmd-item${myIdx === active ? " active" : ""}`}
              role="button" tabIndex={0}
              onClick={() => run(item)} onMouseEnter={() => setActive(myIdx)}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); run(item); } }}>
              <div className="cmd-item-icon">{item.icon}</div>
              <div className="cmd-item-label">
                {item.label}
                {item.sub && <div className="cmd-item-sub">{item.sub}</div>}
              </div>
              {item.kbd && <span className="cmd-item-kbd">{item.kbd}</span>}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    // Backdrop click-to-close + modal click-shield — neither is in the tab
    // order (no tabIndex) and Escape (handled by the search input's onKey
    // above) is already the keyboard equivalent for closing.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
    <div className="cmd-overlay" onClick={onClose}>
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
      <div className="cmd-modal" onClick={e => e.stopPropagation()}>
        <div className="cmd-header">
          <span className="cmd-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></span>
          <input ref={inputRef} className="cmd-input" value={q} onChange={e => { setQ(e.target.value); setActive(0); }}
            onKeyDown={onKey} placeholder={t("cmdPalette.searchPlaceholder")} />
          <span className="cmd-kbd">ESC</span>
        </div>
        <div className="cmd-list">
          {filtered.length === 0 && <div style={{ padding: "24px", textAlign: "center", color: "var(--t5)", fontSize: 13 }}>{t("cmdPalette.noResults", { query: q })}</div>}
          {renderGroup(t("cmdPalette.quickActions"), actionItems)}
          {renderGroup(t("cmdPalette.navigateGroup"), pageItems)}
        </div>
        <div className="cmd-footer">
          <span><span className="cmd-kbd">↑↓</span> {t("cmdPalette.kbdNavigate")}</span>
          <span><span className="cmd-kbd">↵</span> {t("cmdPalette.kbdOpen")}</span>
          <span><span className="cmd-kbd">ESC</span> {t("cmdPalette.kbdClose")}</span>
        </div>
      </div>
    </div>
  );
}
