/**
 * IntegrationsPage — connect external services to Flow apps.
 * Data: typed adapters only (no backend endpoint yet).
 * RTL-first: all spacing/alignment uses logical CSS properties.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

/* ── Types ──────────────────────────────────────────────────────────────── */
interface ConnectedIntegration {
  id: string;
  name: string;
  category: string;
  icon: string;
  status: "connected" | "error" | "syncing";
  lastSync: string;
  events: number;
}

interface AvailableIntegration {
  id: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  popular?: boolean;
}

/* ── Static data (typed adapter — endpoint TBD) ─────────────────────────── */
const CONNECTED: ConnectedIntegration[] = [
  { id: "stripe",   name: "Stripe",   category: "Payments",  icon: "💳", status: "connected", lastSync: "2m ago",  events: 1240 },
  { id: "slack",    name: "Slack",    category: "Messaging", icon: "💬", status: "connected", lastSync: "5m ago",  events: 863  },
  { id: "hubspot",  name: "HubSpot",  category: "CRM",       icon: "🧡", status: "syncing",   lastSync: "now",     events: 5021 },
  { id: "github",   name: "GitHub",   category: "Dev Tools", icon: "🐙", status: "connected", lastSync: "12m ago", events: 302  },
  { id: "sendgrid", name: "SendGrid", category: "Email",     icon: "📧", status: "error",     lastSync: "1h ago",  events: 0    },
];

const AVAILABLE: AvailableIntegration[] = [
  { id: "salesforce", name: "Salesforce",   category: "CRM",        icon: "☁️",  description: "Sync contacts and opportunities", popular: true  },
  { id: "twilio",     name: "Twilio",       category: "SMS",        icon: "📱",  description: "Send SMS and WhatsApp messages"                  },
  { id: "zapier",     name: "Zapier",       category: "Automation", icon: "⚡",  description: "Connect 5000+ apps",             popular: true  },
  { id: "notion",     name: "Notion",       category: "Docs",       icon: "📄",  description: "Sync pages and databases"                        },
  { id: "jira",       name: "Jira",         category: "Dev Tools",  icon: "🔵",  description: "Track issues and sprints"                        },
  { id: "intercom",   name: "Intercom",     category: "Support",    icon: "💬",  description: "Customer messaging and support"                  },
  { id: "shopify",    name: "Shopify",      category: "E-commerce", icon: "🛒",  description: "Sync orders and products",       popular: true  },
  { id: "airtable",   name: "Airtable",     category: "Database",   icon: "📊",  description: "Connect your Airtable bases"                     },
];

const CATEGORIES = ["All", "CRM", "Payments", "Messaging", "Dev Tools", "Email", "Automation", "Docs", "Support", "E-commerce", "Database"];

const STATUS_COLOR: Record<ConnectedIntegration["status"], string> = {
  connected: "var(--flow-success)",
  syncing:   "var(--flow-warning)",
  error:     "var(--flow-danger)",
};

const STATUS_LABEL: Record<ConnectedIntegration["status"], string> = {
  connected: "Connected",
  syncing:   "Syncing…",
  error:     "Error",
};

