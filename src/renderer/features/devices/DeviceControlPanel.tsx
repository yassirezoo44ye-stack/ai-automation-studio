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
import type { Device, DeviceSession, LayoutEntry, SessionStatus } from "./types/devices.types";
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

const SESSION_STATUS_COLOR: Record<SessionStatus, string> = {
  draft:    "var(--t5)",
  starting: "#f5a623",
  active:   "#2ecc71",
  stopping: "#f5a623",
  stopped:  "var(--t5)",
  expired:  "#888",
  failed:   "#e74c3c",
};

const SESSION_STATUS_BG: Record<SessionStatus, string> = {
  draft:    "rgba(100,100,100,0.1)",
  starting: "rgba(245,166,35,0.12)",
  active:   "rgba(46,204,113,0.12)",
  stopping: "rgba(245,166,35,0.12)",
  stopped:  "rgba(100,100,100,0.1)",
  expired:  "rgba(100,100,100,0.08)",
  failed:   "rgba(231,76,60,0.12)",
};

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
    const memberDevices = activeSession.members
      .map(m => devices.find(d => d.id === m.device_id))
      .filter(Boolean) as Device[];

    return (
      <div>
        {/* Active header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
          <ActivePulse />
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--t1)" }}>
            {t("session.activeTitle")}
          </h3>
        </div>

        {/* Session info card */}
        <div style={{ background: "var(--bg-input)", borderRadius: 10, padding: 14, marginBottom: 14 }}>
          <Row label={t("session.primary")} value={primaryDevice?.name ?? "-"} />
          <Row label={t("session.devices")} value={t("session.memberCount", { count: activeSession.members.length })} />
          <Row
            label={t("session.started")}
            value={activeSession.started_at ? new Date(activeSession.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "-"}
          />
        </div>

        {/* Member list */}
        <div style={{ marginBottom: 16 }}>
          {activeSession.members.map(m => {
            const dev = devices.find(d => d.id === m.device_id);
            return (
              <div key={m.id} style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 0", borderBottom: "1px solid var(--b1)",
              }}>
                <div style={{
                  width: 7, height: 7, borderRadius: "50%",
                  background: m.is_primary ? "var(--accent)" : "#2ecc71",
                  flexShrink: 0,
                }} />
                <span style={{ flex: 1, fontSize: 13, color: "var(--t2)" }}>
                  {dev?.name ?? m.device_id}
                </span>
                <span style={{
                  fontSize: 10, fontWeight: 700, letterSpacing: "0.03em",
                  padding: "1px 6px", borderRadius: 10,
                  background: m.is_primary ? "rgba(var(--accent-rgb,120,80,220),0.15)" : "rgba(46,204,113,0.12)",
                  color: m.is_primary ? "var(--accent)" : "#2ecc71",
                }}>
                  {m.is_primary ? t("session.primary") : t("session.secondary")}
                </span>
              </div>
            );
          })}
        </div>

        {/* Layout editor */}
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t4)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
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
          type="button"
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
        <button type="button" onClick={() => setView("list")} style={backBtnStyle}>
          ← {t("session.back")}
        </button>
        <h3 style={{ margin: "10px 0 16px", fontSize: 15, fontWeight: 700, color: "var(--t1)" }}>
          {t("session.createTitle")}
        </h3>

        {/* Primary device picker */}
        <div style={{ marginBottom: 14 }}>
          <label htmlFor="primary-select" style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", display: "block", marginBottom: 6 }}>
            {t("session.selectPrimary")}
          </label>
          <select
            id="primary-select"
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
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 8 }}>
              {t("session.selectSecondary")} ({selectedIds.size}/{MAX_DEVICES - 1})
            </div>
            {onlineDevices
              .filter(d => d.id !== primaryId)
              .map(d => (
                <label key={d.id} style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "5px 0",
                  fontSize: 13, color: "var(--t3)", cursor: "pointer",
                }}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(d.id)}
                    onChange={() => toggleDevice(d.id)}
                    style={{ accentColor: "var(--accent)" }}
                    disabled={!selectedIds.has(d.id) && selectedIds.size >= MAX_DEVICES - 1}
                  />
                  {d.name}
                  <span style={{ color: "var(--t5)", fontSize: 11 }}>({d.platform})</span>
                </label>
              ))
            }
          </div>
        )}

        {/* Layout editor */}
        {selectedDevices.length >= 2 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {t("layout.title")}
            </div>
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
          type="button"
          onClick={() => void handleCreate()}
          disabled={creating || !primaryId || selectedIds.size === 0}
          style={{
            ...primaryBtnStyle, width: "100%",
            opacity: (creating || !primaryId || selectedIds.size === 0) ? 0.5 : 1,
            cursor:  (creating || !primaryId || selectedIds.size === 0) ? "not-allowed" : "pointer",
          }}
        >
          {creating ? t("session.creating") : t("session.create")}
        </button>
      </div>
    );
  }

  // ── Session list view ──────────────────────────────────────────────────────
  const actionableSessions  = sessions.filter(s => s.status === "draft" || s.status === "starting");
  const historySessions     = sessions.filter(s => s.status === "stopped" || s.status === "expired" || s.status === "failed" || s.status === "stopping");

  return (
    <div>
      <button
        type="button"
        onClick={() => setView("create")}
        disabled={onlineDevices.length < 2}
        style={{
          ...primaryBtnStyle, width: "100%", marginBottom: 16,
          opacity: onlineDevices.length < 2 ? 0.45 : 1,
          cursor:  onlineDevices.length < 2 ? "not-allowed" : "pointer",
        }}
        title={onlineDevices.length < 2 ? t("session.needTwoOnline") : ""}
        aria-disabled={onlineDevices.length < 2}
      >
        + {t("session.newSession")}
      </button>

      {/* Actionable sessions */}
      {actionableSessions.length === 0 && historySessions.length === 0 && (
        <div style={{ color: "var(--t5)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
          {t("session.noSessions")}
        </div>
      )}

      {actionableSessions.map(s => (
        <SessionCard
          key={s.id}
          session={s}
          devices={devices}
          onStart={() => void onStartSession(s.id)}
        />
      ))}

      {/* Session history */}
      {historySessions.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t5)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>
            {t("session.historyTitle")}
          </div>
          {historySessions.map(s => (
            <SessionCard key={s.id} session={s} devices={devices} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Session card ──────────────────────────────────────────────────────────────

function SessionCard({
  session, devices, onStart,
}: {
  session: DeviceSession;
  devices: Device[];
  onStart?: () => void;
}) {
  const { t } = useTranslation("devices");
  const primaryDevice = devices.find(d => d.id === session.primary_device_id);
  const statusColor = SESSION_STATUS_COLOR[session.status] ?? "var(--t5)";
  const statusBg    = SESSION_STATUS_BG[session.status]    ?? "transparent";
  const canStart    = session.status === "draft";

  return (
    <div style={{
      background: "var(--bg-input)",
      border: "1px solid var(--b1)",
      borderRadius: 10, padding: "12px 14px", marginBottom: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 8 }}>
        <span style={{ flex: 1, fontSize: 14, fontWeight: 600, color: "var(--t2)" }}>
          {session.name ?? t("session.unnamed")}
        </span>
        {/* Status pill */}
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: "0.04em",
          padding: "2px 8px", borderRadius: 10,
          background: statusBg, color: statusColor,
        }}>
          {t(`session.status.${session.status}`) || session.status}
        </span>
        {canStart && onStart && (
          <button type="button" onClick={onStart} style={primaryBtnStyle}>
            {t("session.start")}
          </button>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--t4)" }}>
        {primaryDevice?.name && (
          <span style={{ marginRight: 10 }}>↗ {primaryDevice.name}</span>
        )}
        <span style={{ color: "var(--t5)" }}>
          {t("session.memberCount", { count: session.members.length })}
        </span>
      </div>
      <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 4 }}>
        {t("session.created", { date: new Date(session.created_at).toLocaleString() })}
      </div>
    </div>
  );
}

// ── Animated "active" pulse indicator ────────────────────────────────────────

function ActivePulse() {
  return (
    <span style={{ position: "relative", display: "inline-block", width: 12, height: 12 }}>
      <style>{`
        @keyframes session-pulse {
          0%   { transform: scale(1);   opacity: 0.7; }
          60%  { transform: scale(2.2); opacity: 0; }
          100% { transform: scale(1);   opacity: 0; }
        }
        @media (prefers-reduced-motion: reduce) {
          .session-pulse-ring { display: none; }
        }
      `}</style>
      <span className="session-pulse-ring" style={{
        position: "absolute", inset: 0, borderRadius: "50%",
        background: "#2ecc71",
        animation: "session-pulse 1.5s ease-out infinite",
      }} />
      <span style={{ position: "absolute", inset: 2, borderRadius: "50%", background: "#2ecc71" }} />
    </span>
  );
}

// ── Row helper ────────────────────────────────────────────────────────────────

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "4px 0" }}>
      <span style={{ color: "var(--t4)" }}>{label}</span>
      <span style={{ color: "var(--t2)", fontWeight: 500 }}>{value}</span>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const primaryBtnStyle: React.CSSProperties = {
  background: "var(--accent)", color: "#fff",
  border: "none", borderRadius: 9, cursor: "pointer",
  padding: "8px 14px", fontSize: 13, fontWeight: 600,
  flexShrink: 0,
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
