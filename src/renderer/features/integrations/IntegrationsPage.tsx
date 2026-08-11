/**
 * IntegrationsPage — connect/disconnect/sync org-scoped integration
 * providers. Mirrors PluginsPage.tsx's installed/available tab-shell
 * pattern (no React Router in this app; one Sidebar entry with internal
 * state).
 *
 * Data: GET  /api/orgs/{id}/integrations/providers   — registered providers
 *       GET  /api/orgs/{id}/integrations             — this org's connections
 *       POST /api/orgs/{id}/integrations/{pid}/connect  — connect (upsert;
 *         calling it again on an already-connected provider is how you
 *         reconfigure it — app/integrations/credential_store.py's save()
 *         is `ON CONFLICT (provider_id, organization_id) DO UPDATE`, so
 *         there is no separate "configure" endpoint to invent)
 *       DELETE /api/orgs/{id}/integrations/{pid}     — disconnect
 *       POST /api/orgs/{id}/integrations/{pid}/sync  — trigger sync
 *         (only shown for providers that declare capabilities.sync)
 *
 * There is no fixed secret-field schema per provider anywhere in the
 * backend (app/integrations/provider.py's connect() contract is a plain
 * `secrets: dict[str, str]`, and app/integrations/oauth.py confirms no
 * OAuth2 app is registered for any provider) — so the connect/reconfigure
 * form is a generic key/value secret list, never an invented per-provider
 * field set. Secret values are write-only: never echoed back by the list
 * endpoint, never logged, never held in localStorage.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/toast";
import { useOrg } from "../../contexts/OrgContext";
import { GoldButton, GlassCard, Dialog } from "../../shared/ui/gold";
import { EmptyState } from "../../shared/ui/EmptyState";
import { S } from "../../styles/theme";

interface ProviderScope { id: string; label: string; sensitive: boolean }
interface ProviderCapabilities { sync: boolean; webhooks: boolean; background_jobs: boolean; real_time: boolean }
interface Provider {
  provider_id: string;
  display_name: string;
  provider_type: "oauth2" | "api_key" | "jwt" | "basic_auth" | "custom";
  capabilities: ProviderCapabilities;
  scopes: ProviderScope[];
}

type ConnectionStatus = "disconnected" | "connected" | "syncing" | "error" | "degraded";
interface Connection {
  provider_id: string;
  provider_type: string;
  status: ConnectionStatus;
  granted_scopes: string[];
  connected_at: string;
  last_sync_at: string | null;
}

const STATUS_COLOR: Record<ConnectionStatus, string> = {
  connected: "var(--green)", syncing: "var(--blue)", error: "var(--red)",
  degraded: "var(--yellow)", disconnected: "var(--t4)",
};

export function IntegrationsPage() {
  const { t } = useTranslation("integrations");
  const toast = useToast();
  const { currentOrgId, orgs } = useOrg();

  const [providers, setProviders] = useState<Provider[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  // Generic key/value secret form — one row per secret field, no invented
  // per-provider schema (see module docstring above).
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [secretRows, setSecretRows] = useState<{ key: string; value: string }[]>([{ key: "", value: "" }]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!currentOrgId) { setProviders([]); setConnections([]); setLoading(false); return; }
    setLoading(true);
    setError(false);
    try {
      const [pr, cr] = await Promise.all([
        apiFetch(`/api/orgs/${currentOrgId}/integrations/providers`),
        apiFetch(`/api/orgs/${currentOrgId}/integrations`),
      ]);
      if (!pr.ok || !cr.ok) throw new Error();
      const pd = await parseJSON<{ providers: Provider[] }>(pr, "integrations/providers");
      const cd = await parseJSON<{ integrations: Connection[] }>(cr, "integrations");
      setProviders(pd.providers ?? []);
      setConnections(cd.integrations ?? []);
    } catch {
      toast(t("toast.loadFailed"), "err");
      setProviders([]); setConnections([]);
      setError(true);
    } finally { setLoading(false); }
  }, [currentOrgId, toast, t]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const openConnect = (providerId: string) => {
    setConnectingId(providerId);
    setSecretRows([{ key: "", value: "" }]);
  };

  const submitConnect = async () => {
    if (!currentOrgId || !connectingId) return;
    const secrets: Record<string, string> = {};
    for (const row of secretRows) {
      if (row.key.trim()) secrets[row.key.trim()] = row.value;
    }
    setSaving(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/integrations/${connectingId}/connect`, {
        method: "POST", body: JSON.stringify({ secrets, granted_scopes: [] }),
      });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "connect").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || t("toast.connectFailed"));
      }
      toast(t("toast.connected"), "ok");
      setConnectingId(null);
      await load();
    } catch (e) {
      toast((e as Error).message || t("toast.connectFailed"), "err");
    } finally { setSaving(false); }
  };

  const disconnect = async (providerId: string) => {
    if (!currentOrgId) return;
    if (!confirm(t("toast.confirmDisconnect"))) return;
    setBusy(providerId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/integrations/${providerId}`, { method: "DELETE" });
      if (!r.ok && r.status !== 404) throw new Error();
      toast(t("toast.disconnected"), "ok");
      await load();
    } catch { toast(t("toast.disconnectFailed"), "err"); }
    finally { setBusy(null); }
  };

  const triggerSync = async (providerId: string) => {
    if (!currentOrgId) return;
    setBusy(providerId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/integrations/${providerId}/sync`, { method: "POST" });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "sync").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || t("toast.syncFailed"));
      }
      toast(t("toast.syncStarted"), "ok");
      await load();
    } catch (e) {
      toast((e as Error).message || t("toast.syncFailed"), "err");
    } finally { setBusy(null); }
  };

  if (!currentOrgId) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>🔌</span>}
        title={t("noOrg.title")}
        description={orgs.length === 0 ? t("noOrg.descriptionNoOrgs") : t("noOrg.descriptionHasOrgs")}
      />
    );
  }

  const connectionByProvider = new Map(connections.map(c => [c.provider_id, c]));

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>{t("header.title")}</span>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {loading ? (
          <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
            {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 120, borderRadius: 14 }} />)}
          </div>
        ) : error ? (
          <EmptyState
            icon={<span style={{ fontSize: 40 }}>⚠️</span>}
            title={t("loadError.title")}
            description={t("loadError.description")}
            action={<GoldButton variant="ghost" onClick={() => void load()}>{t("loadError.retry")}</GoldButton>}
          />
        ) : providers.length === 0 ? (
          <EmptyState icon={<span style={{ fontSize: 48 }}>🔌</span>} title={t("empty.title")} description={t("empty.description")} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
            {providers.map(p => {
              const conn = connectionByProvider.get(p.provider_id);
              const isConnected = !!conn && conn.status !== "disconnected";
              const isBusy = busy === p.provider_id;
              return (
                <GlassCard key={p.provider_id} lift={false} style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{p.display_name}</span>
                    {conn && (
                      <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: STATUS_COLOR[conn.status] }}>
                        {t(`status.${conn.status}`, { defaultValue: conn.status })}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--t4)" }}>{t("providerType", { type: p.provider_type })}</div>
                  {p.scopes.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {p.scopes.map(s => (
                        <span key={s.id} style={{
                          fontSize: 10, padding: "2px 8px", borderRadius: 99,
                          background: "var(--bg-hover)", color: "var(--t4)",
                        }}>{s.label}</span>
                      ))}
                    </div>
                  )}
                  {conn?.last_sync_at && (
                    <div style={{ fontSize: 11, color: "var(--t5)" }}>
                      {t("lastSync", { date: new Date(conn.last_sync_at).toLocaleString() })}
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8, marginTop: "auto", flexWrap: "wrap" }}>
                    <GoldButton
                      variant={isConnected ? "ghost" : "primary"}
                      onClick={() => openConnect(p.provider_id)}
                      disabled={isBusy}
                    >
                      {isConnected ? t("actions.reconfigure") : t("actions.connect")}
                    </GoldButton>
                    {isConnected && p.capabilities.sync && (
                      <GoldButton variant="ghost" onClick={() => void triggerSync(p.provider_id)} disabled={isBusy}>
                        {isBusy ? "…" : t("actions.sync")}
                      </GoldButton>
                    )}
                    {isConnected && (
                      <GoldButton variant="danger" onClick={() => void disconnect(p.provider_id)} disabled={isBusy}>
                        {t("actions.disconnect")}
                      </GoldButton>
                    )}
                  </div>
                </GlassCard>
              );
            })}
          </div>
        )}

        <Dialog
          open={!!connectingId}
          onClose={() => !saving && setConnectingId(null)}
          title={t("connectForm.title", { name: providers.find(p => p.provider_id === connectingId)?.display_name ?? connectingId })}
        >
          <div style={{ fontSize: 11, color: "var(--t4)", marginBottom: 14 }}>{t("connectForm.description")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {secretRows.map((row, i) => (
              <div key={i} style={{ display: "flex", gap: 8 }}>
                <input
                  value={row.key}
                  onChange={e => setSecretRows(rows => rows.map((r, ri) => ri === i ? { ...r, key: e.target.value } : r))}
                  placeholder={t("connectForm.keyPlaceholder")} className="g-input" style={{ flex: 1 }}
                  autoFocus={i === 0}
                />
                <input
                  value={row.value}
                  onChange={e => setSecretRows(rows => rows.map((r, ri) => ri === i ? { ...r, value: e.target.value } : r))}
                  placeholder={t("connectForm.valuePlaceholder")} type="password" autoComplete="off"
                  className="g-input" style={{ flex: 1 }}
                />
                <GoldButton
                  variant="ghost"
                  onClick={() => setSecretRows(rows => rows.filter((_, ri) => ri !== i))}
                  disabled={secretRows.length === 1}
                  style={{ padding: "5px 10px" }}
                >×</GoldButton>
              </div>
            ))}
            <GoldButton variant="ghost" onClick={() => setSecretRows(rows => [...rows, { key: "", value: "" }])} style={{ alignSelf: "flex-start" }}>
              {t("connectForm.addField")}
            </GoldButton>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
            <GoldButton variant="ghost" onClick={() => setConnectingId(null)} disabled={saving}>{t("connectForm.cancel")}</GoldButton>
            <GoldButton onClick={() => void submitConnect()} disabled={saving || !secretRows.some(r => r.key.trim())}>
              {saving ? t("connectForm.saving") : t("connectForm.save")}
            </GoldButton>
          </div>
        </Dialog>
      </div>
    </>
  );
}
