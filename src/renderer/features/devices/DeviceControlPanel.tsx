/**
 * Device Control Panel
 *
 * Renders the "Create Session" flow and the "Active Session" status panel.
 *
 * SECURITY NOTE:
 *   This is a browser UI — it NEVER captures global OS input.
 *   All actual input capture/injection is done by the native Device Agent.
 *   This panel only manages session lifecycle via the REST API.
 */
import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { Device, DeviceSession, LayoutEntry } from "./types/devices.types";
import { DeviceLayoutEditor } from "./DeviceLayoutEditor";

const MAX_DEVICES = 5;

interface Props {
  devices: Device[];
  sessions: DeviceSession[];
  activeSession: DeviceSession | null;
  onCreateSession: (primaryId: string, deviceIds: string[], layout: LayoutEntry[]) => Promise<void>;
  onStartSession: (sessionId: string) => Promise<void>;
  onStopSession: (sessionId: string) => Promise<void>;
  onUpdateLayout: (sessionId: string, layout: LayoutEntry[]) => Promise<void>;
}

export function DeviceControlPanel({
  devices,
  sessions,
  activeSession,
  onCreateSession,
  onStartSession,
  onStopSession,
  onUpdateLayout,
}: Props) {
  const { t } = useTranslation("devices");

  const [view, setView] = useState<"list" | "create">("list");
  const [primaryId, setPrimaryId] = useState<string>("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [layout, setLayout] = useState<LayoutEntry[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onlineDevices = devices.filter(d => d.status === "online" || d.status === "offline");

  const toggleDevice = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < MAX_DEVICES - 1) next.add(id);
      return next;
    });
  }, []);

  const handleCreate = async () => {
    if (!primaryId) { setError(t("session.noPrimary")); return; }
    const deviceIds = [primaryId, ...Array.from(selectedIds).filter(id => id !== primaryId)];
    if (deviceIds.length < 2) { setError(t("session.needTwo")); return; }
    setCreating(true);
    setError(null);
    try {
      await onCreateSession(primaryId, deviceIds, layout);
      setView("list");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create session");
    } finally {
      setCreating(false);
    }
  };

  // ── Active session panel ───────────────────────────────────────────────────
  if (activeSession) {
    const primaryDevice = devices.find(d => d.id === activeSession.primary_device_id);
    const memberDevices = activeSession.members.map(m => devices.find(d => d.id === m.device_id)).filter(Boolean) as Device[];

    return (
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#2ecc71", boxShadow: "0 0 8px #2ecc71" }} />
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--t1)" }}>
            {t("session.activeTitle")}
          </h3>
        </div>

        <div style={{ background: "var(--bg-input)", borderRadius: 10, padding: 14, marginBottom: 14 }}>
          <Row label={t("session.primary")} value={primaryDevice?.name ?? "-"} />
          <Row label={t("session.devices")} value={`${activeSession.members.length}`} />
          <Row label={t("session.started")} value={activeSession.started_at ? new Date(activeSession.started_at).toLocaleString() : "-"} />
        </div>

        {/* Member list */}
        <div style={{ marginBottom: 16 }}>
          {activeSession.members.map(m => {
            const dev = devices.find(d => d.id === m.device_id);
            return (
              <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 0", borderBottom: "1px solid var(--b1)" }}>
                <div style={{ width: 7, height: 7, borderRadius: "50%", background: m.is_primary ? "var(--accent)" : "var(--teal)", flexShrink: 0 }} />
                <span style={{ flex: 1, fontSize: 13, color: "var(--t2)" }}>{dev?.name ?? m.device_id}</span>
                <span style={{ fontSize: 11, color: "var(--t5)" }}>{m.is_primary ? t("session.primary") : t("session.secondary")}</span>
              </div>
            );
          })}
        </div>

        {/* Layout editor */}
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t3)", marginBottom: 10 }}>
            {t("layout.title")}
          </div>
          <DeviceLayoutEditor
            devices={memberDevices}
            layout={activeSession.members.map(m => ({
              device_id:  m.device_id,
              position_x: m.position_x,
              position_y: m.position_y,
              width:      m.width,
              height:     m.height,
              enabled:    m.enabled,
            }))}
            primaryDeviceId={activeSession.primary_device_id}
            onChange={newLayout => void onUpdateLayout(activeSession.id, newLayout)}
          />
        </div>

        <button
          onClick={() => void onStopSession(activeSession.id)}
          style={{ ...dangerBtnStyle, width: "100%" }}
        >
          {t("session.stop")}
        </button>
      </div>
    );
  }

  // ── Create session view ────────────────────────────────────────────────────
  if (view === "create") {
    const selectedDevices = [
      ...(primaryId ? [devices.find(d => d.id === primaryId)!].filter(Boolean) : []),
      ...Array.from(selectedIds)
        .filter(id => id !== primaryId)
        .map(id => devices.find(d => d.id === id)!)
        .filter(Boolean),
    ];

    return (
      <div>
        <button onClick={() => setView("list")} style={backBtnStyle}>← {t("session.back")}</button>
        <h3 style={{ margin: "10px 0 16px", fontSize: 15, fontWeight: 700, color: "var(--t1)" }}>
          {t("session.createTitle")}
        </h3>

        {/* Primary device picker */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", display: "block", marginBottom: 6 }}>
            {t("session.selectPrimary")}
          </label>
          <select
            value={primaryId}
            onChange={e => { setPrimaryId(e.target.value); setSelectedIds(new Set()); }}
            style={selectStyle}
          >
            <option value="">{t("session.pickDevice")}</option>
            {onlineDevices.map(d => (
              <option key={d.id} value={d.id}>{d.name} ({d.platform})</option>
            ))}
          </select>
        </div>

        {/* Secondary device checkboxes */}
        {primaryId && (
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", display: "block", marginBottom: 8 }}>
              {t("session.selectSecondary")} ({selectedIds.size}/{MAX_DEVICES - 1})
            </label>
            {onlineDevices
              .filter(d => d.id !== primaryId)
              .map(d => (
                <label key={d.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", fontSize: 13, color: "var(--t3)", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(d.id)}
                    onChange={() => toggleDevice(d.id)}
                    style={{ accentColor: "var(--accent)" }}
                    disabled={!selectedIds.has(d.id) && selectedIds.size >= MAX_DEVICES - 1}
                  />
                  {d.name} <span style={{ color: "var(--t5)", fontSize: 11 }}>({d.platform})</span>
                </label>
              ))
            }
          </div>
        )}

        {/* Layout editor */}
        {selectedDevices.length >= 2 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 8 }}>{t("layout.title")}</div>
            <DeviceLayoutEditor
              devices={selectedDevices}
              layout={layout}
              primaryDeviceId={primaryId}
              onChange={setLayout}
            />
          </div>
        )}

        {error && (
          <div style={{ padding: "8px 12px", background: "rgba(231,76,60,0.1)", borderRadius: 7, color: "#e74c3c", fontSize: 13, marginBottom: 12 }}>
            {error}
          </div>
        )}

        <button
          onClick={() => void handleCreate()}
          disabled={creating || !primaryId || selectedIds.size === 0}
          style={{ ...primaryBtnStyle, width: "100%" }}
        >
          {creating ? t("session.creating") : t("session.create")}
        </button>
      </div>
    );
  }

  // ── Session list view ──────────────────────────────────────────────────────
  const pendingSessions = sessions.filter(s => s.status === "draft" || s.status === "starting");

  return (
    <div>
      <button
        onClick={() => setView("create")}
        disabled={onlineDevices.length < 2}
        style={{ ...primaryBtnStyle, width: "100%", marginBottom: 16 }}
        title={onlineDevices.length < 2 ? t("session.needTwoOnline") : ""}
      >
        + {t("session.newSession")}
      </button>

      {pendingSessions.length === 0 && (
        <div style={{ color: "var(--t5)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
          {t("session.noSessions")}
        </div>
      )}

      {pendingSessions.map(s => (
        <div key={s.id} style={{ background: "var(--bg-input)", border: "1px solid var(--b1)", borderRadius: 10, padding: "12px 14px", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
            <span style={{ flex: 1, fontSize: 14, fontWeight: 600, color: "var(--t2)" }}>
              {s.name ?? t("session.unnamed")} <span style={{ fontSize: 11, color: "var(--t5)" }}>{s.members.length} devices</span>
            </span>
            <button onClick={() => void onStartSession(s.id)} style={primaryBtnStyle}>
              {t("session.start")}
            </button>
          </div>
          <div style={{ fontSize: 11, color: "var(--t5)" }}>
            {t("session.created", { date: new Date(s.created_at).toLocaleString() })}
          </div>
        </div>
      ))}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "4px 0" }}>
      <span style={{ color: "var(--t4)" }}>{label}</span>
      <span style={{ color: "var(--t2)", fontWeight: 500 }}>{value}</span>
    </div>
  );
}

const primaryBtnStyle: React.CSSProperties = {
  background: "var(--accent)", color: "#fff",
  border: "none", borderRadius: 9, cursor: "pointer",
  padding: "9px 16px", fontSize: 13, fontWeight: 600,
  opacity: 1,
};

const dangerBtnStyle: React.CSSProperties = {
  background: "rgba(231,76,60,0.15)",
  color: "#e74c3c",
  border: "1px solid rgba(231,76,60,0.35)",
  borderRadius: 9, cursor: "pointer",
  padding: "9px 16px", fontSize: 13, fontWeight: 600,
};

const backBtnStyle: React.CSSProperties = {
  background: "none", border: "none",
  color: "var(--t4)", cursor: "pointer",
  fontSize: 13, padding: "4px 0",
};

const selectStyle: React.CSSProperties = {
  width: "100%",
  background: "var(--bg-input)", color: "var(--t2)",
  border: "1px solid var(--b1)", borderRadius: 8,
  padding: "8px 10px", fontSize: 13, outline: "none",
};
