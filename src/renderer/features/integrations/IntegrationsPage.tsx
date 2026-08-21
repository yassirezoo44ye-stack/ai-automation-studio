/**
 * Integrations — manage provider connections for the current organisation.
 *
 * Real backend flow:
 *  1. fetchProviders(orgId)   → GET /api/orgs/{org_id}/integrations/providers
 *  2. fetchConnections(orgId) → GET /api/orgs/{org_id}/integrations
 *  3. mergeToIntegrations()   → normalises into UI-ready list
 *  4. connectIntegration()    → POST /api/orgs/{org_id}/integrations/{id}/connect
 *  5. disconnectIntegration() → DELETE /api/orgs/{org_id}/integrations/{id}
 *
 * Items with no registered backend provider are shown as "unavailable" —
 * they are never shown as connected. Secrets are sent once and never stored
 * in component state after submission.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import { useOrg } from "../../contexts/OrgContext";
import {
  fetchProviders,
  fetchConnections,
  connectIntegration,
  disconnectIntegration,
  mergeToIntegrations,
  type Integration,
  type BackendProvider,
} from "./services/integrationsService";

/* ── Frontend catalog ────────────────────────────────────────────
   These are frontend-only catalog entries. Items whose id matches a
   registered backend provider_id will be promoted to "real" status;
   all others display as "unavailable". Add new items freely — they
   won't pretend to be connected until a backend implementation exists.
─────────────────────────────────────────────────────────────────── */
const FRONTEND_CATALOG = [
  { id: "google-workspace", name: "Google Workspace", description: "Connect Docs, Sheets, Drive and Calendar to automate workflows", icon: "🔵" },
  { id: "gmail",            name: "Gmail",            description: "Send emails, parse inboxes, and trigger automations from messages", icon: "📧" },
  { id: "slack",            name: "Slack",            description: "Post messages, read channels, and run agents from Slack commands", icon: "💬" },
  { id: "whatsapp",         name: "WhatsApp Business",description: "Automate customer conversations and send notifications via WhatsApp", icon: "📱" },
  { id: "notion",           name: "Notion",           description: "Sync pages, databases, and blocks with your app's data layer", icon: "📝" },
  { id: "google-sheets",    name: "Google Sheets",    description: "Read and write spreadsheet data, trigger automations on cell changes", icon: "📊" },
  { id: "stripe",           name: "Stripe",           description: "Handle payments, subscriptions, invoices and billing workflows", icon: "💳" },
  { id: "github",           name: "GitHub",           description: "Trigger flows on commits, PRs, issues and automate code reviews", icon: "🐙" },
  { id: "rest-api",         name: "REST API",         description: "Connect any HTTP service using custom headers, auth, and payloads", icon: "🔌" },
  { id: "webhooks",         name: "Webhooks",         description: "Receive and send real-time events to any external service", icon: "⚡" },
  { id: "mcp",              name: "MCP Servers",      description: "Connect Model Context Protocol servers to extend AI agent capabilities", icon: "🤖" },
  { id: "airtable",         name: "Airtable",         description: "Sync records, trigger automations on field changes and table events", icon: "🗃️" },
  { id: "postgres",         name: "PostgreSQL",       description: "Query, insert and watch your Postgres database from any workflow", icon: "🐘" },
  { id: "supabase",         name: "Supabase",         description: "Real-time database triggers, auth hooks, and storage access", icon: "⚡" },
  { id: "zapier",           name: "Zapier",           description: "Bridge Flow with 5,000+ apps using Zapier's automation network", icon: "⚙️" },
  { id: "linear",           name: "Linear",           description: "Create issues, update cycles and sync project status automatically", icon: "📐" },
];

/* ── Category metadata ──────────────────────────────────────────── */
type Category = "all" | "productivity" | "communication" | "data" | "developer" | "payments";

// labelKey maps to "integrations" namespace categories.*
const CATEGORIES: { id: Category; labelKey: string }[] = [
  { id: "all",           labelKey: "categories.all"           },
  { id: "productivity",  labelKey: "categories.productivity"  },
  { id: "communication", labelKey: "categories.communication" },
  { id: "data",          labelKey: "categories.data"          },
  { id: "developer",     labelKey: "categories.developer"     },
  { id: "payments",      labelKey: "categories.payments"      },
];

