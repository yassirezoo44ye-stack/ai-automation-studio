/**
 * Flow — Multi-Device Control Page  (PRO MAX)
 *
 * Layout: two-column on wide screens, stacked on narrow.
 *   Left:  Device list with enrollment CTA
 *   Right: Session control panel
 *
 * SECURITY NOTE:
 *   The browser UI NEVER captures global OS input or WebSocket-level
 *   device traffic. All of that lives in the native Device Agent.
 *   This page only manages device registry, sessions, and layout via REST.
 */
import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useDevices } from "./hooks/useDevices";
import { useDeviceSession } from "./hooks/useDeviceSession";
import { DeviceCard } from "./DeviceCard";
import { DeviceRegistrationModal } from "./DeviceRegistrationModal";
import { DeviceControlPanel } from "./DeviceControlPanel";
import type { LayoutEntry } from "./types/devices.types";

// ── Responsive + animation styles (injected once) ────────────────────────────

const PAGE_STYLES = `
  .mdc-grid {
    display: grid;
    grid-template-columns: 1fr 340px;
    gap: 20px;
    align-items: start;
  }
  @media (max-width: 840px) {
    .mdc-grid {
      grid-template-columns: 1fr;
    }
    .mdc-panel-right {
      order: -1;
    }
  }
  @keyframes mdc-shimmer {
    0%   { background-position: -400px 0; }
    100% { background-position: 400px 0; }
  }
  @keyframes mdc-fadein {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .mdc-skeleton { animation: none !important; }
    .mdc-fadein   { animation: none !important; }
  }
  .mdc-skeleton {
    background: linear-gradient(90deg, var(--bg-input) 25%, var(--b1) 50%, var(--bg-input) 75%);
    background-size: 800px 100%;
    animation: mdc-shimmer 1.4s infinite linear;
    border-radius: 8px;
  }
  .mdc-fadein {
    animation: mdc-fadein 0.22s ease both;
  }
  .mdc-icon-btn:hover {
    background: var(--b1) !important;
    color: var(--t2) !important;
  }
  .mdc-icon-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .mdc-primary-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
`;

