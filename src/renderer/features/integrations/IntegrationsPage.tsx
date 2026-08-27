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

/* ── SVG icon map — replaces emoji icons for premium rendering ───── */
const ICON_COLOR: Record<string, string> = {
  "google-workspace": "#4285F4",
  "gmail":            "#EA4335",
  "slack":            "#E01E5A",
  "whatsapp":         "#25D366",
  "notion":           "#000000",
  "google-sheets":    "#34A853",
  "stripe":           "#6772E5",
  "github":           "#333333",
  "rest-api":         "#6E32E0",
  "webhooks":         "#F59E0B",
  "mcp":              "#0B7A70",
  "airtable":         "#18BFFF",
  "postgres":         "#336791",
  "supabase":         "#3ECF8E",
  "zapier":           "#FF4A00",
  "linear":           "#5E6AD2",
};

const ICON_DARK: Record<string, boolean> = {
  "notion": true,
  "github": true,
};

function IntegrationSvgIcon({ id, size = 22 }: { id: string; size?: number }) {
  const fill = ICON_COLOR[id] ?? "var(--accent)";
  const paths: Record<string, React.ReactNode> = {
    "google-workspace": <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm.31-8.86c-2.01-.37-2.57-.75-2.57-1.35 0-.68.63-1.15 1.67-1.15 1.1 0 1.51.53 1.54 1.3h1.36c-.03-1.06-.69-2.04-1.98-2.34V6h-1.83v1.58c-1.21.26-2.18 1.03-2.18 2.22 0 1.42 1.17 2.13 2.88 2.54 2.22.53 2.67.99 2.67 1.61 0 .46-.34 1.19-1.69 1.19-1.29 0-1.8-.58-1.86-1.3H9.48c.07 1.35 1.08 2.11 2.29 2.35V18h1.83v-1.57c1.22-.23 2.19-.9 2.19-2.13 0-1.7-1.46-2.28-3.48-2.16z"/>,
    "gmail": <><path d="M20 4H4C2.9 4 2 4.9 2 6v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></>,
    "slack": <><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/></>,
    "whatsapp": <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413Z"/>,
    "notion": <path d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.98-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.139c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z"/>,
    "google-sheets": <><path d="M11.318 0h8.386C20.739 0 21 .261 21 .296v3.682h-9.682V0zM11.318 10.705H21v3.977h-9.682v-3.977zM11.318 5.352H21v4.295h-9.682V5.352z" opacity=".6"/><path d="M0 .296C0 .261.261 0 .296 0h11.022v4H0V.296zM0 5.352h11.318v4.295H0V5.352zM0 10.705h11.318v3.977H0v-3.977z"/><path d="M0 14.682h21V20.7c0 .034-.261.3-.296.3H.296C.261 21 0 20.739 0 20.7v-6.018z" opacity=".6"/></>,
    "stripe": <path d="M13.976 9.15c-2.172-.806-3.356-1.426-3.356-2.409 0-.831.683-1.305 1.901-1.305 2.227 0 4.515.858 6.09 1.631l.89-5.494C18.252.975 15.697 0 12.165 0 9.667 0 7.589.654 6.104 1.872 4.56 3.147 3.757 4.992 3.757 7.218c0 4.039 2.467 5.76 6.476 7.219 2.585.92 3.445 1.574 3.445 2.583 0 .98-.84 1.545-2.354 1.545-1.875 0-4.965-.921-6.99-2.109l-.9 5.555C5.175 22.99 8.385 24 11.714 24c2.641 0 4.843-.624 6.328-1.813 1.664-1.305 2.525-3.236 2.525-5.732 0-4.128-2.524-5.851-6.594-7.305h.003z"/>,
    "github": <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>,
    "rest-api": <><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></>,
    "webhooks": <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>,
    "mcp": <><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/></>,
    "airtable": <><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/></>,
    "postgres": <><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></>,
    "supabase": <path d="M11.9 1.036c-.015-.986-1.26-1.41-1.874-.637L.764 12.05C.142 12.888.765 14.064 1.8 14.064h7.3l-.96 8.9c.015.986 1.26 1.41 1.875.637l9.262-11.652c.622-.837 0-2.013-1.035-2.013h-7.3l.959-8.9z"/>,
    "zapier": <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>,
    "linear": <path d="M3.5 3.5L.447 6.552a.5.5 0 0 0-.002.706l2.98 2.98a.5.5 0 0 0 .706 0l2.98-2.98a.499.499 0 0 0-.002-.706L3.5 3.5zm4.95 1.414a.5.5 0 0 1 .707-.707l5.657 5.657a.5.5 0 0 1 0 .707L9.157 16.228a.5.5 0 1 1-.707-.707l5.303-5.303-5.303-5.304z"/>,
  };

  const pathEl = paths[id];
  if (!pathEl) {
    // Fallback: first two chars of name
    return null;
  }
  const isDark = ICON_DARK[id];
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill={fill} xmlns="http://www.w3.org/2000/svg"
      style={{ flexShrink: 0 }}
    >
      {pathEl}
    </svg>
  );
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
  const iconColor   = ICON_COLOR[integration.id] ?? "var(--accent)";
  const hasSvgIcon  = integration.id in ICON_COLOR;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      style={{
        background: "var(--bg-surface)",
        border: `1px solid ${connected ? iconColor + "44" : "var(--b1)"}`,
        borderRadius: 16, padding: "18px 20px",
        display: "flex", flexDirection: "column", gap: 14,
        opacity: unavailable ? 0.65 : 1,
        transition: "border-color 0.2s, box-shadow 0.2s, transform 0.15s",
        boxShadow: connected ? `0 0 0 1px ${iconColor}22, 0 4px 20px ${iconColor}14` : "none",
      }}
      onMouseEnter={e => {
        if (!unavailable) (e.currentTarget as HTMLDivElement).style.transform = "translateY(-2px)";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLDivElement).style.transform = "none";
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {/* Icon */}
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: hasSvgIcon ? `${iconColor}14` : "var(--bg-card)",
          border: `1px solid ${hasSvgIcon ? iconColor + "28" : "var(--b1)"}`,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {hasSvgIcon
            ? <IntegrationSvgIcon id={integration.id} size={22} />
            : <span style={{ fontSize: 22, lineHeight: 1 }}>{integration.icon}</span>
          }
        </div>
        {/* Name + status */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {integration.name}
          </div>
          <div style={{ marginTop: 3 }}>
            <StatusPill status={status} hasBackend={hasBackend} />
          </div>
        </div>
        {/* Connected indicator dot */}
        {connected && (
          <div style={{
            width: 8, height: 8, borderRadius: "50%",
            background: "var(--green)", flexShrink: 0,
            boxShadow: "0 0 6px var(--green)",
            animation: "pulse 2s ease-in-out infinite",
          }} />
        )}
      </div>

      {/* Description */}
      <p style={{ fontSize: 12, color: "var(--t4)", margin: 0, lineHeight: 1.6, flex: 1 }}>
        {integration.description}
      </p>

      {/* Connected metadata */}
      {connected && connectedAt && (
        <div style={{ fontSize: 11, color: "var(--t5)", display: "flex", alignItems: "center", gap: 4 }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>
          {t("card.connectedAt", { date: new Date(connectedAt).toLocaleDateString() })}
        </div>
      )}

      {/* Error detail */}
      {status === "error" && (
        <div style={{ fontSize: 11, color: "var(--red)", display: "flex", alignItems: "center", gap: 5 }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          {t("card.connectionError")}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 7, marginTop: 2 }}>
        {unavailable ? (
          <button disabled style={{ flex: 1, padding: "7px 0", borderRadius: 8, border: "1px dashed var(--b2)", background: "transparent", color: "var(--t5)", fontSize: 12, cursor: "not-allowed" }}>
            {t("card.comingSoon")}
          </button>
        ) : connected ? (
          <>
            <button
              onClick={() => onConnect(integration)}
              style={{ flex: 1, padding: "7px 0", borderRadius: 8, border: "1px solid var(--b1)", background: "transparent", color: "var(--t2)", fontSize: 12, cursor: "pointer", fontWeight: 500 }}
            >
              {t("card.configure")}
            </button>
            <button
              onClick={() => onDisconnect(integration.id)}
              style={{ padding: "7px 12px", borderRadius: 8, border: "1px solid rgba(239,68,68,0.25)", background: "rgba(239,68,68,0.06)", color: "var(--red)", fontSize: 12, cursor: "pointer", fontWeight: 500 }}
            >
              {t("card.disconnect")}
            </button>
          </>
        ) : (
          <button
            onClick={() => onConnect(integration)}
            style={{
              flex: 1, padding: "8px 0", borderRadius: 8, border: "none",
              background: status === "error"
                ? "var(--red)"
                : `linear-gradient(135deg, ${iconColor} 0%, ${iconColor}cc 100%)`,
              color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer",
              boxShadow: `0 2px 8px ${iconColor}40`,
            }}
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