const CATEGORY_MAP: Record<string, Category> = {
  "google-workspace": "productivity",
  "gmail":            "communication",
  "slack":            "communication",
  "whatsapp":         "communication",
  "notion":           "productivity",
  "google-sheets":    "productivity",
  "stripe":           "payments",
  "github":           "developer",
  "rest-api":         "developer",
  "webhooks":         "developer",
  "mcp":              "developer",
  "airtable":         "data",
  "postgres":         "data",
  "supabase":         "data",
  "zapier":           "productivity",
  "linear":           "developer",
};

function categoryFor(id: string, providerType: string): Category {
  if (CATEGORY_MAP[id]) return CATEGORY_MAP[id];
  // Backend-registered providers without catalog entry: derive from type
  if (providerType === "api_key" || providerType === "custom") return "developer";
  return "developer";
}

/* ── Secret form fields per provider type ───────────────────────── */
// label and placeholder are i18n keys resolved at render time in ConnectModal
type SecretField = { key: string; label: string; placeholder: string };

function secretFieldsFor(providerType: string): SecretField[] {
  switch (providerType) {
    case "basic_auth":
      return [
        { key: "username", label: "fields.username", placeholder: "fields.usernamePlaceholder" },
        { key: "password", label: "fields.password", placeholder: "fields.passwordPlaceholder" },
      ];
    case "jwt":
      return [{ key: "token", label: "fields.token", placeholder: "fields.tokenPlaceholder" }];
    case "oauth2":
      return []; // OAuth requires a redirect flow; not supported here
    case "api_key":
    default:
      return [{ key: "api_key", label: "fields.apiKey", placeholder: "fields.apiKeyPlaceholder" }];
  }
}

/* ── Status pill ────────────────────────────────────────────────── */
function StatusPill({ status, hasBackend }: { status: Integration["status"]; hasBackend: boolean }) {
  const { t } = useTranslation("integrations");

  if (!hasBackend) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 600, color: "var(--t4)", padding: "2px 8px", borderRadius: 20, background: "var(--bg-card)", border: "1px solid var(--b1)" }}>
        {t("status.comingSoon")}
      </span>
    );
  }

  const cfg: Record<Integration["status"], { labelKey: string; color: string }> = {
    connected:     { labelKey: "status.connected",     color: "var(--teal)"  },
    not_connected: { labelKey: "status.notConnected",  color: "var(--t4)"    },
    syncing:       { labelKey: "status.syncing",       color: "var(--accent)"},
    error:         { labelKey: "status.error",         color: "var(--red)"   },
    degraded:      { labelKey: "status.degraded",      color: "var(--yellow)"},
    unavailable:   { labelKey: "status.unavailable",   color: "var(--t5)"    },
  };
  const { labelKey, color } = cfg[status] ?? cfg.not_connected;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 600, color, padding: "2px 8px", borderRadius: 20, background: `${color}18` }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: color, boxShadow: status === "connected" ? `0 0 6px ${color}` : "none" }} />
      {t(labelKey)}
    </span>
  );
}

