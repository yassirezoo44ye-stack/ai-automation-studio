import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Device } from "./types/devices.types";

interface Props {
  device: Device;
  role?: "primary" | "secondary";   // set when device is in an active session
  selected?: boolean;
  onSelect?: () => void;
  onRevoke?: () => void;
  onDelete?: () => void;
}

const STATUS_DOT: Record<string, string> = {
  online:           "#2ecc71",
  offline:          "#555",
  connecting:       "#f39c12",
  revoked:          "#e74c3c",
  control_active:   "var(--accent)",
  control_disabled: "#666",
};

const STATUS_DOT_GLOW: Record<string, boolean> = {
  online:         true,
  control_active: true,
  connecting:     false,
  offline:        false,
  revoked:        false,
  control_disabled: false,
};

const STATUS_BG: Record<string, string> = {
  online:           "rgba(46,204,113,0.12)",
  offline:          "transparent",
  connecting:       "rgba(243,156,18,0.12)",
  revoked:          "rgba(231,76,60,0.08)",
  control_active:   "rgba(var(--accent-rgb,120,80,220),0.1)",
  control_disabled: "transparent",
};

export function DeviceCard({ device, role, selected, onSelect, onRevoke, onDelete }: Props) {
  const { t } = useTranslation("devices");
  const [hovered, setHovered] = useState(false);

  const dotColor  = STATUS_DOT[device.status] ?? "#555";
  const glowing   = STATUS_DOT_GLOW[device.status] ?? false;
  const isRevoked = device.status === "revoked";

  const borderColor = selected
    ? "var(--accent)"
    : hovered
    ? "var(--t5)"
    : "var(--b1)";

  const bgColor = selected
    ? "var(--bg-elevated, #1a1a2e)"
    : STATUS_BG[device.status] ?? "var(--card, #161622)";

  return (
    <div
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={onSelect}
      onKeyDown={onSelect ? e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } } : undefined}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      aria-pressed={selected}
      style={{
        background:   bgColor,
        border:       `1px solid ${borderColor}`,
        borderRadius: 12,
        padding:      "14px 16px",
        cursor:       onSelect ? "pointer" : "default",
        transition:   "border-color 0.15s, background 0.15s, box-shadow 0.15s",
        opacity:      isRevoked ? 0.55 : 1,
        boxShadow:    hovered && !isRevoked ? "0 2px 12px rgba(0,0,0,0.2)" : "none",
        outline:      "none",
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>

        {/* Status dot */}
        <div
          aria-hidden="true"
          style={{
            width: 8, height: 8, borderRadius: "50%",
            background: dotColor, flexShrink: 0,
            boxShadow: glowing ? `0 0 7px ${dotColor}` : "none",
            transition: "box-shadow 0.3s",
          }}
        />

        {/* Device name */}
        <span style={{
          fontWeight: 700, fontSize: 14, color: "var(--t1)", flex: 1,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {device.name}
        </span>

        {/* Role badge — only when device is in active session */}
        {role && (
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.04em",
            padding: "2px 7px", borderRadius: 20,
            background: role === "primary" ? "var(--accent)" : "rgba(46,204,113,0.2)",
            color:      role === "primary" ? "#fff" : "#2ecc71",
            flexShrink: 0,
          }}>
            {t(`role.${role}`)}
          </span>
        )}

        {/* Action buttons */}
        <div style={{ display: "flex", gap: 4 }}>
          {!isRevoked && onRevoke && (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onRevoke(); }}
              aria-label={t("devices.actions.revoke")}
              title={t("devices.actions.revoke")}
              style={btnStyle}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
              </svg>
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onDelete(); }}
              aria-label={t("devices.actions.delete")}
              title={t("devices.actions.delete")}
              style={{ ...btnStyle, color: "var(--err, #e74c3c)" }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Chips row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 8px" }}>
        <Chip label={t(`platform.${device.platform}`) || device.platform} />
        {device.hostname && <Chip label={device.hostname} />}
        <Chip label={t(`status.${device.status}`) || device.status} color={STATUS_BG_CHIP[device.status]} textColor={STATUS_TEXT_CHIP[device.status]} />
        {device.screen_width && device.screen_height && (
          <Chip label={`${device.screen_width}×${device.screen_height}`} />
        )}
        {device.agent_version && <Chip label={`v${device.agent_version}`} />}
      </div>

      {/* Last seen */}
      {device.last_seen_at && (
        <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 7 }}>
          {formatRelative(device.last_seen_at)}
        </div>
      )}

      {/* Online pulse indicator for active control */}
      {device.status === "control_active" && (
        <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
          <PulseDot />
          <span style={{ fontSize: 11, color: "var(--accent)", fontWeight: 600 }}>
            {t("status.control_active")}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Status chip color maps ──────────────────────────────────────────────────

const STATUS_BG_CHIP: Record<string, string | undefined> = {
  online:           "rgba(46,204,113,0.15)",
  offline:          undefined,
  connecting:       "rgba(243,156,18,0.15)",
  revoked:          "rgba(231,76,60,0.15)",
  control_active:   "rgba(var(--accent-rgb,120,80,220),0.15)",
  control_disabled: undefined,
};

const STATUS_TEXT_CHIP: Record<string, string | undefined> = {
  online:           "#2ecc71",
  offline:          undefined,
  connecting:       "#f5a623",
  revoked:          "#e74c3c",
  control_active:   "var(--accent)",
  control_disabled: undefined,
};

// ── Sub-components ─────────────────────────────────────────────────────────

function Chip({ label, color, textColor }: { label: string; color?: string; textColor?: string }) {
  return (
    <span style={{
      fontSize: 11, padding: "2px 8px",
      background: color ?? "var(--bg-input, #0d0d18)",
      borderRadius: 6,
      color: textColor ?? "var(--t4)",
      fontWeight: textColor ? 600 : 400,
    }}>
      {label}
    </span>
  );
}

function PulseDot() {
  return (
    <span style={{ position: "relative", display: "inline-block", width: 8, height: 8 }}>
      <style>{`
        @keyframes dev-card-pulse {
          0%   { transform: scale(1);   opacity: 0.8; }
          50%  { transform: scale(1.6); opacity: 0.3; }
          100% { transform: scale(1);   opacity: 0.8; }
        }
        @media (prefers-reduced-motion: reduce) {
          .dev-pulse-ring { display: none; }
        }
      `}</style>
      <span className="dev-pulse-ring" style={{
        position: "absolute", inset: -3,
        borderRadius: "50%",
        background: "var(--accent)",
        animation: "dev-card-pulse 1.6s ease-in-out infinite",
        opacity: 0.4,
      }} />
      <span style={{
        position: "absolute", inset: 0,
        borderRadius: "50%",
        background: "var(--accent)",
      }} />
    </span>
  );
}

const btnStyle: React.CSSProperties = {
  background: "none", border: "none",
  color: "var(--t4)", cursor: "pointer",
  padding: "3px 4px", borderRadius: 5,
  display: "flex", alignItems: "center",
  transition: "color 0.1s, background 0.1s",
};

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60)    return "just now";
  if (secs < 3600)  return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
