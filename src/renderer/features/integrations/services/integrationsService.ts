/**
 * Integrations service — connects to the real backend integration registry.
 *
 * Endpoints:
 *   GET  /api/orgs/{org_id}/integrations/providers  – registered providers
 *   GET  /api/orgs/{org_id}/integrations            – org's active connections
 *   POST /api/orgs/{org_id}/integrations/{id}/connect
 *   DEL  /api/orgs/{org_id}/integrations/{id}
 *   POST /api/orgs/{org_id}/integrations/{id}/sync
 *
 * All routes require X-Organization-Id header (set by OrgContext via apiFetch).
 * Secrets are never stored in frontend state after connect — only masked indicators.
 */
import { apiFetch, parseJSON, APIError } from "../../../shared/utils/api";

/* ── Backend contract types ─────────────────────────────────────── */
export interface BackendProvider {
  provider_id: string;
  display_name: string;
  provider_type: string; // "oauth2" | "api_key" | "jwt" | "basic_auth" | "custom"
  capabilities: {
    sync: boolean;
    webhooks: boolean;
    background_jobs: boolean;
    real_time: boolean;
  };
  scopes: Array<{ id: string; label: string; sensitive: boolean }>;
}

export interface BackendConnection {
  provider_id: string;
  status: string;     // "connected" | "disconnected" | "syncing" | "error" | "degraded"
  connected_by?: string;
  granted_scopes?: string[];
  connected_at?: string;
  updated_at?: string;
}

/* ── Canonical integration type for the UI ─────────────────────── */
export type IntegrationStatus = "connected" | "not_connected" | "error" | "syncing" | "degraded" | "unavailable";

export interface Integration {
  id: string;
  name: string;
  description: string;
  icon: string;
  providerType: string;
  status: IntegrationStatus;
  connectedAt: string | null;
  capabilities: BackendProvider["capabilities"] | null;
  scopes: BackendProvider["scopes"];
  /** True = has a real backend implementation. False = frontend-only catalog entry. */
  hasBackend: boolean;
}

/* ── Fetch providers from backend ───────────────────────────────── */
export async function fetchProviders(orgId: string): Promise<BackendProvider[]> {
  const path = `/api/orgs/${orgId}/integrations/providers`;
  const r = await apiFetch(path);
  const data = await parseJSON<{ providers: BackendProvider[] }>(r, path);
  return data.providers ?? [];
}

/* ── Fetch active connections ───────────────────────────────────── */
export async function fetchConnections(orgId: string): Promise<BackendConnection[]> {
  const path = `/api/orgs/${orgId}/integrations`;
  const r = await apiFetch(path);
  const data = await parseJSON<{ integrations: BackendConnection[] }>(r, path);
  return data.integrations ?? [];
}

/* ── Connect ────────────────────────────────────────────────────── */
export async function connectIntegration(
  orgId: string,
  providerId: string,
  secrets: Record<string, string>,
  grantedScopes: string[] = [],
): Promise<void> {
  const path = `/api/orgs/${orgId}/integrations/${providerId}/connect`;
  const r = await apiFetch(path, {
    method: "POST",
    body: JSON.stringify({ secrets, granted_scopes: grantedScopes }),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    let detail = `HTTP ${r.status}`;
    try { detail = JSON.parse(body)?.detail ?? detail; } catch { /* skip */ }
    throw new APIError(detail, { url: path, status: r.status, contentType: "" });
  }
}

/* ── Disconnect ─────────────────────────────────────────────────── */
export async function disconnectIntegration(orgId: string, providerId: string): Promise<void> {
  const path = `/api/orgs/${orgId}/integrations/${providerId}`;
  const r = await apiFetch(path, { method: "DELETE" });
  if (!r.ok && r.status !== 204) {
    const body = await r.text().catch(() => "");
    let detail = `HTTP ${r.status}`;
    try { detail = JSON.parse(body)?.detail ?? detail; } catch { /* skip */ }
    throw new APIError(detail, { url: path, status: r.status, contentType: "" });
  }
}

/* ── Trigger sync ───────────────────────────────────────────────── */
export async function triggerSync(orgId: string, providerId: string): Promise<string> {
  const path = `/api/orgs/${orgId}/integrations/${providerId}/sync`;
  const r = await apiFetch(path, { method: "POST" });
  const data = await parseJSON<{ run_id: string }>(r, path);
  return data.run_id;
}

/* ── Map backend status to UI status ───────────────────────────── */
function mapStatus(raw: string | undefined): IntegrationStatus {
  switch (raw) {
    case "connected":    return "connected";
    case "syncing":      return "syncing";
    case "error":        return "error";
    case "degraded":     return "degraded";
    case "disconnected": return "not_connected";
    default:             return "not_connected";
  }
}

/* ── Merge providers + connections into UI integrations ─────────── */
export function mergeToIntegrations(
  providers: BackendProvider[],
  connections: BackendConnection[],
  frontendCatalog: Array<{ id: string; name: string; description: string; icon: string }>,
): Integration[] {
  const connMap = new Map(connections.map(c => [c.provider_id, c]));
  const providerMap = new Map(providers.map(p => [p.provider_id, p]));

  // Real backend providers
  const backendItems: Integration[] = providers.map(p => {
    const conn = connMap.get(p.provider_id);
    return {
      id: p.provider_id,
      name: p.display_name,
      description: `${p.provider_type.replace(/_/g, " ")} integration`,
      icon: "🔌",
      providerType: p.provider_type,
      status: conn ? mapStatus(conn.status) : "not_connected",
      connectedAt: conn?.connected_at ?? null,
      capabilities: p.capabilities,
      scopes: p.scopes,
      hasBackend: true,
    };
  });

  // Frontend-only items (no backend provider registered)
  const frontendItems: Integration[] = frontendCatalog
    .filter(f => !providerMap.has(f.id))
    .map(f => ({
      id: f.id,
      name: f.name,
      description: f.description,
      icon: f.icon,
      providerType: "custom",
      status: "unavailable" as IntegrationStatus,
      connectedAt: null,
      capabilities: null,
      scopes: [],
      hasBackend: false,
    }));

  return [...backendItems, ...frontendItems];
}
