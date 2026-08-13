import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import { Icons } from "../../shared/icons";
import { useAsyncData } from "../../shared/hooks/useAsyncData";
import { apiFetch } from "../../shared/utils/apiFetch";

/* ─── Types ─────────────────────────────────────────────────── */
type IntegrationStatus = "connected" | "not_connected" | "error" | "configuring";
type IntegrationCategory = "all" | "productivity" | "communication" | "data" | "developer" | "payments";

interface Integration {
  id: string;
  name: string;
  description: string;
  icon: string; // SVG string or emoji fallback
  category: IntegrationCategory;
  status: IntegrationStatus;
  connectedAt?: string;
  usageCount?: number;
  docsUrl?: string;
}

/* ─── Static integration catalog ────────────────────────────── */
const INTEGRATION_CATALOG: Omit<Integration, "status">[] = [
  {
    id: "google-workspace",
    name: "Google Workspace",
    description: "Connect Docs, Sheets, Drive and Calendar to automate workflows",
    icon: "🔵",
    category: "productivity",
    usageCount: 0,
  },
  {
    id: "gmail",
    name: "Gmail",
    description: "Send emails, parse inboxes, and trigger automations from messages",
    icon: "📧",
    category: "communication",
    usageCount: 0,
  },
  {
    id: "slack",
    name: "Slack",
    description: "Post messages, read channels, and run agents from Slack commands",
    icon: "💬",
    category: "communication",
    usageCount: 0,
  },
  {
    id: "whatsapp",
    name: "WhatsApp Business",
    description: "Automate customer conversations and send notifications via WhatsApp",
    icon: "📱",
    category: "communication",
    usageCount: 0,
  },
  {
    id: "notion",
    name: "Notion",
    description: "Sync pages, databases, and blocks with your app's data layer",
    icon: "📝",
    category: "productivity",
    usageCount: 0,
  },
  {
    id: "google-sheets",
    name: "Google Sheets",
    description: "Read and write spreadsheet data, trigger automations on cell changes",
    icon: "📊",
    category: "productivity",
    usageCount: 0,
  },
  {
    id: "stripe",
    name: "Stripe",
    description: "Handle payments, subscriptions, invoices and billing workflows",
    icon: "💳",
    category: "payments",
    usageCount: 0,
  },
  {
    id: "github",
    name: "GitHub",
    description: "Trigger flows on commits, PRs, issues and automate code reviews",
    icon: "🐙",
    category: "developer",
    usageCount: 0,
  },
  {
    id: "rest-api",
    name: "REST API",
    description: "Connect any HTTP service using custom headers, auth, and payloads",
    icon: "🔌",
    category: "developer",
    usageCount: 0,
  },
  {
    id: "webhooks",
    name: "Webhooks",
    description: "Receive and send real-time events to any external service",
    icon: "⚡",
    category: "developer",
    usageCount: 0,
  },
  {
    id: "mcp",
    name: "MCP Servers",
    description: "Connect Model Context Protocol servers to extend AI agent capabilities",
    icon: "🤖",
    category: "developer",
    usageCount: 0,
  },
  {
    id: "airtable",
    name: "Airtable",
    description: "Sync records, trigger automations on field changes and table events",
    icon: "🗃️",
    category: "data",
    usageCount: 0,
  },
  {
    id: "postgres",
    name: "PostgreSQL",
    description: "Query, insert and watch your Postgres database from any workflow",
    icon: "🐘",
    category: "data",
    usageCount: 0,
  },
  {
    id: "supabase",
    name: "Supabase",
    description: "Real-time database triggers, auth hooks, and storage access",
    icon: "⚡",
    category: "data",
    usageCount: 0,
  },
  {
    id: "zapier",
    name: "Zapier",
    description: "Bridge Flow with 5,000+ apps using Zapier's automation network",
    icon: "⚙️",
    category: "productivity",
    usageCount: 0,
  },
  {
    id: "linear",
    name: "Linear",
    description: "Create issues, update cycles and sync project status automatically",
    icon: "📐",
    category: "developer",
    usageCount: 0,
  },
];

