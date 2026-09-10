/**
 * Flow — Multi-Device Control Page
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
      // Apply initial layout immediately if user configured one
      if (layout.length > 0) {
        await updateLayout(session.id, layout);
      }
    },
    [createSession, updateLayout],
  );

  const loading = devLoading || sessLoading;
  const error   = devError   || sessError;

  return (
    <div style={{ padding: "24px 28px", height: "100%", overflowY: "auto" }}>

      {/* Page header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "var(--t1)" }}>
            {t("page.title")}
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--t4)" }}>
            {t("page.subtitle")}
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button onClick={refetch} style={iconBtnStyle} title={t("page.refresh")}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.2"/>
            </svg>
          </button>
          <button onClick={() => setShowEnrollModal(true)} style={primaryBtnStyle}>
            + {t("page.enrollDevice")}
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{ padding: "10px 14px", background: "rgba(231,76,60,0.1)", border: "1px solid rgba(231,76,60,0.2)", borderRadius: 10, color: "#e74c3c", fontSize: 13, marginBottom: 18 }}>
          {error}
        </div>
      )}

      {/* Two-column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20, alignItems: "start" }}>

        {/* ── Left: Device list ───────────────────────────────────────────── */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t5)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 12 }}>
            {t("devices.title")} ({devices.length})
          </div>

          {loading && (
            <div style={{ color: "var(--t5)", fontSize: 13, textAlign: "center", padding: "30px 0" }}>
              {t("devices.loading")}
            </div>
          )}

          {!loading && devices.length === 0 && (
            <div style={{ color: "var(--t5)", fontSize: 13, textAlign: "center", padding: "40px 0" }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>🖥️</div>
              <div style={{ marginBottom: 8 }}>{t("devices.empty")}</div>
              <button onClick={() => setShowEnrollModal(true)} style={primaryBtnStyle}>
                {t("page.enrollDevice")}
              </button>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {devices.map(device => (
              <DeviceCard
                key={device.id}
                device={device}
                onRevoke={device.status !== "revoked"
                  ? () => setConfirmRevoke(device.id)
                  : undefined}
                onDelete={() => setConfirmDelete(device.id)}
              />
            ))}
          </div>
        </div>

        {/* ── Right: Session control panel ────────────────────────────────── */}
        <div style={{
          background:   "var(--card, #161622)",
          border:       "1px solid var(--b1)",
          borderRadius: 14,
          padding:      "18px 20px",
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t5)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 14 }}>
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
          onConfirm={async () => {
            await revokeDevice(confirmRevoke);
            setConfirmRevoke(null);
          }}
          onCancel={() => setConfirmRevoke(null)}
          danger
        />
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <ConfirmDialog
          message={t("confirm.delete")}
          onConfirm={async () => {
            await deleteDevice(confirmDelete);
            setConfirmDelete(null);
          }}
          onCancel={() => setConfirmDelete(null)}
          danger
        />
      )}
    </div>
  );
}

// ── Minimal confirm dialog ────────────────────────────────────────────────────

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
    <div style={{
      position: "fixed", inset: 0, zIndex: 1100,
      background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: "var(--card)", border: "1px solid var(--b1)",
        borderRadius: 14, padding: "24px 26px",
        width: 360, boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
      }}>
        <p style={{ margin: "0 0 20px", fontSize: 14, color: "var(--t2)", lineHeight: 1.5 }}>{message}</p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onCancel} style={secondaryBtnStyle}>{t("confirm.cancel")}</button>
          <button onClick={() => void confirm()} disabled={loading} style={danger ? dangerBtnStyle : primaryBtnStyle}>
            {loading ? "…" : t("confirm.ok")}
          </button>
        </div>
      </div>
    </div>
  );
}

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
};
