/**
 * PluginsPage — Installed / Available tab shell (mirrors BillingPage.tsx's
 * and MarketplacePage.tsx's established tab-shell pattern; no React Router
 * in this app, so this is one Sidebar nav entry with internal state).
 *
 * Data: GET /plugins/installed, GET /marketplace/listings?type=plugin,
 *       POST /marketplace/listings/{id}/install (installing IS how a
 *       plugin_installations row gets created — see app/marketplace/
 *       installer.py's stage 7 hook), plus the per-installation
 *       enable/disable/approve/uninstall/reload endpoints under
 *       /plugins/installed/{id}/*.
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/ToastContext";
import { useOrg } from "../../contexts/OrgContext";
import { VersionsTab } from "../marketplace/tabs/VersionsTab";
import { PermissionsTab } from "./tabs/PermissionsTab";
import { HealthTab } from "./tabs/HealthTab";
import { ConfigTab } from "./tabs/ConfigTab";

interface Installation {
  id: string;
  marketplace_item_id: string;
  plugin_id: string;
  version: string;
  status: "installed" | "enabled" | "disabled" | "failed" | "uninstalled";
  approved: boolean;
  config: Record<string, unknown>;
  manifest?: { required_permissions?: string[]; name?: string; description?: string; author?: string };
}

interface AvailablePlugin {
  id: string; name: string; description: string; author: string; version: string; installs: number;
}

type TopTab = "installed" | "available";
type DetailTab = "config" | "permissions" | "health" | "versions";

const STATUS_COLOR: Record<string, string> = {
  enabled: "#00C853", disabled: "var(--t4)", failed: "#FF5252", installed: "#E8C87D", uninstalled: "var(--t5)",
};

export function PluginsPage() {
  const toast = useToast();
  const { currentOrgId, orgs } = useOrg();
  const [topTab, setTopTab] = useState<TopTab>("installed");
  const [installed, setInstalled] = useState<Installation[]>([]);
  const [available, setAvailable] = useState<AvailablePlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("config");
  const [busy, setBusy] = useState<string | null>(null);

  const loadInstalled = useCallback(async () => {
    if (!currentOrgId) { setInstalled([]); return; }
    try {
      const r = await apiFetch("/plugins/installed");
      if (!r.ok) throw new Error();
      setInstalled(await parseJSON<Installation[]>(r, "/plugins/installed"));
    } catch {
      toast("Could not load installed plugins", "err");
    }
  }, [currentOrgId, toast]);

  const loadAvailable = useCallback(async () => {
    try {
      const r = await apiFetch("/marketplace/listings?type=plugin&per_page=50");
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ items: AvailablePlugin[] }>(r, "/marketplace/listings");
      setAvailable(d.items ?? []);
    } catch {
      toast("Could not load available plugins", "err");
    }
  }, [toast]);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadInstalled(), loadAvailable()]).finally(() => setLoading(false));
  }, [loadInstalled, loadAvailable]);

  const install = async (listingId: string) => {
    if (!currentOrgId) { toast("Select an organization first", "err"); return; }
    setBusy(listingId);
    try {
      const r = await apiFetch(`/marketplace/listings/${listingId}/install`, { method: "POST" });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail ?? "Install failed");
      }
      toast("Plugin installed", "ok");
      setTopTab("installed");
      await loadInstalled();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Install failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const toggleEnabled = async (inst: Installation) => {
    setBusy(inst.id);
    const action = inst.status === "enabled" ? "disable" : "enable";
    try {
      const r = await apiFetch(`/plugins/installed/${inst.id}/${action}`, { method: "POST" });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail ?? `${action} failed`);
      }
      await loadInstalled();
    } catch (e) {
      toast(e instanceof Error ? e.message : `${action} failed`, "err");
    } finally {
      setBusy(null);
    }
  };

  const uninstall = async (inst: Installation) => {
    setBusy(inst.id);
    try {
      const r = await apiFetch(`/plugins/installed/${inst.id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      toast("Plugin uninstalled", "ok");
      if (expandedId === inst.id) setExpandedId(null);
      await loadInstalled();
    } catch {
      toast("Uninstall failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const toggleDetails = (id: string) => {
    setExpandedId(prev => (prev === id ? null : id));
    setDetailTab("config");
  };

  if (!currentOrgId) {
    return (
      <div className="empty-state" style={{ margin: "auto" }}>
        <div style={{ fontSize: 40 }}>🧩</div>
        <h3>No organization selected</h3>
        <p>{orgs.length === 0 ? "Create an organization first." : "Pick one from the Organizations page."}</p>
      </div>
    );
  }

  const installedItemIds = new Set(installed.filter(i => i.status !== "uninstalled").map(i => i.marketplace_item_id));

  return (
    <>
      <header style={{
        padding: "20px 24px 16px", borderBottom: "1px solid var(--border)",
        background: "var(--bg-surface)", flexShrink: 0, display: "flex", flexDirection: "column", gap: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.3px", color: "var(--t1)" }}>Plugins</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(["installed", "available"] as TopTab[]).map(t => (
            <button key={t} onClick={() => setTopTab(t)} style={{
              padding: "6px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600,
              background: topTab === t ? "rgba(232,200,125,.18)" : "rgba(255,255,255,.04)",
              color: topTab === t ? "#E8C87D" : "var(--t4)", textTransform: "capitalize",
            }}>
              {t} {t === "installed" ? `(${installed.length})` : ""}
            </button>
          ))}
        </div>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {loading ? (
          <div style={{ display: "grid", gap: 16 }}>
            {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 90, borderRadius: 14 }} />)}
          </div>
        ) : topTab === "installed" ? (
          installed.length === 0 ? (
            <div style={{ textAlign: "center", padding: "64px 0", color: "var(--t4)" }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>🧩</div>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: "var(--t2)" }}>No plugins installed</div>
              <p style={{ fontSize: 13 }}>Browse the Available tab to install one.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {installed.map(inst => (
                <div key={inst.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 14, padding: "16px 20px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{inst.manifest?.name ?? inst.plugin_id}</span>
                        <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: STATUS_COLOR[inst.status] ?? "var(--t4)" }}>
                          {inst.status}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--t4)" }}>v{inst.version} · {inst.plugin_id}</div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button onClick={() => toggleDetails(inst.id)} style={{
                        padding: "6px 12px", borderRadius: 8, border: "1px solid var(--border)",
                        background: "rgba(255,255,255,.04)", color: "var(--t3)", fontSize: 12, cursor: "pointer",
                      }}>
                        {expandedId === inst.id ? "Hide" : "Details"}
                      </button>
                      <button
                        onClick={() => void toggleEnabled(inst)} disabled={busy === inst.id}
                        style={{
                          padding: "6px 12px", borderRadius: 8, border: "1px solid var(--border)",
                          background: "rgba(255,255,255,.04)", color: "var(--t3)", fontSize: 12,
                          cursor: busy === inst.id ? "wait" : "pointer",
                        }}
                      >
                        {inst.status === "enabled" ? "Disable" : "Enable"}
                      </button>
                      <button
                        onClick={() => void uninstall(inst)} disabled={busy === inst.id}
                        style={{
                          padding: "6px 12px", borderRadius: 8, border: "1px solid var(--border)",
                          background: "rgba(255,82,82,.08)", color: "#FF5252", fontSize: 12,
                          cursor: busy === inst.id ? "wait" : "pointer",
                        }}
                      >
                        Uninstall
                      </button>
                    </div>
                  </div>

                  {expandedId === inst.id && (
                    <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
                      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
                        {(["config", "permissions", "health", "versions"] as DetailTab[]).map(t => (
                          <button key={t} onClick={() => setDetailTab(t)} style={{
                            padding: "5px 12px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 11, fontWeight: 600,
                            background: detailTab === t ? "rgba(232,200,125,.18)" : "rgba(255,255,255,.04)",
                            color: detailTab === t ? "#E8C87D" : "var(--t4)", textTransform: "capitalize",
                          }}>
                            {t}
                          </button>
                        ))}
                      </div>
                      {detailTab === "config" && <ConfigTab installationId={inst.id} config={inst.config} />}
                      {detailTab === "permissions" && (
                        <PermissionsTab
                          installationId={inst.id}
                          permissions={inst.manifest?.required_permissions ?? []}
                          approved={inst.approved}
                          onApproved={() => void loadInstalled()}
                        />
                      )}
                      {detailTab === "health" && <HealthTab installationId={inst.id} status={inst.status} />}
                      {detailTab === "versions" && (
                        <VersionsTab
                          listingId={inst.marketplace_item_id}
                          currentVersion={inst.version}
                          canManage={false}
                          onRolledBack={() => void loadInstalled()}
                        />
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )
        ) : (
          available.length === 0 ? (
            <div style={{ textAlign: "center", padding: "64px 0", color: "var(--t4)" }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>🧩</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: "var(--t2)" }}>No plugins published yet</div>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
              {available.map(p => {
                const alreadyInstalled = installedItemIds.has(p.id);
                return (
                <div key={p.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 14, padding: "16px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: "var(--t4)" }}>by {p.author} · v{p.version}</div>
                  </div>
                  <p style={{ fontSize: 12, color: "var(--t3)", margin: 0, lineHeight: 1.5 }}>{p.description}</p>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto" }}>
                    <span style={{ fontSize: 11, color: "var(--t5)" }}>{p.installs.toLocaleString()} installs</span>
                    <button
                      onClick={() => (alreadyInstalled ? setTopTab("installed") : void install(p.id))}
                      disabled={busy === p.id}
                      style={{
                        padding: "6px 16px", borderRadius: 8, border: "none", cursor: busy === p.id ? "wait" : "pointer",
                        background: alreadyInstalled ? "rgba(255,255,255,.06)" : "linear-gradient(135deg,#FFD700,#D4AF37)",
                        color: alreadyInstalled ? "var(--t3)" : "#0a0a0a", fontSize: 12, fontWeight: 700,
                      }}
                    >
                      {busy === p.id ? "…" : alreadyInstalled ? "Installed" : "Install"}
                    </button>
                  </div>
                </div>
                );
              })}
            </div>
          )
        )}
      </div>
    </>
  );
}
