/**
 * FLOW Global Command Bar — Ctrl+K
 *
 * AI-aware command palette that exposes:
 *   • Navigation to all pages
 *   • Quick actions that launch real workflows
 *   • Context-sensitive AI commands
 *
 * Design: Linear + Vercel command palette aesthetic.
 * All actions are real (navigate or sessionStorage handoff, never mock).
 */
import { useState, useRef, useEffect } from "react";
import { Icons } from "../../icons";
import type { Page } from "../../types";

type CmdItem = {
  id: string;
  label: string;
  sub?: string;
  icon: React.JSX.Element;
  badge?: string;
  action: () => void;
  kbd?: string;
  group: "ai" | "action" | "navigate" | "platform";
};

// ── Inline icons not in Icons registry ──────────────────────────────────────

const I = {
  terminal: () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>,
  zap:      () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>,
  agent:    () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3"/></svg>,
  workflow: () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>,
  shield:   () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
  monitor:  () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>,
  deploy:   () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>,
  chat:     () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  runs:     () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
  search:   () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>,
  sparkle:  () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z"/></svg>,
};

const GROUP_LABELS: Record<CmdItem["group"], string> = {
  ai:       "✦ AI Commands",
  action:   "Quick Actions",
  navigate: "Navigate",
  platform: "Platform",
};

