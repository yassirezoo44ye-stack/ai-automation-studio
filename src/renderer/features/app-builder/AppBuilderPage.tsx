/**
 * App Builder — 3-panel workspace for building apps with AI.
 *
 * Layout:
 *   ┌──────────────┬──────────────────────────────┬───────────────┐
 *   │  App Sidebar │        Live Preview           │  AI Builder   │
 *   │  (nav)       │        (iframe sim)           │  (chat)       │
 *   └──────────────┴──────────────────────────────┴───────────────┘
 *
 * Top bar: Build | Plan | Debug  +  Preview | Share | Publish
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { useAppContext } from "../../contexts/app";
import { apiFetch, parseJSON } from "../../utils/api";
import { useToast } from "../../contexts/toast";
import type { Project } from "../../types";

/* ── Types ──────────────────────────────────────────────────────── */
type BuildMode  = "build" | "plan" | "debug";
type AppSection = "overview" | "pages" | "data" | "workflows" | "agents" | "integrations" | "settings";
type BuildPhase = { label: string; status: "pending" | "running" | "done" | "error" };

const SECTIONS: { id: AppSection; label: string; icon: React.ReactNode }[] = [
  { id: "overview",     label: "Overview",     icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg> },
  { id: "pages",        label: "Pages",        icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> },
  { id: "data",         label: "Data",         icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg> },
  { id: "workflows",    label: "Workflows",    icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><line x1="7" y1="6" x2="17" y2="6"/><line x1="5" y1="8" x2="12" y2="16"/><line x1="19" y1="8" x2="12" y2="16"/></svg> },
  { id: "agents",       label: "Agents",       icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3"/></svg> },
  { id: "integrations", label: "Integrations", icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg> },
  { id: "settings",     label: "Settings",     icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06"/></svg> },
];

/* ── Build phases ────────────────────────────────────────────────── */
const INITIAL_PHASES: BuildPhase[] = [
  { label: "Understanding requirements", status: "pending" },
  { label: "Designing database schema",  status: "pending" },
  { label: "Creating pages & UI",        status: "pending" },
  { label: "Setting up backend logic",   status: "pending" },
  { label: "Configuring permissions",    status: "pending" },
  { label: "Creating automations",       status: "pending" },
  { label: "Running tests",              status: "pending" },
];

/* ── AI chat message ─────────────────────────────────────────────── */
type ChatMsg = { role: "user" | "assistant"; content: string };

/* ══════════════════════════════════════════════════════════════════
   Sub-components
   ══════════════════════════════════════════════════════════════════ */

/** Left panel — app structure navigation */
function AppSidebar({ section, setSection, projectName }: {
  section: AppSection;
  setSection: (s: AppSection) => void;
  projectName: string;
}) {
  return (
    <div style={{
      width: 200, flexShrink: 0,
      background: "var(--bg-surface)",
      borderRight: "1px solid var(--b1)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* App identity */}
      <div style={{ padding: "14px 16px 10px", borderBottom: "1px solid var(--b1)" }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {projectName || "Untitled App"}
        </div>
        <div style={{ fontSize: 11, color: "var(--green)", marginTop: 2, display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--green)", display: "inline-block" }} />
          Live
        </div>
      </div>

      {/* Section nav */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {SECTIONS.map(s => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            style={{
              width: "100%", display: "flex", alignItems: "center", gap: 10,
              padding: "9px 16px", border: "none", cursor: "pointer",
              background: section === s.id ? "var(--accent-dim)" : "transparent",
              color: section === s.id ? "var(--accent)" : "var(--t3)",
              fontSize: 13, fontWeight: section === s.id ? 600 : 400,
              borderInlineStart: section === s.id ? "2px solid var(--accent)" : "2px solid transparent",
              textAlign: "start",
              transition: "all 0.12s",
            }}
          >
            <span style={{ flexShrink: 0, opacity: section === s.id ? 1 : 0.7 }}>{s.icon}</span>
            {s.label}
          </button>
        ))}
      </nav>

      {/* Publish button */}
      <div style={{ padding: 12, borderTop: "1px solid var(--b1)" }}>
        <button style={{
          width: "100%", padding: "9px", borderRadius: 10, border: "none",
          background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
          color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer",
        }}>
          🚀 Publish
        </button>
      </div>
    </div>
  );
}

/** Center panel — live preview */
function PreviewPanel({ section, projectName, isBuilding, buildDone }: {
  section: AppSection;
  projectName: string;
  isBuilding: boolean;
  buildDone: boolean;
}) {
  const previewContent: Record<AppSection, React.ReactNode> = {
    overview: (
      <div style={{ padding: 28, height: "100%", overflowY: "auto" }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", marginBottom: 6 }}>{projectName || "Your App"}</h2>
        <p style={{ fontSize: 13, color: "var(--t4)", marginBottom: 24 }}>Your AI-built application is ready to customize.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
          {[["6", "Tables"], ["8", "Pages"], ["3", "User Roles"], ["4", "Workflows"], ["2", "Integrations"], ["12", "AI Features"]].map(([n, l]) => (
            <div key={l} style={{ background: "var(--bg-card)", border: "1px solid var(--b1)", borderRadius: 12, padding: "16px", textAlign: "center" }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: "var(--accent)" }}>{n}</div>
              <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 4 }}>{l}</div>
            </div>
          ))}
        </div>
      </div>
    ),
    pages: (
      <div style={{ padding: 28, overflowY: "auto" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 16 }}>Application Pages</div>
        {["Dashboard", "Contacts", "Deals", "Tasks", "Reports", "Settings", "Admin Panel", "Login"].map((p, i) => (
          <div key={p} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8, marginBottom: 4, background: i === 0 ? "var(--accent-dim)" : "var(--bg-card)", border: `1px solid ${i === 0 ? "var(--accent-border)" : "var(--b1)"}` }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={i === 0 ? "var(--accent)" : "var(--t4)"} strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span style={{ fontSize: 13, fontWeight: 500, color: i === 0 ? "var(--accent)" : "var(--t1)" }}>{p}</span>
            {i === 0 && <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 99, background: "var(--accent)", color: "white", marginLeft: "auto" }}>Active</span>}
          </div>
        ))}
      </div>
    ),
    data: (
      <div style={{ padding: 28, overflowY: "auto" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 16 }}>Data Tables</div>
        {[
          { name: "Contacts", fields: 12, records: 0 },
          { name: "Deals", fields: 8, records: 0 },
          { name: "Tasks", fields: 6, records: 0 },
          { name: "Companies", fields: 10, records: 0 },
          { name: "Activities", fields: 7, records: 0 },
          { name: "Users", fields: 9, records: 1 },
        ].map(t => (
          <div key={t.name} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 12px", borderRadius: 8, marginBottom: 4, background: "var(--bg-card)", border: "1px solid var(--b1)" }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--t1)", flex: 1 }}>{t.name}</span>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>{t.fields} fields</span>
            <span style={{ fontSize: 11, color: "var(--t5)" }}>{t.records} rows</span>
          </div>
        ))}
      </div>
    ),
    workflows: (
      <div style={{ padding: 28, overflowY: "auto" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 16 }}>Automations</div>
        {[
          { name: "New Lead Welcome", trigger: "Contact Created", status: "active" },
          { name: "Deal Follow-up", trigger: "7 days inactive", status: "active" },
          { name: "Task Reminder", trigger: "Due date - 1 day", status: "active" },
          { name: "Report Generator", trigger: "Every Monday", status: "paused" },
        ].map(w => (
          <div key={w.name} style={{ padding: "12px 14px", borderRadius: 10, marginBottom: 8, background: "var(--bg-card)", border: "1px solid var(--b1)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{w.name}</span>
              <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 99, background: w.status === "active" ? "var(--green-dim)" : "var(--bg-card)", color: w.status === "active" ? "var(--green)" : "var(--t4)", border: `1px solid ${w.status === "active" ? "rgba(22,163,74,0.2)" : "var(--b1)"}` }}>
                {w.status}
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--t4)" }}>⚡ {w.trigger}</div>
          </div>
        ))}
      </div>
    ),
    agents: (
      <div style={{ padding: 28, overflowY: "auto" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 16 }}>AI Agents</div>
        {[
          { name: "Sales Agent", purpose: "Qualifies leads & creates follow-ups", status: "active" },
          { name: "Data Analyst", purpose: "Generates reports & insights", status: "active" },
          { name: "Support Bot", purpose: "Handles customer inquiries", status: "idle" },
        ].map(a => (
          <div key={a.name} style={{ padding: "14px 16px", borderRadius: 12, marginBottom: 10, background: "var(--bg-card)", border: `1px solid ${a.status === "active" ? "var(--accent-border)" : "var(--b1)"}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: a.status === "active" ? "var(--green)" : "var(--t4)" }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)" }}>{a.name}</span>
              <span style={{ fontSize: 10, color: "var(--t4)", textTransform: "capitalize", marginLeft: "auto" }}>{a.status}</span>
            </div>
            <p style={{ fontSize: 11, color: "var(--t4)", margin: 0 }}>{a.purpose}</p>
          </div>
        ))}
      </div>
    ),
    integrations: (
      <div style={{ padding: 28, overflowY: "auto" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 16 }}>Connected Integrations</div>
        {[
          { name: "Gmail", connected: true },
          { name: "Slack", connected: true },
          { name: "Google Sheets", connected: false },
          { name: "Stripe", connected: false },
        ].map(i => (
          <div key={i.name} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8, marginBottom: 4, background: "var(--bg-card)", border: "1px solid var(--b1)" }}>
            <div style={{ width: 28, height: 28, borderRadius: 7, background: i.connected ? "var(--green-dim)" : "var(--bg-base)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>
              {i.name === "Gmail" ? "✉" : i.name === "Slack" ? "💬" : i.name === "Google Sheets" ? "📊" : "💳"}
            </div>
            <span style={{ fontSize: 13, flex: 1, color: "var(--t1)" }}>{i.name}</span>
            <span style={{ fontSize: 11, color: i.connected ? "var(--green)" : "var(--t4)" }}>{i.connected ? "Connected" : "Not connected"}</span>
          </div>
        ))}
      </div>
    ),
    settings: (
      <div style={{ padding: 28, overflowY: "auto" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 16 }}>App Settings</div>
        {[["App Name", "My App", "text"], ["Description", "AI-powered business app", "text"], ["Environment", "Production", "select"], ["Custom Domain", "—", "text"]].map(([label, val]) => (
          <div key={label} style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.05em", display: "block", marginBottom: 6 }}>{label}</label>
            <input defaultValue={val} style={{ width: "100%", padding: "9px 12px", borderRadius: 8, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", fontSize: 13, boxSizing: "border-box", outline: "none" }} />
          </div>
        ))}
      </div>
    ),
  };

  if (isBuilding) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-base)" }}>
        <div style={{ textAlign: "center", maxWidth: 360 }}>
          <div style={{ fontSize: 32, marginBottom: 16 }}>⚡</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)", marginBottom: 8 }}>AI is building your app…</div>
          <div style={{ fontSize: 13, color: "var(--t4)", marginBottom: 24 }}>This takes about 30 seconds. Sit back and relax.</div>
          <div style={{ width: "100%", height: 4, borderRadius: 99, background: "var(--bg-card)", overflow: "hidden" }}>
            <div style={{
              height: "100%", borderRadius: 99,
              background: "linear-gradient(90deg, var(--accent) 0%, var(--teal) 100%)",
              animation: "shimmer 1.5s ease-in-out infinite",
            }} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, background: "var(--bg-base)", overflow: "hidden", position: "relative" }}>
      {/* Browser chrome simulation */}
      <div style={{ background: "var(--bg-surface)", borderBottom: "1px solid var(--b1)", padding: "8px 12px", display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ display: "flex", gap: 5 }}>
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#FF5F57" }} />
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#FEBC2E" }} />
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#28C840" }} />
        </div>
        <div style={{ flex: 1, background: "var(--bg-card)", borderRadius: 6, padding: "4px 10px", fontSize: 11, color: "var(--t4)", display: "flex", alignItems: "center", gap: 6 }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          app.flow.ai/{(projectName || "my-app").toLowerCase().replace(/\s+/g, "-")}
        </div>
      </div>
      {/* App preview */}
      <div style={{ height: "calc(100% - 41px)", overflow: "hidden" }}>
        {buildDone || !isBuilding ? previewContent[section] : (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--t4)", fontSize: 14 }}>
            Type a prompt to start building your app
          </div>
        )}
      </div>
    </div>
  );
}

/** Right panel — AI builder chat */
function AIBuilderPanel({ onBuild, projectName }: {
  onBuild: (prompt: string) => void;
  projectName: string;
}) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput]       = useState("");
  const [loading, setLoading]   = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  // Load initial prompt from Dashboard
  useEffect(() => {
    const stored = sessionStorage.getItem("flow_builder_prompt");
    if (stored) {
      sessionStorage.removeItem("flow_builder_prompt");
      setInput(stored);
    }
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const val = input.trim();
    if (!val || loading) return;
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: val }]);
    setLoading(true);

    // Kick off build if first message
    if (messages.length === 0) {
      onBuild(val);
    }

    try {
      // Try AI backend
      const r = await apiFetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: val, context: "app_builder", app_name: projectName }),
      });
      if (r.ok) {
        const data = await parseJSON<{ response: string }>(r, "/api/ai/chat");
        setMessages(prev => [...prev, { role: "assistant", content: data.response }]);
      } else {
        // Fallback response
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `I'm designing ${val.length > 40 ? "your app" : `"${val}"`} now. I'll create the database schema, pages, and automations based on your requirements. You can see the preview updating in real-time.`,
        }]);
      }
    } catch {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: "I'm building your app now. Check the preview panel to see progress.",
      }]);
    }
    setLoading(false);
  }, [input, loading, messages, onBuild, projectName]);

  return (
    <div style={{
      width: 320, flexShrink: 0,
      borderLeft: "1px solid var(--b1)",
      background: "var(--bg-surface)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 8,
          background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)" }}>AI Builder</div>
          <div style={{ fontSize: 10, color: "var(--green)", display: "flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--green)", display: "inline-block" }} />
            Ready
          </div>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", padding: "24px 8px" }}>
            <div style={{ fontSize: 13, color: "var(--t4)", lineHeight: 1.6, marginBottom: 16 }}>
              Describe what you want to build. I'll create the full application for you.
            </div>
            {/* Suggestions */}
            {[
              "Build a CRM for sales",
              "Create inventory system",
              "Make a help desk app",
            ].map(s => (
              <button
                key={s}
                onClick={() => setInput(s)}
                style={{
                  width: "100%", textAlign: "left", padding: "9px 12px",
                  borderRadius: 10, border: "1px solid var(--b1)",
                  background: "var(--bg-card)", color: "var(--t2)",
                  fontSize: 12, cursor: "pointer", marginBottom: 6,
                  transition: "border-color 0.12s",
                }}
                onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--accent)")}
                onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--b1)")}
              >
                "{s}"
              </button>
            ))}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            {msg.role === "user" ? (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{
                  maxWidth: "85%", padding: "10px 12px",
                  borderRadius: "12px 12px 4px 12px",
                  background: "var(--accent)", color: "white",
                  fontSize: 13, lineHeight: 1.5,
                }}>
                  {msg.content}
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <div style={{
                  width: 24, height: 24, borderRadius: 7, flexShrink: 0,
                  background: "linear-gradient(135deg, var(--accent), var(--teal))",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                </div>
                <div style={{
                  maxWidth: "85%", padding: "10px 12px",
                  borderRadius: "12px 12px 12px 4px",
                  background: "var(--bg-card)", border: "1px solid var(--b1)",
                  fontSize: 13, color: "var(--t1)", lineHeight: 1.6,
                }}>
                  {msg.content}
                </div>
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "8px 0" }}>
            <div style={{
              width: 24, height: 24, borderRadius: 7,
              background: "linear-gradient(135deg, var(--accent), var(--teal))",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            </div>
            <div style={{ display: "flex", gap: 4, paddingInlineStart: 2 }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: "var(--accent)",
                  animation: `bounce 1s ease-in-out ${i * 0.15}s infinite`,
                }} />
              ))}
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "12px", borderTop: "1px solid var(--b1)" }}>
        <div style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Describe a change…"
            rows={2}
            style={{
              flex: 1, padding: "9px 12px", fontSize: 13,
              borderRadius: 10, border: "1px solid var(--b1)",
              background: "var(--bg-card)", color: "var(--t1)",
              resize: "none", outline: "none", fontFamily: "inherit",
            }}
            onFocus={e => (e.target.style.borderColor = "var(--accent)")}
            onBlur={e => (e.target.style.borderColor = "var(--b1)")}
          />
          <button
            onClick={send}
            disabled={!input.trim() || loading}
            style={{
              width: 36, height: 36, borderRadius: 9, border: "none",
              background: input.trim() && !loading ? "var(--accent)" : "var(--bg-card)",
              color: input.trim() && !loading ? "white" : "var(--t5)",
              cursor: input.trim() && !loading ? "pointer" : "default",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              transition: "all 0.12s",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Build phases overlay ─────────────────────────────────────────── */
function BuildingOverlay({ phases }: { phases: BuildPhase[] }) {
  return (
    <div style={{
      position: "absolute", inset: 0,
      background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 10,
    }}>
      <div style={{
        background: "var(--bg-surface)", borderRadius: 24, padding: "32px 36px",
        maxWidth: 400, width: "100%", boxShadow: "var(--shadow-xl)",
      }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <div style={{ fontSize: 28, marginBottom: 10 }}>⚡</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)" }}>Building your app with AI</div>
          <div style={{ fontSize: 13, color: "var(--t4)", marginTop: 6 }}>Sit back, this takes about 30 seconds</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {phases.map((phase, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 22, height: 22, borderRadius: 99, flexShrink: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: phase.status === "done" ? "var(--green-dim)" : phase.status === "running" ? "var(--accent-dim)" : "var(--bg-card)",
                border: `1px solid ${phase.status === "done" ? "rgba(22,163,74,0.2)" : phase.status === "running" ? "var(--accent-border)" : "var(--b1)"}`,
              }}>
                {phase.status === "done" && (
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                )}
                {phase.status === "running" && (
                  <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--accent)", animation: "pulse 1s ease-in-out infinite" }} />
                )}
                {phase.status === "pending" && (
                  <div style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--t5)" }} />
                )}
              </div>
              <span style={{
                fontSize: 13, fontWeight: phase.status === "running" ? 600 : 400,
                color: phase.status === "pending" ? "var(--t4)" : phase.status === "done" ? "var(--t2)" : "var(--t1)",
              }}>
                {phase.label}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════
   Main AppBuilderPage
   ══════════════════════════════════════════════════════════════════ */
export function AppBuilderPage() {
  const { setPage } = useAppContext();
  const toast = useToast();

  const [mode, setMode]       = useState<BuildMode>("build");
  const [section, setSection] = useState<AppSection>("overview");
  const [isBuilding, setIsBuilding] = useState(false);
  const [buildDone, setBuildDone]   = useState(false);
  const [phases, setPhases]         = useState<BuildPhase[]>(INITIAL_PHASES);
  const [projectName, setProjectName] = useState("");

  // Load active project info
  useEffect(() => {
    const pid = sessionStorage.getItem("flow_active_project");
    if (pid) {
      apiFetch(`/api/projects/${pid}`).then(r => r.json()).then((data: Partial<Project>) => {
        if (data.name) setProjectName(data.name);
      }).catch(() => {});
    }
  }, []);

  const handleBuild = useCallback(async (prompt: string) => {
    setIsBuilding(true);
    setBuildDone(false);

    // Animate phases
    const newPhases = [...INITIAL_PHASES];
    for (let i = 0; i < newPhases.length; i++) {
      await new Promise(r => setTimeout(r, 800 + Math.random() * 600));
      newPhases[i] = { ...newPhases[i], status: "running" };
      setPhases([...newPhases]);
      await new Promise(r => setTimeout(r, 1200 + Math.random() * 800));
      newPhases[i] = { ...newPhases[i], status: "done" };
      setPhases([...newPhases]);
    }

    // Create project in backend
    try {
      const name = prompt.split(" ").slice(0, 4).join(" ").replace(/^build a?n?\s*/i, "").trim() || "New App";
      const r = await apiFetch("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.charAt(0).toUpperCase() + name.slice(1), description: prompt }),
      });
      if (r.ok) {
        const data = await r.json() as Partial<Project>;
        if (data.name) setProjectName(data.name);
        toast("Your app is ready!", "ok");
      }
    } catch { /* best-effort */ }

    setIsBuilding(false);
    setBuildDone(true);
  }, [toast]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* ── Top bar ──────────────────────────────────────────── */}
      <div style={{
        height: 48, minHeight: 48,
        borderBottom: "1px solid var(--b1)",
        background: "var(--bg-surface)",
        display: "flex", alignItems: "center",
        padding: "0 16px", gap: 8, flexShrink: 0,
      }}>
        {/* Back */}
        <button
          onClick={() => setPage("home")}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"/></svg>
          Apps
        </button>
        <div style={{ width: 1, height: 16, background: "var(--b1)" }} />

        {/* Mode tabs */}
        <div style={{ display: "flex", background: "var(--bg-card)", borderRadius: 8, padding: 3, gap: 2 }}>
          {(["build", "plan", "debug"] as BuildMode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                padding: "4px 12px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
                background: mode === m ? "var(--bg-surface)" : "transparent",
                color: mode === m ? "var(--t1)" : "var(--t4)",
                boxShadow: mode === m ? "var(--shadow-xs)" : "none",
                textTransform: "capitalize",
                transition: "all 0.12s",
              }}
            >
              {m}
            </button>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        {/* App name */}
        {projectName && (
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t2)" }}>{projectName}</div>
        )}

        {/* Action buttons */}
        <button style={{
          padding: "6px 14px", borderRadius: 8, border: "1px solid var(--b1)",
          background: "transparent", color: "var(--t2)", fontSize: 12, fontWeight: 500, cursor: "pointer",
        }}>
          Preview
        </button>
        <button style={{
          padding: "6px 14px", borderRadius: 8, border: "1px solid var(--b1)",
          background: "transparent", color: "var(--t2)", fontSize: 12, fontWeight: 500, cursor: "pointer",
        }}>
          Share
        </button>
        <button style={{
          padding: "6px 14px", borderRadius: 8, border: "none",
          background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
          color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer",
          boxShadow: "var(--shadow-btn)",
        }}>
          🚀 Publish
        </button>
      </div>

      {/* ── 3-panel workspace ─────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", position: "relative" }}>
        <AppSidebar section={section} setSection={setSection} projectName={projectName} />
        <PreviewPanel section={section} projectName={projectName} isBuilding={isBuilding} buildDone={buildDone} />
        <AIBuilderPanel onBuild={handleBuild} projectName={projectName} />

        {/* Build overlay */}
        {isBuilding && <BuildingOverlay phases={phases} />}
      </div>

      {/* Build done banner */}
      {buildDone && (
        <div style={{
          position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
          background: "var(--bg-surface)", border: "1px solid var(--green)",
          borderRadius: 16, padding: "16px 24px",
          boxShadow: "var(--shadow-xl)", display: "flex", alignItems: "center", gap: 16,
          zIndex: 100,
          animation: "slideUp 0.3s ease",
        }}>
          <div style={{ color: "var(--green)", fontSize: 20 }}>✓</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>Your app is ready!</div>
            <div style={{ fontSize: 12, color: "var(--t4)" }}>6 tables · 8 pages · 3 roles · 4 automations</div>
          </div>
          <div style={{ display: "flex", gap: 8, marginLeft: 8 }}>
            <button style={{
              padding: "7px 14px", borderRadius: 8, border: "1px solid var(--b1)",
              background: "transparent", color: "var(--t2)", fontSize: 12, cursor: "pointer",
            }} onClick={() => setBuildDone(false)}>
              Dismiss
            </button>
            <button style={{
              padding: "7px 16px", borderRadius: 8, border: "none",
              background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
              color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}>
              🚀 Publish
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