const CATEGORIES: { id: IntegrationCategory; label: string }[] = [
  { id: "all",          label: "All" },
  { id: "productivity", label: "Productivity" },
  { id: "communication",label: "Communication" },
  { id: "data",         label: "Data & Storage" },
  { id: "developer",    label: "Developer" },
  { id: "payments",     label: "Payments" },
];

/* ─── Status pill ────────────────────────────────────────────── */
function StatusPill({ status }: { status: IntegrationStatus }) {
  const cfg: Record<IntegrationStatus, { label: string; color: string }> = {
    connected:     { label: "Connected",     color: "var(--teal)" },
    not_connected: { label: "Not Connected", color: "var(--text-muted)" },
    error:         { label: "Error",         color: "var(--error, #f87171)" },
    configuring:   { label: "Configuring…",  color: "var(--accent)" },
  };
  const { label, color } = cfg[status];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 11, fontWeight: 600, color,
      padding: "2px 8px", borderRadius: 20,
      background: `${color}18`,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: color,
        boxShadow: status === "connected" ? `0 0 6px ${color}` : "none",
      }} />
      {label}
    </span>
  );
}

/* ─── Configure modal ────────────────────────────────────────── */
function ConfigureModal({
  integration,
  onClose,
  onConnect,
}: {
  integration: Integration;
  onClose: () => void;
  onConnect: (id: string) => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [connecting, setConnecting] = useState(false);

  async function handleConnect() {
    setConnecting(true);
    // Simulate connection delay
    await new Promise(r => setTimeout(r, 1200));
    onConnect(integration.id);
    setConnecting(false);
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{
        position: "fixed", inset: 0, zIndex: 200,
        background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.93, opacity: 0, y: 12 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.93, opacity: 0, y: 12 }}
        transition={{ duration: 0.2 }}
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--b1)",
          borderRadius: 16, padding: 32,
          width: 480, maxWidth: "calc(100vw - 48px)",
          boxShadow: "0 24px 60px rgba(0,0,0,0.4)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 24 }}>
          <span style={{ fontSize: 36 }}>{integration.icon}</span>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)" }}>
              Connect {integration.name}
            </div>
            <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
              {integration.description}
            </div>
          </div>
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", display: "block", marginBottom: 6 }}>
            API Key / Secret
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder={`Enter your ${integration.name} API key`}
            style={{
              width: "100%", padding: "10px 14px", borderRadius: 8,
              border: "1px solid var(--b1)", background: "var(--bg-secondary)",
              color: "var(--text-primary)", fontSize: 14,
              boxSizing: "border-box",
              outline: "none",
            }}
            onFocus={e => (e.target.style.borderColor = "var(--accent)")}
            onBlur={e => (e.target.style.borderColor = "var(--b1)")}
          />
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button
            onClick={onClose}
            style={{
              padding: "9px 18px", borderRadius: 8, border: "1px solid var(--b1)",
              background: "transparent", color: "var(--text-secondary)", fontSize: 14,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleConnect}
            disabled={!apiKey.trim() || connecting}
            style={{
              padding: "9px 20px", borderRadius: 8, border: "none",
              background: "var(--accent)", color: "#fff", fontSize: 14,
              fontWeight: 600, cursor: apiKey.trim() ? "pointer" : "not-allowed",
              opacity: apiKey.trim() ? 1 : 0.5,
              display: "flex", alignItems: "center", gap: 8,
            }}
          >
            {connecting ? (
              <>
                <span style={{
                  width: 14, height: 14, border: "2px solid rgba(255,255,255,0.3)",
                  borderTopColor: "#fff", borderRadius: "50%",
                  animation: "spin 0.7s linear infinite",
                  display: "inline-block",
                }} />
                Connecting…
              </>
            ) : "Connect"}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

/* ─── Integration card ───────────────────────────────────────── */
function IntegrationCard({
  integration,
  onConfigure,
  onDisconnect,
}: {
  integration: Integration;
  onConfigure: (i: Integration) => void;
  onDisconnect: (id: string) => void;
}) {
  const connected = integration.status === "connected";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      style={{
        background: "var(--bg-surface)",
        border: `1px solid ${connected ? "var(--teal)" : "var(--b1)"}`,
        borderRadius: 14,
        padding: 20,
        display: "flex", flexDirection: "column", gap: 12,
        transition: "border-color 0.2s, box-shadow 0.2s",
        boxShadow: connected ? "0 0 0 1px var(--teal), 0 4px 20px rgba(0,200,170,0.08)" : "none",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 28, lineHeight: 1 }}>{integration.icon}</span>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
              {integration.name}
            </div>
            <StatusPill status={integration.status} />
          </div>
        </div>
      </div>

      {/* Description */}
      <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: 0, lineHeight: 1.5 }}>
        {integration.description}
      </p>

      {/* Connected meta */}
      {connected && integration.connectedAt && (
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          Connected {integration.connectedAt}
          {integration.usageCount !== undefined && (
            <> · <strong>{integration.usageCount}</strong> uses</>
          )}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
        {connected ? (
          <>
            <button
              onClick={() => onConfigure(integration)}
              style={{
                flex: 1, padding: "8px 0", borderRadius: 8,
                border: "1px solid var(--b1)", background: "transparent",
                color: "var(--text-secondary)", fontSize: 13,
                cursor: "pointer", fontWeight: 500,
              }}
            >
              Configure
            </button>
            <button
              onClick={() => onDisconnect(integration.id)}
              style={{
                padding: "8px 14px", borderRadius: 8,
                border: "1px solid rgba(248,113,113,0.3)",
                background: "rgba(248,113,113,0.08)",
                color: "var(--error, #f87171)", fontSize: 13,
                cursor: "pointer", fontWeight: 500,
              }}
            >
              Disconnect
            </button>
          </>
        ) : (
          <button
            onClick={() => onConfigure(integration)}
            style={{
              flex: 1, padding: "9px 0", borderRadius: 8,
              border: "none", background: "var(--accent)",
              color: "#fff", fontSize: 13, fontWeight: 600,
              cursor: "pointer",
            }}
          >
            + Connect
          </button>
        )}
      </div>
    </motion.div>
  );
}