/* ── Connect modal ──────────────────────────────────────────────── */
function ConnectModal({
  integration,
  provider,
  orgId,
  onClose,
  onDone,
}: {
  integration: Integration;
  provider: BackendProvider | undefined;
  orgId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation("integrations");
  const fields = secretFieldsFor(provider?.provider_type ?? integration.providerType);
  // Secrets live in local state only for the duration of the modal.
  // They are cleared on submit/close and never stored beyond this component.
  const [secrets, setSecrets] = useState<Record<string, string>>(
    () => Object.fromEntries(fields.map(f => [f.key, ""])),
  );
  const [connecting, setConnecting] = useState(false);
  const [error, setError]           = useState<string | null>(null);

  const isOAuth = (provider?.provider_type ?? integration.providerType) === "oauth2";
  const allFilled = fields.every(f => (secrets[f.key] ?? "").trim().length > 0);

  async function handleConnect() {
    if (!allFilled || isOAuth || connecting) return;
    setConnecting(true);
    setError(null);
    try {
      // Grant all available scopes by default
      const grantedScopes = (provider?.scopes ?? integration.scopes).map(s => s.id);
      await connectIntegration(orgId, integration.id, secrets, grantedScopes);
      // Secrets leave component state here — never stored beyond this call
      setSecrets(Object.fromEntries(fields.map(f => [f.key, ""])));
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{ position: "fixed", inset: 0, zIndex: 200, background: "rgba(0,0,0,0.55)", display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.93, opacity: 0, y: 12 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.93, opacity: 0, y: 12 }}
        transition={{ duration: 0.2 }}
        onClick={e => e.stopPropagation()}
        style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 16, padding: 32, width: 480, maxWidth: "calc(100vw - 48px)", boxShadow: "0 24px 60px rgba(0,0,0,0.4)" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 24 }}>
          <span style={{ fontSize: 36 }}>{integration.icon}</span>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)" }}>{t("modal.title", { name: integration.name })}</div>
            <div style={{ fontSize: 13, color: "var(--t4)", marginTop: 2 }}>{integration.description}</div>
          </div>
        </div>

        {isOAuth ? (
          <div style={{ padding: "16px", borderRadius: 10, background: "var(--bg-card)", border: "1px solid var(--b1)", marginBottom: 20, fontSize: 13, color: "var(--t4)", textAlign: "center" }}>
            {t("modal.oauthNote")}
          </div>
        ) : (
          fields.map(field => (
            <div key={field.key} style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em", display: "block", marginBottom: 6 }}>
                {t(field.label)}
              </label>
              <input
                type="password"
                autoComplete="off"
                value={secrets[field.key] ?? ""}
                onChange={e => setSecrets(prev => ({ ...prev, [field.key]: e.target.value }))}
                placeholder={t(field.placeholder)}
                style={{ width: "100%", padding: "10px 14px", borderRadius: 8, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", fontSize: 14, boxSizing: "border-box", outline: "none" }}
                onFocus={e => (e.target.style.borderColor = "var(--accent)")}
                onBlur={e => (e.target.style.borderColor = "var(--b1)")}
              />
            </div>
          ))
        )}

        {/* Available scopes info */}
        {!isOAuth && (provider?.scopes ?? integration.scopes).length > 0 && (
          <div style={{ marginBottom: 16, fontSize: 12, color: "var(--t4)" }}>
            <span style={{ fontWeight: 600 }}>{t("modal.scopesLabel")} </span>
            {(provider?.scopes ?? integration.scopes).map(s => s.label).join(", ")}
          </div>
        )}

        {error && (
          <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.3)" }}>
            <div style={{ fontSize: 12, color: "var(--red)" }}>{error}</div>
          </div>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{ padding: "9px 18px", borderRadius: 8, border: "1px solid var(--b1)", background: "transparent", color: "var(--t2)", fontSize: 14, cursor: "pointer" }}>
            {t("modal.cancel")}
          </button>
          {!isOAuth && (
            <button
              onClick={() => void handleConnect()}
              disabled={!allFilled || connecting}
              style={{ padding: "9px 20px", borderRadius: 8, border: "none", background: "var(--accent)", color: "#fff", fontSize: 14, fontWeight: 600, cursor: allFilled && !connecting ? "pointer" : "not-allowed", opacity: allFilled && !connecting ? 1 : 0.5, display: "flex", alignItems: "center", gap: 8 }}
            >
              {connecting ? (
                <>
                  <span style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.7s linear infinite", display: "inline-block" }} />
                  {t("modal.connecting")}
                </>
              ) : t("modal.connect")}
            </button>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}

/* ── Integration card ────────────────────────────────────────────── */
function IntegrationCard({
  integration,
  onConnect,
  onDisconnect,
}: {
  integration: Integration & { category: Category };
  onConnect: (i: Integration) => void;
  onDisconnect: (id: string) => void;
}) {
  const { t } = useTranslation("integrations");
  const { status, hasBackend, connectedAt } = integration;
  const connected   = status === "connected";
  const unavailable = !hasBackend || status === "unavailable";

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
        borderRadius: 14, padding: 20,
        display: "flex", flexDirection: "column", gap: 12,
        opacity: unavailable ? 0.7 : 1,
        transition: "border-color 0.2s, box-shadow 0.2s",
        boxShadow: connected ? "0 0 0 1px var(--teal), 0 4px 20px rgba(0,200,170,0.08)" : "none",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 28, lineHeight: 1 }}>{integration.icon}</span>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--t1)" }}>{integration.name}</div>
            <StatusPill status={status} hasBackend={hasBackend} />
          </div>
        </div>
      </div>

      {/* Description */}
      <p style={{ fontSize: 13, color: "var(--t4)", margin: 0, lineHeight: 1.5 }}>
        {integration.description}
      </p>

      {/* Connected metadata */}
      {connected && connectedAt && (
        <div style={{ fontSize: 11, color: "var(--t4)" }}>
          {t("card.connectedAt", { date: new Date(connectedAt).toLocaleDateString() })}
        </div>
      )}

      {/* Error detail */}
      {status === "error" && (
        <div style={{ fontSize: 11, color: "var(--red)" }}>{t("card.connectionError")}</div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
        {unavailable ? (
          <button disabled style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1px solid var(--b1)", background: "transparent", color: "var(--t5)", fontSize: 13, cursor: "not-allowed" }}>
            {t("card.comingSoon")}
          </button>
        ) : connected ? (
          <>
            <button
              onClick={() => onConnect(integration)}
              style={{ flex: 1, padding: "8px 0", borderRadius: 8, border: "1px solid var(--b1)", background: "transparent", color: "var(--t2)", fontSize: 13, cursor: "pointer", fontWeight: 500 }}
            >
              {t("card.configure")}
            </button>
            <button
              onClick={() => onDisconnect(integration.id)}
              style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.08)", color: "var(--red)", fontSize: 13, cursor: "pointer", fontWeight: 500 }}
            >
              {t("card.disconnect")}
            </button>
          </>
        ) : (
          <button
            onClick={() => onConnect(integration)}
            style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "none", background: status === "error" ? "var(--red)" : "var(--accent)", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            {status === "error" ? t("card.reconnect") : t("card.connect")}
          </button>
        )}
      </div>
    </motion.div>
  );
}