/* ── Page ─────────────────────────────────────────────────────────────── */
export function IntegrationsPage() {
  useTranslation("common");
  const [category, setCategory] = useState("All");
  const [search, setSearch]     = useState("");

  const filtered = AVAILABLE.filter(a =>
    (category === "All" || a.category === category) &&
    (search === "" || a.name.toLowerCase().includes(search.toLowerCase()) || a.description.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "var(--bg-base)", color: "var(--t1)" }}>
      {/* Header */}
      <div style={{ padding: "24px 28px 0", borderBlockEnd: "1px solid var(--b1)", background: "var(--bg-surface)", flexShrink: 0 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 4px", color: "var(--t1)" }}>Integrations</h1>
        <p style={{ fontSize: 13, color: "var(--t3)", margin: "0 0 20px" }}>Connect external services to power your apps</p>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 28 }}>

        {/* Connected section */}
        <section style={{ marginBlockEnd: 36 }}>
          <h2 style={{ fontSize: 13, fontWeight: 600, color: "var(--t2)", textTransform: "uppercase", letterSpacing: "0.06em", marginBlockEnd: 14 }}>
            Connected ({CONNECTED.length})
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
            {CONNECTED.map(intg => (
              <ConnectedCard key={intg.id} intg={intg} />
            ))}
          </div>
        </section>

        {/* Available section */}
        <section>
          <h2 style={{ fontSize: 13, fontWeight: 600, color: "var(--t2)", textTransform: "uppercase", letterSpacing: "0.06em", marginBlockEnd: 14 }}>
            Available
          </h2>

          {/* Filters */}
          <div style={{ display: "flex", gap: 10, marginBlockEnd: 16, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ position: "relative", flex: "0 0 240px" }}>
              <svg style={{ position: "absolute", insetInlineStart: 10, top: "50%", transform: "translateY(-50%)", color: "var(--t3)" }} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
              <input
                type="search"
                placeholder="Search integrations…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ width: "100%", boxSizing: "border-box", paddingInline: "32px 12px", paddingBlock: "8px", fontSize: 13, background: "var(--bg-input)", border: "1px solid var(--b1)", borderRadius: 8, color: "var(--t1)", outline: "none" }}
              />
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {CATEGORIES.map(cat => (
                <button
                  key={cat}
                  onClick={() => setCategory(cat)}
                  style={{ padding: "5px 12px", fontSize: 12, fontWeight: 500, borderRadius: 20, border: "1px solid", cursor: "pointer", transition: "all .15s",
                    background: category === cat ? "var(--accent-dim)" : "transparent",
                    borderColor: category === cat ? "var(--accent-border)" : "var(--b1)",
                    color: category === cat ? "var(--accent)" : "var(--t3)",
                  }}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
            {filtered.map(intg => (
              <AvailableCard key={intg.id} intg={intg} />
            ))}
            {filtered.length === 0 && (
              <div style={{ gridColumn: "1/-1", padding: "40px 0", textAlign: "center", color: "var(--t3)", fontSize: 14 }}>
                No integrations match your search.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ConnectedCard({ intg }: { intg: ConnectedIntegration }) {
  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 12, padding: "16px 18px", display: "flex", gap: 14, alignItems: "flex-start" }}>
      <div style={{ width: 40, height: 40, borderRadius: 10, background: "var(--bg-card)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, flexShrink: 0 }}>
        {intg.icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBlockEnd: 2 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)" }}>{intg.name}</span>
          <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 500, color: STATUS_COLOR[intg.status] }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: STATUS_COLOR[intg.status], display: "inline-block" }} />
            {STATUS_LABEL[intg.status]}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--t3)", marginBlockEnd: 10 }}>{intg.category} · {intg.lastSync}</div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 12, color: "var(--t3)" }}>{intg.events.toLocaleString()} events</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button style={{ padding: "4px 10px", fontSize: 11, fontWeight: 500, background: "var(--bg-card)", border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer", color: "var(--t2)" }}>Config</button>
            <button style={{ padding: "4px 10px", fontSize: 11, fontWeight: 500, background: "var(--bg-card)", border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer", color: "var(--red)" }}>Remove</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AvailableCard({ intg }: { intg: AvailableIntegration }) {
  return (
    <div style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 12, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 10, position: "relative" }}>
      {intg.popular && (
        <span style={{ position: "absolute", insetBlockStart: 12, insetInlineEnd: 12, fontSize: 10, fontWeight: 600, background: "var(--accent-dim)", color: "var(--accent)", border: "1px solid var(--accent-border)", borderRadius: 20, padding: "2px 8px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Popular
        </span>
      )}
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <div style={{ width: 36, height: 36, borderRadius: 8, background: "var(--bg-card)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0 }}>
          {intg.icon}
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{intg.name}</div>
          <div style={{ fontSize: 11, color: "var(--t3)" }}>{intg.category}</div>
        </div>
      </div>
      <p style={{ fontSize: 12, color: "var(--t3)", margin: 0, lineHeight: 1.5 }}>{intg.description}</p>
      <button style={{ alignSelf: "flex-start", padding: "6px 14px", fontSize: 12, fontWeight: 600, background: "var(--accent)", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}>
        Connect
      </button>
    </div>
  );
}
