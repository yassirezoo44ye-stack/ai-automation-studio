import { C } from "../../shared/lib/theme";
/**
 * SandboxPage — Agent Sandbox & Secure Execution Runtime monitoring.
 * Mirrors PluginsPage.tsx's tab-shell + expand-to-detail pattern (same
 * design system, same structural conventions). A sandbox worker's
 * lifecycle IS its plugin_installations row's lifecycle — Permission
 * Requests here is literally Plugin SDK's existing approval queue,
 * surfaced under this page rather than duplicated.
 *
 * Data: GET /sandbox/workers, GET /sandbox/security-events,
 *       GET /sandbox/permission-requests, POST .../stop, POST .../approve.
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/toast";
import { useOrg } from "../../contexts/OrgContext";
import { SandboxLogsTab } from "./tabs/SandboxLogsTab";
import { ResourceUsageTab } from "./tabs/ResourceUsageTab";

interface Worker {
  id: string;
  organization_id: string;
  plugin_installation_id: string;
  backend: "docker" | "process";
  status: "starting" | "running" | "stopped" | "crashed";
  pid_or_container_id: string | null;
  started_at: string;
  stopped_at: string | null;
  cpu_seconds_used: number | null;
  memory_mb_peak: number | null;
}

interface SecurityEvent {
  id: string;
  worker_id: string;
  severity: string;
  message: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

interface PermissionRequest {
  installation_id: string;
  plugin_id: string;
  version: string;
  status: string;
  pending_capabilities: string[];
}

type TopTab = "workers" | "permission-requests" | "security-events";
type DetailTab = "logs" | "resource-usage";

const STATUS_COLOR: Record<string, string> = {
  running: C.green, starting: C.blue, stopped: "var(--t4)", crashed: C.redSoft,
};

export function SandboxPage() {
  const toast = useToast();
  const { currentOrgId, orgs } = useOrg();
  const [topTab, setTopTab] = useState<TopTab>("workers");
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [permissionRequests, setPermissionRequests] = useState<PermissionRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("logs");
  const [busy, setBusy] = useState<string | null>(null);

  const loadWorkers = useCallback(async () => {
    if (!currentOrgId) { setWorkers([]); return; }
    try {
      const r = await apiFetch("/sandbox/workers");
      if (!r.ok) throw new Error();
      setWorkers(await parseJSON<Worker[]>(r, "/sandbox/workers"));
    } catch {
      toast("Could not load sandbox workers", "err");
    }
  }, [currentOrgId, toast]);

  const loadSecurityEvents = useCallback(async () => {
    if (!currentOrgId) { setSecurityEvents([]); return; }
    try {
      const r = await apiFetch("/sandbox/security-events");
      if (!r.ok) throw new Error();
      setSecurityEvents(await parseJSON<SecurityEvent[]>(r, "/sandbox/security-events"));
    } catch {
      toast("Could not load security events", "err");
    }
  }, [currentOrgId, toast]);

  const loadPermissionRequests = useCallback(async () => {
    if (!currentOrgId) { setPermissionRequests([]); return; }
    try {
      const r = await apiFetch("/sandbox/permission-requests");
      if (!r.ok) throw new Error();
      setPermissionRequests(await parseJSON<PermissionRequest[]>(r, "/sandbox/permission-requests"));
    } catch {
      toast("Could not load permission requests", "err");
    }
  }, [currentOrgId, toast]);

  useEffect(() => {
    void Promise.resolve().then(() => {
      setLoading(true);
      Promise.all([loadWorkers(), loadSecurityEvents(), loadPermissionRequests()]).finally(() => setLoading(false));
    });
  }, [loadWorkers, loadSecurityEvents, loadPermissionRequests]);

  const refresh = () => {
    void loadWorkers(); void loadSecurityEvents(); void loadPermissionRequests();
  };

  const stopWorker = async (w: Worker) => {
    setBusy(w.id);
    try {
      const r = await apiFetch(`/sandbox/workers/${w.id}/stop`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast("Worker stopped", "ok");
      await loadWorkers();
    } catch {
      toast("Stop failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const approveRequest = async (req: PermissionRequest) => {
    setBusy(req.installation_id);
    try {
      const r = await apiFetch(`/sandbox/permission-requests/${req.installation_id}/approve`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast("Approved", "ok");
      refresh();
    } catch {
      toast("Approval failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const toggleDetails = (id: string) => {
    setExpandedId(prev => (prev === id ? null : id));
    setDetailTab("logs");
  };

  if (!currentOrgId) {
    return (
      <div className="empty-state" style={{ margin: "auto" }}>
        <div style={{ fontSize: 40 }}>🛡️</div>
        <h3>No organization selected</h3>
        <p>{orgs.length === 0 ? "Create an organization first." : "Pick one from the Organizations page."}</p>
      </div>
    );
  }

  return (
    <>
      <header style={{
        padding: "20px 24px 16px", borderBottom: "1px solid var(--border)",
        background: "var(--bg-surface)", flexShrink: 0, display: "flex", flexDirection: "column", gap: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.3px", color: "var(--t1)" }}>Sandbox</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {([
            ["workers", "Workers"], ["permission-requests", "Permission Requests"], ["security-events", "Security Events"],
          ] as [TopTab, string][]).map(([t, label]) => (
            <button key={t} onClick={() => setTopTab(t)} style={{
              padding: "6px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600,
              background: topTab === t ? "var(--accent-dim)" : "rgba(255,255,255,.04)",
              color: topTab === t ? "var(--accent-2)" : "var(--t4)",
            }}>
              {label} {t === "workers" ? `(${workers.length})` : t === "permission-requests" ? `(${permissionRequests.length})` : ""}
            </button>
          ))}
        </div>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {loading ? (
          <div style={{ display: "grid", gap: 16 }}>
            {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 90, borderRadius: 14 }} />)}
          </div>
        ) : topTab === "workers" ? (
          workers.length === 0 ? (
            <div style={{ textAlign: "center", padding: "64px 0", color: "var(--t4)" }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>🛡️</div>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: "var(--t2)" }}>No sandbox workers</div>
              <p style={{ fontSize: 13 }}>Workers appear here when a plugin is installed and enabled from the Plugins page.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {workers.map(w => (
                <div key={w.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 14, padding: "16px 20px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{w.pid_or_container_id ?? w.id.slice(0, 8)}</span>
                        <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: STATUS_COLOR[w.status] ?? "var(--t4)" }}>
                          {w.status}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--t4)" }}>
                        {w.backend} · started {new Date(w.started_at).toLocaleString()}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button onClick={() => toggleDetails(w.id)} style={{
                        padding: "6px 12px", borderRadius: 8, border: "1px solid var(--border)",
                        background: "rgba(255,255,255,.04)", color: "var(--t3)", fontSize: 12, cursor: "pointer",
                      }}>
                        {expandedId === w.id ? "Hide" : "Details"}
                      </button>
                      <button
                        onClick={() => void stopWorker(w)}
                        disabled={busy === w.id || w.status === "stopped" || w.status === "crashed"}
                        style={{
                          padding: "6px 12px", borderRadius: 8, border: "1px solid var(--border)",
                          background: "rgba(248,113,113,.08)", color: C.redSoft, fontSize: 12,
                          cursor: busy === w.id ? "wait" : "pointer",
                          opacity: (w.status === "stopped" || w.status === "crashed") ? 0.5 : 1,
                        }}
                      >
                        {busy === w.id ? "…" : "Stop"}
                      </button>
                    </div>
                  </div>

                  {expandedId === w.id && (
                    <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
                      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
                        {(["logs", "resource-usage"] as DetailTab[]).map(t => (
                          <button key={t} onClick={() => setDetailTab(t)} style={{
                            padding: "5px 12px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 11, fontWeight: 600,
                            background: detailTab === t ? "var(--accent-dim)" : "rgba(255,255,255,.04)",
                            color: detailTab === t ? "var(--accent-2)" : "var(--t4)",
                          }}>
                            {t === "logs" ? "Logs" : "Resource Usage"}
                          </button>
                        ))}
                      </div>
                      {detailTab === "logs" && <SandboxLogsTab workerId={w.id} />}
                      {detailTab === "resource-usage" && <ResourceUsageTab key={w.status} workerId={w.id} />}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )
        ) : topTab === "permission-requests" ? (
          permissionRequests.length === 0 ? (
            <div style={{ textAlign: "center", padding: "64px 0", color: "var(--t4)" }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>✅</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: "var(--t2)" }}>No pending permission requests</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {permissionRequests.map(req => (
                <div key={req.installation_id} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  background: "var(--bg-surface)", border: "1px solid rgba(245,158,11,.3)",
                  borderRadius: 14, padding: "16px 20px",
                }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{req.plugin_id} <span style={{ color: "var(--t4)", fontWeight: 400 }}>v{req.version}</span></div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                      {req.pending_capabilities.map(c => (
                        <span key={c} style={{
                          fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 99,
                          background: "rgba(245,158,11,.12)", color: C.amber, border: "1px solid rgba(245,158,11,.3)",
                        }}>
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={() => void approveRequest(req)} disabled={busy === req.installation_id}
                    style={{
                      padding: "6px 16px", borderRadius: 8, border: "none", cursor: busy === req.installation_id ? "wait" : "pointer",
                      background: C.amber, color: "#000", fontSize: 12, fontWeight: 700,
                    }}
                  >
                    {busy === req.installation_id ? "…" : "Approve"}
                  </button>
                </div>
              ))}
            </div>
          )
        ) : (
          securityEvents.length === 0 ? (
            <div style={{ textAlign: "center", padding: "64px 0", color: "var(--t4)" }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>🛡️</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: "var(--t2)" }}>No security events</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {securityEvents.map(e => (
                <div key={e.id} style={{
                  display: "flex", gap: 12, alignItems: "center",
                  background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 16px",
                }}>
                  <span style={{
                    fontSize: 10, fontWeight: 700, textTransform: "uppercase", minWidth: 60,
                    color: e.severity === "error" ? C.redSoft : e.severity === "warning" ? C.amber : "var(--t4)",
                  }}>
                    {e.severity}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--t3)", flex: 1 }}>{e.message}</span>
                  <span style={{ fontSize: 11, color: "var(--t5)" }}>{new Date(e.created_at).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )
        )}
      </div>
    </>
  );
}