/* ─── Main page ──────────────────────────────────────────────── */
export function IntegrationsPage() {
  const { t } = useTranslation("common");
  const [activeCategory, setActiveCategory] = useState<IntegrationCategory>("all");
  const [search, setSearch] = useState("");
  const [configuring, setConfiguring] = useState<Integration | null>(null);

  // Overlay statuses on top of catalog (from API in real usage)
  const [statuses, setStatuses] = useState<Record<string, IntegrationStatus>>({});

  // Merge catalog + status map
  const integrations: Integration[] = INTEGRATION_CATALOG.map(i => ({
    ...i,
    status: statuses[i.id] ?? "not_connected",
    connectedAt: statuses[i.id] === "connected" ? "just now" : undefined,
    usageCount: statuses[i.id] === "connected" ? Math.floor(Math.random() * 40) : 0,
  }));

  const filtered = integrations.filter(i => {
    const catOk = activeCategory === "all" || i.category === activeCategory;
    const q = search.toLowerCase();
    const searchOk = !q || i.name.toLowerCase().includes(q) || i.description.toLowerCase().includes(q);
    return catOk && searchOk;
  });

  const connectedCount = integrations.filter(i => i.status === "connected").length;

  function handleConnect(id: string) {
    setStatuses(s => ({ ...s, [id]: "connected" }));
    setConfiguring(null);
  }

  function handleDisconnect(id: string) {
    setStatuses(s => ({ ...s, [id]: "not_connected" }));
  }

  return (
    <div style={{
      height: "100%", display: "flex", flexDirection: "column",
      overflow: "hidden", background: "var(--bg-primary)",
    }}>
      {/* ── Top bar ── */}
      <div style={{
        padding: "20px 28px", borderBottom: "1px solid var(--b1)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 16, flexShrink: 0,
      }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "var(--text-primary)" }}>
            Integrations
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-muted)" }}>
            {connectedCount} of {integrations.length} connected
          </p>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {/* Search */}
          <div style={{ position: "relative" }}>
            <span style={{
              position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)",
              color: "var(--text-muted)",
            }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
              </svg>
            </span>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search integrations…"
              style={{
                padding: "8px 12px 8px 32px", borderRadius: 8,
                border: "1px solid var(--b1)", background: "var(--bg-surface)",
                color: "var(--text-primary)", fontSize: 13, width: 220,
                outline: "none",
              }}
            />
          </div>

          <button
            onClick={() => setConfiguring({
              id: "custom",
              name: "Custom Connector",
              description: "Connect any REST API with custom auth, headers, and transforms",
              icon: "🔌",
              category: "developer",
              status: "not_connected",
            })}
            style={{
              padding: "8px 16px", borderRadius: 8,
              border: "1px solid var(--b1)", background: "var(--bg-surface)",
              color: "var(--text-secondary)", fontSize: 13,
              cursor: "pointer", fontWeight: 500,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            Add Custom
          </button>
        </div>
      </div>

      {/* ── Stats row ── */}
      <div style={{
        padding: "16px 28px",
        display: "flex", gap: 16,
        borderBottom: "1px solid var(--b1)", flexShrink: 0,
      }}>
        {[
          { label: "Connected",     value: connectedCount,                             color: "var(--teal)" },
          { label: "Available",     value: integrations.length - connectedCount,        color: "var(--text-muted)" },
          { label: "Total",         value: integrations.length,                        color: "var(--accent)" },
          { label: "Active Today",  value: Math.max(0, connectedCount - 1),            color: "var(--text-primary)" },
        ].map(s => (
          <div key={s.label} style={{
            background: "var(--bg-surface)", border: "1px solid var(--b1)",
            borderRadius: 10, padding: "10px 18px",
            display: "flex", flexDirection: "column", gap: 2, minWidth: 90,
          }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: s.color, lineHeight: 1 }}>
              {s.value}
            </span>
            <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 500 }}>
              {s.label}
            </span>
          </div>
        ))}
      </div>

      {/* ── Category tabs ── */}
      <div style={{
        padding: "12px 28px",
        display: "flex", gap: 6, flexShrink: 0,
        borderBottom: "1px solid var(--b1)",
        overflowX: "auto",
      }}>
        {CATEGORIES.map(cat => {
          const count = cat.id === "all"
            ? integrations.length
            : integrations.filter(i => i.category === cat.id).length;
          const active = activeCategory === cat.id;
          return (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              style={{
                padding: "6px 14px", borderRadius: 20,
                border: active ? "none" : "1px solid var(--b1)",
                background: active ? "var(--accent)" : "transparent",
                color: active ? "#fff" : "var(--text-secondary)",
                fontSize: 13, fontWeight: active ? 600 : 400,
                cursor: "pointer", whiteSpace: "nowrap",
                display: "flex", alignItems: "center", gap: 6,
              }}
            >
              {cat.label}
              <span style={{
                fontSize: 11, fontWeight: 600,
                background: active ? "rgba(255,255,255,0.25)" : "var(--bg-secondary)",
                padding: "1px 6px", borderRadius: 20,
                color: active ? "#fff" : "var(--text-muted)",
              }}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── Grid ── */}
      <div style={{
        flex: 1, overflowY: "auto", padding: "24px 28px",
      }}>
        {filtered.length === 0 ? (
          <div style={{
            textAlign: "center", color: "var(--text-muted)",
            padding: "60px 0",
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🔌</div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>No integrations found</div>
            <div style={{ fontSize: 13 }}>Try a different search or category</div>
          </div>
        ) : (
          <motion.div
            layout
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 16,
            }}
          >
            <AnimatePresence mode="popLayout">
              {filtered.map(integration => (
                <IntegrationCard
                  key={integration.id}
                  integration={integration}
                  onConfigure={setConfiguring}
                  onDisconnect={handleDisconnect}
                />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>

      {/* ── Configure modal ── */}
      <AnimatePresence>
        {configuring && (
          <ConfigureModal
            integration={configuring}
            onClose={() => setConfiguring(null)}
            onConnect={handleConnect}
          />
        )}
      </AnimatePresence>

      {/* Keyframe for spinner */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
