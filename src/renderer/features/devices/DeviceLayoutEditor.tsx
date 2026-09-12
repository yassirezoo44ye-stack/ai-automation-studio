/**
 * Device Layout Editor
 *
 * Renders a virtual canvas where devices can be dragged to set their
 * relative positions. Each device is shown as a rectangle proportional
 * to its configured screen resolution.
 *
 * The layout is stored as (position_x, position_y, width, height) per device,
 * in virtual canvas pixels (not physical screen pixels).
 */
import { useRef, useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { Device, LayoutEntry } from "./types/devices.types";

interface Props {
  devices: Device[];                        // all candidate devices
  layout: LayoutEntry[];                    // current layout config
  primaryDeviceId: string;
  onChange: (layout: LayoutEntry[]) => void;
}

const CANVAS_H  = 260;
const DEV_SCALE = 0.1;   // 1920×1080 → 192×108 in canvas at 100%

function resolveEntry(device: Device, layout: LayoutEntry[]): LayoutEntry {
  const existing = layout.find(e => e.device_id === device.id);
  return existing ?? {
    device_id:  device.id,
    position_x: 0,
    position_y: 0,
    width:      device.screen_width  ?? 1920,
    height:     device.screen_height ?? 1080,
    enabled:    true,
  };
}

export function DeviceLayoutEditor({ devices, layout, primaryDeviceId, onChange }: Props) {
  const { t } = useTranslation("devices");
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef    = useRef<HTMLDivElement>(null);

  // Track actual canvas width so we scale device rects proportionally
  const [canvasW, setCanvasW] = useState(480);

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(entries => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setCanvasW(Math.floor(w));
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const [dragging,    setDragging]    = useState<string | null>(null);
  const [dragOffset,  setDragOffset]  = useState({ ox: 0, oy: 0 });

  const entries = devices.map(d => resolveEntry(d, layout));

  const onMouseDown = useCallback((deviceId: string, e: React.MouseEvent) => {
    e.preventDefault();
    const entry = entries.find(en => en.device_id === deviceId);
    if (!entry || !canvasRef.current) return;
    const rect  = canvasRef.current.getBoundingClientRect();
    const scale = canvasW / 540;   // relative to reference canvas width
    const scaledX = entry.position_x * DEV_SCALE * scale;
    const scaledY = entry.position_y * DEV_SCALE * scale;
    setDragging(deviceId);
    setDragOffset({
      ox: e.clientX - rect.left - scaledX,
      oy: e.clientY - rect.top  - scaledY,
    });
  }, [entries, canvasW]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging || !canvasRef.current) return;
    const rect  = canvasRef.current.getBoundingClientRect();
    const scale = canvasW / 540;
    const rawX  = (e.clientX - rect.left - dragOffset.ox) / (DEV_SCALE * scale);
    const rawY  = (e.clientY - rect.top  - dragOffset.oy) / (DEV_SCALE * scale);
    const newLayout = entries.map(en =>
      en.device_id === dragging
        ? { ...en, position_x: Math.max(0, Math.round(rawX)), position_y: Math.max(0, Math.round(rawY)) }
        : en
    );
    onChange(newLayout);
  }, [dragging, dragOffset, entries, onChange, canvasW]);

  const onMouseUp = useCallback(() => setDragging(null), []);

  // Attach mouseup to window so dragging stops even if mouse is released outside canvas
  useEffect(() => {
    window.addEventListener("mouseup", onMouseUp);
    return () => window.removeEventListener("mouseup", onMouseUp);
  }, [onMouseUp]);

  const toggleDevice = useCallback((deviceId: string) => {
    if (deviceId === primaryDeviceId) return;   // Primary cannot be disabled
    const newLayout = entries.map(en =>
      en.device_id === deviceId ? { ...en, enabled: !en.enabled } : en
    );
    onChange(newLayout);
  }, [entries, primaryDeviceId, onChange]);

  const scale = canvasW / 540;

  return (
    <div ref={containerRef}>
      <div style={{ fontSize: 12, color: "var(--t4)", marginBottom: 10 }}>
        {t("layout.dragHint")}
      </div>

      {/* Canvas */}
      <div
        ref={canvasRef}
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseUp}
        style={{
          position:   "relative",
          width:      "100%",
          height:     CANVAS_H,
          background: "var(--bg-input)",
          borderRadius: 10,
          border:     "1px solid var(--b1)",
          overflow:   "hidden",
          userSelect: "none",
        }}
      >
        {/* Subtle grid */}
        <div style={{
          position: "absolute", inset: 0,
          backgroundImage: "radial-gradient(circle, var(--b1) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
          opacity: 0.5,
          pointerEvents: "none",
        }} />

        {entries.map(en => {
          const device    = devices.find(d => d.id === en.device_id);
          if (!device) return null;
          const w         = en.width  * DEV_SCALE * scale;
          const h         = en.height * DEV_SCALE * scale;
          const x         = en.position_x * DEV_SCALE * scale;
          const y         = en.position_y * DEV_SCALE * scale;
          const isPrimary = en.device_id === primaryDeviceId;
          const isActive  = en.enabled;

          return (
            <div
              key={en.device_id}
              onMouseDown={e => onMouseDown(en.device_id, e)}
              onClick={e => { e.stopPropagation(); toggleDevice(en.device_id); }}
              role="button"
              tabIndex={0}
              aria-label={`${device.name} — ${isPrimary ? t("role.primary") : t("role.secondary")}`}
              aria-pressed={isActive}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") toggleDevice(en.device_id); }}
              style={{
                position:   "absolute",
                left:       x, top: y, width: w, height: h,
                background: isPrimary
                  ? "rgba(var(--accent-rgb,120,80,220),0.2)"
                  : isActive
                  ? "rgba(46,204,113,0.12)"
                  : "rgba(100,100,100,0.1)",
                border:     `2px solid ${isPrimary ? "var(--accent)" : isActive ? "rgba(46,204,113,0.5)" : "var(--b1)"}`,
                borderRadius: 6,
                cursor:     dragging === en.device_id ? "grabbing" : "grab",
                display:    "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                overflow:   "hidden",
                transition: "border-color 0.15s, opacity 0.15s",
                opacity:    isActive ? 1 : 0.4,
                outline:    "none",
              }}
            >
              <div style={{
                fontSize: 9, fontWeight: 700, color: "var(--t2)",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                maxWidth: "92%", textAlign: "center",
              }}>
                {device.name}
              </div>
              {isPrimary && (
                <div style={{ fontSize: 7, color: "var(--accent)", marginTop: 2, fontWeight: 800, letterSpacing: "0.05em" }}>
                  {t("layout.primary")}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Device toggle list */}
      <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
        {entries.map(en => {
          const device    = devices.find(d => d.id === en.device_id);
          if (!device) return null;
          const isPrimary = en.device_id === primaryDeviceId;
          return (
            <label
              key={en.device_id}
              style={{
                display: "flex", alignItems: "center", gap: 6, fontSize: 12,
                color: "var(--t3)", cursor: isPrimary ? "default" : "pointer",
                padding: "4px 8px",
                background: "var(--bg-input)",
                borderRadius: 7,
                border: "1px solid var(--b1)",
              }}
            >
              <input
                type="checkbox"
                checked={en.enabled}
                disabled={isPrimary}
                onChange={() => toggleDevice(en.device_id)}
                style={{ accentColor: "var(--accent)" }}
                aria-label={`${en.enabled ? "Disable" : "Enable"} ${device.name}`}
              />
              {device.name}
              {isPrimary && (
                <span style={{ fontSize: 10, color: "var(--accent)", fontWeight: 700 }}>
                  {t("role.primary")}
                </span>
              )}
            </label>
          );
        })}
      </div>
    </div>
  );
}
