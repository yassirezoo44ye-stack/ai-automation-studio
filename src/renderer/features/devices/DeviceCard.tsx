import type { Device } from "./types/devices.types";

const STATUS_COLOR: Record<string, string> = {
  online:           "var(--teal)",
  offline:          "var(--t5)",
  connecting:       "#f5a623",
  revoked:          "var(--err, #e74c3c)",
  control_active:   "var(--accent)",
  control_disabled: "var(--t5)",
};

const STATUS_DOT: Record<string, string> = {
  online:           "#2ecc71",
  offline:          "#666",
  connecting:       "#f39c12",
  revoked:          "#e74c3c",
  control_active:   "var(--accent)",
  control_disabled: "#888",
};

const PLATFORM_LABEL: Record<string, string> = {
  windows: "Windows",
  macos:   "macOS",
  linux:   "Linux",
  unknown: "Unknown",
};

interface Props {
  device: Device;
  selected?: boolean;
  onSelect?: () => void;
  onRevoke?: () => void;
  onDelete?: () => void;
}

export function DeviceCard({ device, selected, onSelect, onRevoke, onDelete }: Props) {
  const dotColor = STATUS_DOT[device.status] ?? "#666";
  const isRevoked = device.status === "revoked";
  const isOnline  = device.status === "online" || device.status === "control_active";

  return (
    <div
      onClick={onSelect}
      style={{
        background:    selected ? "var(--bg-elevated, #1a1a2e)" : "var(--card, #161622)",
        border:        `1px solid ${selected ? "var(--accent)" : "var(--b1)"}`,
        borderRadius:  12,
        padding:       "14px 16px",
        cursor:        onSelect ? "pointer" : "default",
        transition:    "border-color 0.15s, background 0.15s",
        opacity:       isRevoked ? 0.55 : 1,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        {/* Status dot */}
        <div style={{
          width: 8, height: 8, borderRadius: "50%",
          background: dotColor, flexShrink: 0,
          boxShadow: isOnline ? `0 0 6px ${dotColor}` : "none",
        }} />

        {/* Name */}
        <span style={{ fontWeight: 700, fontSize: 14, color: "var(--t1)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {device.name}
        </span>

        {/* Actions */}
        <div style={{ display: "flex", gap: 4 }}>
          {!isRevoked && onRevoke && (
            <button
              onClick={e => { e.stopPropagation(); onRevoke(); }}
              title="Revoke device"
              style={btnStyle}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
              </svg>
            </button>
          )}
          {onDelete && (
            <button
              onClick={e => { e.stopPropagation(); onDelete(); }}
              title="Delete device"
              style={{ ...btnStyle, color: "var(--err, #e74c3c)" }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Details */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}>
        <Chip label={PLATFORM_LABEL[device.platform] ?? device.platform} />
        {device.hostname && <Chip label={device.hostname} />}
        <Chip
          label={STATUS_LABEL[device.status] ?? device.status}
          color={STATUS_COLOR[device.status]}
        />
        {device.screen_width && device.screen_height && (
          <Chip label={`${device.screen_width}×${device.screen_height}`} />
        )}
        {device.agent_version && <Chip label={`v${device.agent_version}`} />}
      </div>

      {/* Last seen */}
      {device.last_seen_at && (
        <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 6 }}>
          {formatRelative(device.last_seen_at)}
        </div>
      )}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  online:           "Online",
  offline:          "Offline",
  connecting:       "Connecting…",
  revoked:          "Revoked",
  control_active:   "Control Active",
  control_disabled: "Control Off",
};

function Chip({ label, color }: { label: string; color?: string }) {
  return (
    <span style={{
      fontSize: 11, padding: "2px 7px",
      background: "var(--bg-input, #0d0d18)",
      borderRadius: 6,
      color: color ?? "var(--t4)",
    }}>
      {label}
    </span>
  );
}

const btnStyle: React.CSSProperties = {
  background: "none", border: "none",
  color: "var(--t4)", cursor: "pointer",
  padding: "3px 4px", borderRadius: 5,
  display: "flex", alignItems: "center",
  transition: "color 0.1s",
};

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60)  return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