export function CommandPalette({ onNavigate, onClose }: { onNavigate: (p: Page) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  function go(page: Page) { onNavigate(page); onClose(); }

  function buildAndGo(prompt?: string) {
    if (prompt) sessionStorage.setItem("flow_builder_prompt", prompt);
    go("app-builder");
  }

  // ── Command registry ────────────────────────────────────────────────────
  const items: CmdItem[] = [
    // AI Commands — these are AI-native actions, not just navigation
    {
      id: "ai-build",
      label: "Build an app with AI",
      sub: "Describe what you want — FLOW generates architecture, pages, and code",
      icon: I.sparkle(), badge: "AI", group: "ai",
      action: () => buildAndGo(),
      kbd: "B",
    },
    {
      id: "ai-agent",
      label: "Create an AI agent",
      sub: "Deploy an autonomous agent to run tasks on your behalf",
      icon: I.agent(), badge: "AI", group: "ai",
      action: () => go("agentos"),
    },
    {
      id: "ai-workflow",
      label: "Automate a workflow",
      sub: "Build trigger-action automations with human approval steps",
      icon: I.workflow(), badge: "AI", group: "ai",
      action: () => go("automation"),
    },
    {
      id: "ai-chat",
      label: "New AI conversation",
      sub: "Start a conversation with your AI assistants",
      icon: I.chat(), badge: "AI", group: "ai",
      action: () => go("ai"),
      kbd: "N",
    },
    {
      id: "ai-security",
      label: "Run security audit",
      sub: "Scan your apps for vulnerabilities and misconfigurations",
      icon: I.shield(), badge: "AI", group: "ai",
      action: () => go("observability"),
    },
    {
      id: "ai-crm",
      label: "Build a CRM",
      sub: "Generate a CRM with contacts, deals and pipeline — AI builds it",
      icon: I.zap(), badge: "Template", group: "ai",
      action: () => buildAndGo("Build a CRM for my sales team with contacts, deals, pipeline and email integration"),
    },
    {
      id: "ai-saas",
      label: "Build a SaaS app",
      sub: "Full-stack SaaS with auth, billing, teams and dashboard",
      icon: I.zap(), badge: "Template", group: "ai",
      action: () => buildAndGo("Build an AI customer support SaaS with authentication, dashboard, tickets, AI agent and Stripe billing"),
    },

    // Quick Actions
    {
      id: "find-runs",
      label: "Find failed runs",
      sub: "View execution history and diagnose failures",
      icon: I.runs(), group: "action",
      action: () => go("runs"),
    },
    {
      id: "open-monitoring",
      label: "Open monitoring",
      sub: "Error rate, latency, throughput and AI cost",
      icon: I.monitor(), group: "action",
      action: () => go("observability"),
    },
    {
      id: "open-logs",
      label: "View logs",
      sub: "Execution logs and debug output",
      icon: I.terminal(), group: "action",
      action: () => go("sandbox"),
    },
    {
      id: "deploy",
      label: "Deploy project",
      sub: "Run build → test → security → deploy pipeline",
      icon: I.deploy(), group: "action",
      action: () => go("app-builder"),
    },

    // Navigate
    { id: "home",         label: "Command Center",  sub: "KPIs · agents · workflows · activity",  icon: Icons.home(),          group: "navigate", action: () => go("home") },
    { id: "app-builder",  label: "App Builder",      sub: "AI Software Factory",                   icon: Icons["app-builder"](), group: "navigate", action: () => go("app-builder") },
    { id: "design",       label: "Design Studio",    sub: "Visual canvas & UI editor",             icon: Icons.design(),         group: "navigate", action: () => go("design") },
    { id: "agentos",      label: "Agents",           sub: "Deploy and manage AI agents",           icon: Icons.agentos(),        group: "navigate", action: () => go("agentos") },
    { id: "automation",   label: "Workflows",        sub: "Triggers · conditions · automation",    icon: Icons.automation(),     group: "navigate", action: () => go("automation") },
    { id: "runs",         label: "Runs",             sub: "Execution center · logs · costs",       icon: Icons.runs(),           group: "navigate", action: () => go("runs") },
    { id: "ai",           label: "Conversations",    sub: "Chat with AI assistants",               icon: Icons.ai(),             group: "navigate", action: () => go("ai") },

    // Platform
    { id: "ai-routing",    label: "AI Gateway",      sub: "Models · providers · budgets",         icon: Icons.api(),            group: "platform", action: () => go("ai-routing") },
    { id: "integrations",  label: "Integrations",    sub: "Connect your tools",                   icon: Icons.integrations(),   group: "platform", action: () => go("integrations") },
    { id: "observability", label: "Monitoring",      sub: "Metrics · alerts · observability",     icon: Icons.data(),           group: "platform", action: () => go("observability") },
    { id: "plugins",       label: "Packages",        sub: "Extensions and plugins",               icon: Icons.plugins(),        group: "platform", action: () => go("plugins") },
    { id: "marketplace",   label: "Marketplace",     sub: "Templates and components",             icon: Icons.templates(),      group: "platform", action: () => go("marketplace") },
    { id: "organizations", label: "Organizations",   sub: "Org management",                       icon: Icons.organizations(),  group: "platform", action: () => go("organizations") },
    { id: "settings",      label: "Settings",        sub: "System & app configuration",           icon: Icons.settings(),       group: "platform", action: () => go("settings") },
  ];

  const filtered = q.trim()
    ? items.filter(i =>
        i.label.toLowerCase().includes(q.toLowerCase()) ||
        i.sub?.toLowerCase().includes(q.toLowerCase()) ||
        i.group === "ai" // AI commands always shown when there's a query
          ? i.label.toLowerCase().includes(q.toLowerCase()) || i.sub?.toLowerCase().includes(q.toLowerCase())
          : i.label.toLowerCase().includes(q.toLowerCase()) || i.sub?.toLowerCase().includes(q.toLowerCase())
      )
    : items;

  function run(item: CmdItem) { item.action(); onClose(); }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown")  { e.preventDefault(); setActive(a => Math.min(a + 1, filtered.length - 1)); }
    if (e.key === "ArrowUp")    { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
    if (e.key === "Enter")      { e.preventDefault(); if (filtered[active]) run(filtered[active]); }
    if (e.key === "Escape")     { onClose(); }
  }

  // Group items preserving order
  const groupOrder: CmdItem["group"][] = ["ai", "action", "navigate", "platform"];
  const grouped = groupOrder
    .map(g => ({ group: g, items: filtered.filter(i => i.group === g) }))
    .filter(g => g.items.length > 0);

  let globalIdx = 0;

  return (
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
    <div className="cmd-overlay" onClick={onClose}>
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
      <div className="cmd-modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 600 }}>

        {/* Search input */}
        <div className="cmd-header">
          <span className="cmd-icon"><I.search /></span>
          <input
            ref={inputRef}
            className="cmd-input"
            value={q}
            onChange={e => { setQ(e.target.value); setActive(0); }}
            onKeyDown={onKey}
            placeholder="Search or type a command…"
          />
          {q && (
            <button
              onClick={() => setQ("")}
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t5)", padding: "0 4px", fontSize: 16, lineHeight: 1, display: "flex", alignItems: "center" }}
            >×</button>
          )}
          <span className="cmd-kbd">ESC</span>
        </div>

        {/* AI hint banner (shown only when no query yet) */}
        {!q && (
          <div style={{ padding: "8px 16px 4px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", gap: 8 }}>
            <I.sparkle />
            <span style={{ fontSize: 11, color: "var(--t4)", fontWeight: 500 }}>
              Type anything — FLOW can build apps, run agents, create workflows, and more
            </span>
          </div>
        )}

        {/* Results */}
        <div className="cmd-list">
          {filtered.length === 0 && (
            <div style={{ padding: "24px", textAlign: "center" }}>
              <div style={{ fontSize: 13, color: "var(--t4)", marginBottom: 8 }}>No results for "{q}"</div>
              <div style={{ fontSize: 11, color: "var(--t5)" }}>Try "build", "agent", "workflow", or a page name</div>
            </div>
          )}

          {grouped.map(({ group, items: groupItems }) => (
            <div key={group}>
              <div style={{ padding: "8px 16px 4px", fontSize: 10, fontWeight: 700, color: "var(--t5)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {GROUP_LABELS[group]}
              </div>
              {groupItems.map(item => {
                const myIdx = globalIdx++;
                const isActive = myIdx === active;
                return (
                  <div
                    key={item.id}
                    className={`cmd-item${isActive ? " active" : ""}`}
                    role="button" tabIndex={0}
                    onClick={() => run(item)}
                    onMouseEnter={() => setActive(myIdx)}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); run(item); } }}
                  >
                    <div className="cmd-item-icon" style={{ color: group === "ai" ? "var(--accent)" : undefined }}>
                      {item.icon}
                    </div>
                    <div className="cmd-item-label">
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        {item.label}
                        {item.badge && (
                          <span style={{
                            fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 4,
                            background: group === "ai" ? "var(--accent-dim)" : "var(--bg-card)",
                            color: group === "ai" ? "var(--accent)" : "var(--t4)",
                            textTransform: "uppercase", letterSpacing: "0.06em",
                          }}>
                            {item.badge}
                          </span>
                        )}
                      </div>
                      {item.sub && <div className="cmd-item-sub">{item.sub}</div>}
                    </div>
                    {item.kbd && <span className="cmd-item-kbd">{item.kbd}</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="cmd-footer">
          <span><span className="cmd-kbd">↑↓</span> navigate</span>
          <span><span className="cmd-kbd">↵</span> open</span>
          <span><span className="cmd-kbd">ESC</span> close</span>
        </div>
      </div>
    </div>
  );
}