export function DevicesPage() {
  const { t } = useTranslation("devices");
  const {
    devices, loading: devLoading, error: devError,
    refetch, revokeDevice, deleteDevice,
  } = useDevices();

  const {
    sessions, activeSession, loading: sessLoading, error: sessError,
    createSession, startSession, stopSession, updateLayout,
  } = useDeviceSession();

  const [showEnrollModal, setShowEnrollModal] = useState(false);
  const [confirmRevoke,   setConfirmRevoke]   = useState<string | null>(null);
  const [confirmDelete,   setConfirmDelete]   = useState<string | null>(null);

  const handleCreateSession = useCallback(
    async (primaryId: string, deviceIds: string[], layout: LayoutEntry[]) => {
      const session = await createSession({ primary_device_id: primaryId, device_ids: deviceIds });
      if (layout.length > 0) await updateLayout(session.id, layout);
    },
    [createSession, updateLayout],
  );

  const loading = devLoading || sessLoading;
  const error   = devError   || sessError;

  // Derive role map from active session
  const roleMap = new Map<string, "primary" | "secondary">();
  if (activeSession) {
    activeSession.members.forEach(m => {
      roleMap.set(m.device_id, m.is_primary ? "primary" : "secondary");
    });
  }

  const onlineCount = devices.filter(d => d.status === "online" || d.status === "control_active").length;

  return (
    <div style={{ padding: "24px 28px", height: "100%", overflowY: "auto", overflowX: "hidden" }}>
      <style>{PAGE_STYLES}</style>

      {/* ── Page header ─────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 20 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "var(--t1)" }}>
              {t("page.title")}
            </h1>
            {onlineCount > 0 && !loading && (
              <span style={{
                fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
                background: "rgba(46,204,113,0.15)", color: "#2ecc71",
                letterSpacing: "0.03em",
              }}>
                {onlineCount} online
              </span>
            )}
          </div>
          <p style={{ margin: 0, fontSize: 13, color: "var(--t4)" }}>
            {t("page.subtitle")}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <button
            type="button"
            onClick={refetch}
            className="mdc-icon-btn"
            style={iconBtnStyle}
            aria-label={t("page.refresh")}
            title={t("page.refresh")}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.2"/>
            </svg>
          </button>
          <button
            type="button"
            onClick={() => setShowEnrollModal(true)}
            className="mdc-primary-btn"
            style={primaryBtnStyle}
          >
            + {t("page.enrollDevice")}
          </button>
        </div>
      </div>

      {/* ── Topology strip ─────────────────────────────────────────────────── */}
      <TopologyStrip activeCount={onlineCount} total={devices.length} hint={t("topology.hint")} />

      {/* ── Error banner ────────────────────────────────────────────────────── */}
      {error && (
        <div className="mdc-fadein" style={{
          padding: "10px 14px",
          background: "rgba(231,76,60,0.08)", border: "1px solid rgba(231,76,60,0.2)",
          borderRadius: 10, color: "#e74c3c", fontSize: 13, marginBottom: 18,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}

      {/* ── Two-column grid ─────────────────────────────────────────────────── */}
      <div className="mdc-grid">

        {/* Left: Device list */}
        <div>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "var(--t5)",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 14,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            {t("devices.title")}
            {!loading && (
              <span style={{
                fontSize: 11, fontWeight: 700, padding: "1px 7px",
                background: "var(--bg-input)", borderRadius: 8, color: "var(--t4)",
              }}>
                {devices.length}
              </span>
            )}
          </div>

          {/* Skeleton loading */}
          {loading && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[1, 2, 3].map(i => (
                <div key={i} className="mdc-skeleton" style={{ height: 82, borderRadius: 12 }} />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && devices.length === 0 && (
            <div className="mdc-fadein" style={{
              color: "var(--t5)", textAlign: "center", padding: "44px 20px",
              border: "1px dashed var(--b1)", borderRadius: 14,
            }}>
              <MonitorIcon />
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t4)", marginBottom: 6, marginTop: 16 }}>
                {t("devices.empty")}
              </div>
              <div style={{ fontSize: 12, color: "var(--t5)", marginBottom: 20, lineHeight: 1.5 }}>
                {t("devices.emptyHint")}
              </div>
              <button
                type="button"
                onClick={() => setShowEnrollModal(true)}
                className="mdc-primary-btn"
                style={primaryBtnStyle}
              >
                {t("page.enrollDevice")}
              </button>
            </div>
          )}

          {/* Device list */}
          {!loading && devices.length > 0 && (
            <div className="mdc-fadein" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {devices.map(device => (
                <DeviceCard
                  key={device.id}
                  device={device}
                  role={roleMap.get(device.id)}
                  onRevoke={device.status !== "revoked"
                    ? () => setConfirmRevoke(device.id)
                    : undefined}
                  onDelete={() => setConfirmDelete(device.id)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: Session control panel */}
        <div className="mdc-panel-right" style={{
          background:   "var(--card, #161622)",
          border:       "1px solid var(--b1)",
          borderRadius: 14,
          padding:      "18px 20px",
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "var(--t5)",
            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 16,
          }}>
            {t("session.title")}
          </div>

          <DeviceControlPanel
            devices={devices}
            sessions={sessions}
            activeSession={activeSession}
            onCreateSession={handleCreateSession}
            onStartSession={startSession}
            onStopSession={stopSession}
            onUpdateLayout={updateLayout}
          />
        </div>
      </div>

      {/* Enrollment modal */}
      {showEnrollModal && (
        <DeviceRegistrationModal
          onClose={() => { setShowEnrollModal(false); void refetch(); }}
        />
      )}

      {/* Revoke confirmation */}
      {confirmRevoke && (
        <ConfirmDialog
          message={t("confirm.revoke")}
          onConfirm={async () => { await revokeDevice(confirmRevoke); setConfirmRevoke(null); }}
          onCancel={() => setConfirmRevoke(null)}
          danger
        />
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <ConfirmDialog
          message={t("confirm.delete")}
          onConfirm={async () => { await deleteDevice(confirmDelete); setConfirmDelete(null); }}
          onCancel={() => setConfirmDelete(null)}
          danger
        />
      )}
    </div>
  );
}

// ── Topology strip ────────────────────────────────────────────────────────────

function TopologyStrip({ activeCount, total, hint }: { activeCount: number; total: number; hint: string }) {
  return (
    <div style={{
      marginBottom: 22,
      padding: "14px 18px",
      background: "var(--card)",
      border: "1px solid var(--b1)",
      borderRadius: 12,
      display: "flex",
      alignItems: "center",
      gap: 20,
    }}>
      {/* SVG diagram */}
      <svg
        width="220"
        height="48"
        viewBox="0 0 220 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
        style={{ flexShrink: 0 }}
      >
        {/* Secondary left */}
        <rect x="2" y="10" width="48" height="28" rx="5" stroke="var(--b1)" strokeWidth="1.5" fill="var(--bg-input)"/>
        <rect x="8" y="14" width="36" height="20" rx="2" stroke="var(--t5)" strokeWidth="1" fill="none" opacity="0.5"/>
        <line x1="18" y1="38" x2="32" y2="38" stroke="var(--t5)" strokeWidth="1.5" strokeLinecap="round" opacity="0.5"/>
        {/* Arrow left to center */}
        <line x1="52" y1="24" x2="74" y2="24" stroke="var(--b1)" strokeWidth="1.5" strokeDasharray="3 3"/>
        <polyline points="68,20 74,24 68,28" stroke="var(--b1)" strokeWidth="1.5" strokeLinejoin="round" fill="none"/>
        {/* Primary center */}
        <rect x="76" y="6" width="68" height="36" rx="6" stroke="var(--accent)" strokeWidth="2" fill="rgba(var(--accent-rgb,120,80,220),0.08)"/>
        <rect x="82" y="10" width="56" height="26" rx="3" stroke="var(--accent)" strokeWidth="1" fill="none" opacity="0.4"/>
        <line x1="96" y1="42" x2="124" y2="42" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" opacity="0.6"/>
        <circle cx="110" cy="24" r="4" fill="var(--accent)" opacity="0.8"/>
        {/* Arrow center to right */}
        <line x1="146" y1="24" x2="168" y2="24" stroke="var(--b1)" strokeWidth="1.5" strokeDasharray="3 3"/>
        <polyline points="162,20 168,24 162,28" stroke="var(--b1)" strokeWidth="1.5" strokeLinejoin="round" fill="none"/>
        {/* Secondary right */}
        <rect x="170" y="10" width="48" height="28" rx="5" stroke="var(--b1)" strokeWidth="1.5" fill="var(--bg-input)"/>
        <rect x="176" y="14" width="36" height="20" rx="2" stroke="var(--t5)" strokeWidth="1" fill="none" opacity="0.5"/>
        <line x1="186" y1="38" x2="200" y2="38" stroke="var(--t5)" strokeWidth="1.5" strokeLinecap="round" opacity="0.5"/>
        {/* Labels */}
        <text x="26" y="52" textAnchor="middle" fontSize="8" fill="var(--t5)" fontFamily="system-ui">SEC</text>
        <text x="110" y="52" textAnchor="middle" fontSize="8" fill="var(--accent)" fontFamily="system-ui" fontWeight="700">PRIMARY</text>
        <text x="194" y="52" textAnchor="middle" fontSize="8" fill="var(--t5)" fontFamily="system-ui">SEC</text>
      </svg>

      {/* Text */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.5 }}>{hint}</div>
        {total > 0 && (
          <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 4 }}>
            {activeCount > 0
              ? `${activeCount} of ${total} device${total !== 1 ? "s" : ""} online`
              : `${total} device${total !== 1 ? "s" : ""} enrolled`
            }
          </div>
        )}
      </div>
    </div>
  );
}

// ── Empty state monitor icon ──────────────────────────────────────────────────

function MonitorIcon() {
  return (
    <svg width="52" height="52" viewBox="0 0 52 52" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style={{ margin: "0 auto", display: "block" }}>
      <rect x="4" y="6" width="44" height="30" rx="4" stroke="var(--b1)" strokeWidth="2" fill="var(--bg-input)"/>
      <rect x="8" y="10" width="36" height="22" rx="2" fill="var(--card)" stroke="var(--b1)" strokeWidth="1"/>
      {/* Screen lines */}
      <line x1="14" y1="16" x2="38" y2="16" stroke="var(--b1)" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="14" y1="21" x2="30" y2="21" stroke="var(--b1)" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="14" y1="26" x2="34" y2="26" stroke="var(--b1)" strokeWidth="1.5" strokeLinecap="round"/>
      {/* Stand */}
      <line x1="26" y1="36" x2="26" y2="44" stroke="var(--b1)" strokeWidth="2" strokeLinecap="round"/>
      <line x1="18" y1="44" x2="34" y2="44" stroke="var(--b1)" strokeWidth="2" strokeLinecap="round"/>
      {/* Plus badge */}
      <circle cx="40" cy="40" r="10" fill="var(--card)" stroke="var(--b1)" strokeWidth="1.5"/>
      <line x1="40" y1="35" x2="40" y2="45" stroke="var(--t4)" strokeWidth="2" strokeLinecap="round"/>
      <line x1="35" y1="40" x2="45" y2="40" stroke="var(--t4)" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  );
}

// ── Confirm dialog ────────────────────────────────────────────────────────────

function ConfirmDialog({
  message, onConfirm, onCancel, danger,
}: { message: string; onConfirm: () => Promise<void>; onCancel: () => void; danger?: boolean }) {
  const { t } = useTranslation("devices");
  const [loading, setLoading] = useState(false);

  const confirm = async () => {
    setLoading(true);
    try { await onConfirm(); } finally { setLoading(false); }
  };

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1100,
        background: "rgba(0,0,0,0.65)",
        display: "flex", alignItems: "center", justifyContent: "center",
        backdropFilter: "blur(2px)",
      }}
      role="alertdialog"
      aria-modal="true"
    >
      <div style={{
        background: "var(--card)", border: "1px solid var(--b1)",
        borderRadius: 14, padding: "24px 26px",
        width: 360, boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
      }}>
        <p style={{ margin: "0 0 20px", fontSize: 14, color: "var(--t2)", lineHeight: 1.6 }}>
          {message}
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" onClick={onCancel} style={secondaryBtnStyle}>
            {t("confirm.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void confirm()}
            disabled={loading}
            style={danger ? dangerBtnStyle : primaryBtnStyle}
          >
            {loading ? "…" : t("confirm.ok")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Button styles ─────────────────────────────────────────────────────────────

const primaryBtnStyle: React.CSSProperties = {
  background: "var(--accent)", color: "#fff",
  border: "none", borderRadius: 9, cursor: "pointer",
  padding: "9px 16px", fontSize: 13, fontWeight: 600,
};

const secondaryBtnStyle: React.CSSProperties = {
  background: "var(--bg-input)", color: "var(--t3)",
  border: "1px solid var(--b1)", borderRadius: 9, cursor: "pointer",
  padding: "9px 16px", fontSize: 13,
};

const dangerBtnStyle: React.CSSProperties = {
  background: "#e74c3c", color: "#fff",
  border: "none", borderRadius: 9, cursor: "pointer",
  padding: "9px 16px", fontSize: 13, fontWeight: 600,
};

const iconBtnStyle: React.CSSProperties = {
  background: "var(--bg-input)", color: "var(--t4)",
  border: "1px solid var(--b1)", borderRadius: 8, cursor: "pointer",
  padding: "8px", display: "flex", alignItems: "center", justifyContent: "center",
  transition: "background 0.15s, color 0.15s",
};