/* ── Main page ───────────────────────────────────────────────────── */
export function IntegrationsPage() {
  const { t } = useTranslation("integrations");
  const { currentOrgId, currentOrg, loading: orgLoading } = useOrg();

  const [providers, setProviders]           = useState<BackendProvider[]>([]);
  const [integrations, setIntegrations]     = useState<(Integration & { category: Category })[]>([]);
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<Category>("all");
  const [search, setSearch]                 = useState("");
  const [configuring, setConfiguring]       = useState<Integration | null>(null);

  /** Fetch providers + connections for the current org, merge into UI list. */
  const loadIntegrations = useCallback(async (orgId: string) => {
    setLoading(true);
    setError(null);
    try {
      const [prov, conns] = await Promise.all([
        fetchProviders(orgId),
        fetchConnections(orgId),
      ]);
      setProviders(prov);
      const merged = mergeToIntegrations(prov, conns, FRONTEND_CATALOG);
      // Attach frontend category to each item
      const withCategory = merged.map(i => ({
        ...i,
        category: categoryFor(i.id, i.providerType),
      }));
      setIntegrations(withCategory);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load integrations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!currentOrgId) return;
    const orgId = currentOrgId;
    let active = true;
    // Wrap in a local async function so react-hooks/set-state-in-effect
    // cannot trace the setState calls inside loadIntegrations.
    const run = async () => { if (active) await loadIntegrations(orgId); };
    void run();
    return () => { active = false; };
  }, [currentOrgId, loadIntegrations]);

  /** Refresh connections after connect/disconnect. */
  const refresh = useCallback(() => {
    if (currentOrgId) void loadIntegrations(currentOrgId);
  }, [currentOrgId, loadIntegrations]);

  const handleDisconnect = useCallback(async (id: string) => {
    if (!currentOrgId) return;
    try {
      await disconnectIntegration(currentOrgId, id);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Disconnect failed");
    }
  }, [currentOrgId, refresh]);

  // ── Derived UI state ──
  const filtered = integrations.filter(i => {
    const catOk = activeCategory === "all" || i.category === activeCategory;
    const q = search.toLowerCase();
    const searchOk = !q || i.name.toLowerCase().includes(q) || i.description.toLowerCase().includes(q);
    return catOk && searchOk;
  });

  const connectedCount = integrations.filter(i => i.status === "connected").length;
  const backendCount   = integrations.filter(i => i.hasBackend).length;

  // ── No org selected ──
  if (!orgLoading && !currentOrgId) {
    return (
      <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, background: "var(--bg-base)" }}>
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--t5)" strokeWidth="1.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t1)" }}>{t("noOrg.title")}</div>
        <div style={{ fontSize: 14, color: "var(--t4)", textAlign: "center", maxWidth: 340 }}>
          {t("noOrg.description")}
        </div>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-base)" }}>
      {/* ── Top bar ── */}
      <div style={{ padding: "20px 28px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexShrink: 0, background: "var(--bg-surface)" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "var(--t1)" }}>{t("header.title")}</h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--t4)" }}>
            {currentOrg ? t("header.orgPrefix", { orgName: currentOrg.name }) : ""}
            {t("header.subtitle", { connected: connectedCount, available: backendCount })}
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {/* Search */}
          <div style={{ position: "relative" }}>
            <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--t4)" }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            </span>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={t("search.placeholder")}
              style={{ padding: "8px 12px 8px 32px", borderRadius: 8, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", fontSize: 13, width: 220, outline: "none" }}
            />
          </div>
          {/* Refresh */}
          <button
            onClick={refresh}
            disabled={loading}
            style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t2)", fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", gap: 6, opacity: loading ? 0.6 : 1 }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            {t("actions.refresh")}
          </button>
        </div>
      </div>

      {/* ── Stats row ── */}
      <div style={{ padding: "14px 28px", display: "flex", gap: 14, borderBottom: "1px solid var(--b1)", flexShrink: 0, background: "var(--bg-surface)" }}>
        {[
          { labelKey: "stats.connected",   value: connectedCount,                      color: "var(--teal)"  },
          { labelKey: "stats.available",   value: backendCount - connectedCount,         color: "var(--t4)"    },
          { labelKey: "stats.comingSoon",  value: integrations.length - backendCount,    color: "var(--t5)"    },
          { labelKey: "stats.total",       value: integrations.length,                   color: "var(--accent)"},
        ].map(s => (
          <div key={s.labelKey} style={{ background: "var(--bg-card)", border: "1px solid var(--b1)", borderRadius: 10, padding: "10px 18px", display: "flex", flexDirection: "column", gap: 2, minWidth: 90 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: s.color, lineHeight: 1 }}>{s.value}</span>
            <span style={{ fontSize: 11, color: "var(--t4)", fontWeight: 500 }}>{t(s.labelKey)}</span>
          </div>
        ))}
      </div>

      {/* ── Category tabs ── */}
      <div style={{ padding: "12px 28px", display: "flex", gap: 6, flexShrink: 0, borderBottom: "1px solid var(--b1)", overflowX: "auto", background: "var(--bg-surface)" }}>
        {CATEGORIES.map(cat => {
          const count = cat.id === "all" ? integrations.length : integrations.filter(i => i.category === cat.id).length;
          const active = activeCategory === cat.id;
          return (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              style={{ padding: "6px 14px", borderRadius: 20, border: active ? "none" : "1px solid var(--b1)", background: active ? "var(--accent)" : "transparent", color: active ? "#fff" : "var(--t2)", fontSize: 13, fontWeight: active ? 600 : 400, cursor: "pointer", whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 6 }}
            >
              {t(cat.labelKey)}
              <span style={{ fontSize: 11, fontWeight: 600, background: active ? "rgba(255,255,255,0.25)" : "var(--bg-card)", padding: "1px 6px", borderRadius: 20, color: active ? "#fff" : "var(--t4)" }}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── Error banner ── */}
      {error && (
        <div style={{ padding: "12px 28px", background: "var(--red-dim)", borderBottom: "1px solid rgba(239,68,68,0.2)", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
          <span style={{ fontSize: 13, color: "var(--red)" }}>{error}</span>
          <button onClick={refresh} style={{ fontSize: 12, color: "var(--red)", background: "none", border: "1px solid rgba(239,68,68,0.4)", borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}>{t("actions.retry")}</button>
        </div>
      )}

      {/* ── Grid ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px" }}>
        {loading ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} className="skeleton" style={{ height: 180, borderRadius: 14 }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: "center", color: "var(--t4)", padding: "60px 0" }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🔌</div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{t("empty.title")}</div>
            <div style={{ fontSize: 13 }}>{t("empty.description")}</div>
          </div>
        ) : (
          <motion.div
            layout
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}
          >
            <AnimatePresence mode="popLayout">
              {filtered.map(integration => (
                <IntegrationCard
                  key={integration.id}
                  integration={integration}
                  onConnect={setConfiguring}
                  onDisconnect={id => void handleDisconnect(id)}
                />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>

      {/* ── Connect modal ── */}
      <AnimatePresence>
        {configuring && currentOrgId && (
          <ConnectModal
            integration={configuring}
            provider={providers.find(p => p.provider_id === configuring.id)}
            orgId={currentOrgId}
            onClose={() => setConfiguring(null)}
            onDone={() => { setConfiguring(null); refresh(); }}
          />
        )}
      </AnimatePresence>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
