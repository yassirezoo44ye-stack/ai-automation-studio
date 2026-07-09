import { useState, useRef, useEffect, createContext, useContext } from "react";
import { Icons } from "../../icons";
import type { Page } from "../../types";

type CmdItem = { id: string; label: string; sub?: string; icon: React.JSX.Element; action: () => void; kbd?: string };
export const CmdCtx = createContext<{ open: () => void; close: () => void }>({ open: () => {}, close: () => {} });
export function useCmdPalette() { return useContext(CmdCtx); }

export function CommandPalette({ onNavigate, onClose }: { onNavigate: (p: Page) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const pages: CmdItem[] = [
    { id: "home",       label: "Home",       sub: "Overview & projects",   icon: Icons.home(),       action: () => onNavigate("home")       },
    { id: "ai",         label: "AI",         sub: "Chat & agents",         icon: Icons.ai(),         action: () => onNavigate("ai")         },
    { id: "dev",        label: "Dev",        sub: "Build, run & package",  icon: Icons.dev(),        action: () => onNavigate("dev")        },
    { id: "design",     label: "Design",     sub: "Visual design studio",  icon: Icons.design(),     action: () => onNavigate("design")     },
    { id: "automation", label: "Automation", sub: "Tasks & workflows",     icon: Icons.automation(), action: () => onNavigate("automation") },
    { id: "agentos",     label: "AgentOS",     sub: "Self-evolving AI OS",     icon: Icons.agentos(),     action: () => onNavigate("agentos")     },
    { id: "marketplace", label: "Marketplace", sub: "Browse agents & plugins", icon: Icons.marketplace(), action: () => onNavigate("marketplace") },
    { id: "organizations", label: "Organizations", sub: "Create & switch orgs",  icon: Icons.organizations(), action: () => onNavigate("organizations") },
    { id: "teams",          label: "Teams",         sub: "Members & invitations", icon: Icons.teams(),         action: () => onNavigate("teams")         },
    { id: "billing",        label: "Billing",       sub: "Plan & usage",          icon: Icons.billing(),       action: () => onNavigate("billing")       },
    { id: "social",      label: "Social",      sub: "Social media content",    icon: Icons.social(),      action: () => onNavigate("social")      },
    { id: "settings",   label: "Settings",   sub: "App configuration",     icon: Icons.settings(),   action: () => onNavigate("settings")   },
  ];

  const actions: CmdItem[] = [
    { id: "new-chat",    label: "New Chat",    sub: "Start a conversation", icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="10" y1="10" x2="14" y2="10"/></svg>, action: () => { onNavigate("ai"); onClose(); }, kbd: "N" },
    { id: "new-build",   label: "New Build",   sub: "Open code builder",    icon: Icons.dev(),    action: () => { onNavigate("dev"); onClose(); } },
    { id: "new-agent",   label: "New Agent",   sub: "Create an AI agent",   icon: Icons.ai(),     action: () => { onNavigate("ai");  onClose(); } },
    { id: "new-project", label: "New Project", sub: "Create a project",     icon: Icons.home(),   action: () => { onNavigate("home"); onClose(); } },
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
              onClick={() => run(item)} onMouseEnter={() => setActive(myIdx)}>
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
    <div className="cmd-overlay" onClick={onClose}>
      <div className="cmd-modal" onClick={e => e.stopPropagation()}>
        <div className="cmd-header">
          <span className="cmd-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></span>
          <input ref={inputRef} className="cmd-input" value={q} onChange={e => { setQ(e.target.value); setActive(0); }}
            onKeyDown={onKey} placeholder="Search pages, actions…" />
          <span className="cmd-kbd">ESC</span>
        </div>
        <div className="cmd-list">
          {filtered.length === 0 && <div style={{ padding: "24px", textAlign: "center", color: "var(--t5)", fontSize: 13 }}>No results for "{q}"</div>}
          {renderGroup("Quick Actions", actionItems)}
          {renderGroup("Navigate", pageItems)}
        </div>
        <div className="cmd-footer">
          <span><span className="cmd-kbd">↑↓</span> navigate</span>
          <span><span className="cmd-kbd">↵</span> open</span>
          <span><span className="cmd-kbd">ESC</span> close</span>
        </div>
      </div>
    </div>
  );
}
