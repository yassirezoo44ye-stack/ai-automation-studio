/**
 * LivePreviewPage — preview built apps across device viewports.
 * Consumes app data from the app-builder API (read-only).
 * RTL-first: logical CSS properties throughout.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAsyncData } from "../../shared/hooks/useAsyncData";
import { apiFetch, parseJSON } from "../../utils/api";
import type { AppRecord } from "../app-builder/types";

/* ── Device presets ───────────────────────────────────────────────────── */
type DevicePreset = {
  id: string;
  label: string;
  width: number;
  height: number;
  icon: React.ReactNode;
};

const DEVICES: DevicePreset[] = [
  {
    id: "desktop",
    label: "Desktop",
    width: 1280,
    height: 800,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
    ),
  },
  {
    id: "tablet",
    label: "Tablet",
    width: 768,
    height: 1024,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
    ),
  },
  {
    id: "mobile",
    label: "Mobile",
    width: 390,
    height: 844,
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
    ),
  },
];

/* ── Page ─────────────────────────────────────────────────────────────── */
export function LivePreviewPage() {
  useTranslation("common");
  const [device, setDevice]  = useState<DevicePreset>(DEVICES[0]);
  const [zoom, setZoom]      = useState(0.7);
  const [selectedApp, setSelectedApp] = useState<string | null>(null);

  // Load existing apps from the app-builder API (read-only)
  const appsQuery = useAsyncData<AppRecord[]>(
    () => apiFetch("/apps").then(r => parseJSON<AppRecord[]>(r, "/apps")).catch(() => [] as AppRecord[]),
    [],
  );
  const apps = appsQuery.data ?? [];
  const currentApp = apps.find(a => a.id === selectedApp) ?? apps[0] ?? null;

  // No preview_url on AppRecord — always use mock preview for now
  const previewUrl: string | null = null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "var(--bg-base)", color: "var(--t1)" }}>
      {/* Top bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 20px", height: 52, borderBlockEnd: "1px solid var(--b1)", background: "var(--bg-surface)", flexShrink: 0 }}>
        {/* App picker */}
        <select
          value={selectedApp ?? ""}
          onChange={e => setSelectedApp(e.target.value || null)}
          style={{ padding: "6px 10px", fontSize: 13, background: "var(--bg-input)", border: "1px solid var(--b1)", borderRadius: 8, color: "var(--t1)", outline: "none", cursor: "pointer" }}
        >
          {apps.length === 0 && <option value="">No apps built yet</option>}
          {apps.map(a => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>

        {/* Device picker */}
        <div style={{ display: "flex", border: "1px solid var(--b1)", borderRadius: 8, overflow: "hidden" }}>
          {DEVICES.map(d => (
            <button
              key={d.id}
              onClick={() => setDevice(d)}
              title={d.label}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px", fontSize: 12, fontWeight: 500, background: device.id === d.id ? "var(--accent)" : "transparent", color: device.id === d.id ? "#fff" : "var(--t3)", border: "none", cursor: "pointer", transition: "all .12s", borderInlineStart: d.id !== "desktop" ? "1px solid var(--b1)" : "none" }}
            >
              {d.icon}
              {d.label}
            </button>
          ))}
        </div>

        {/* Zoom controls */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginInlineStart: "auto" }}>
          <button onClick={() => setZoom(z => Math.max(0.25, z - 0.1))} style={{ width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-card)", border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer", fontSize: 16, color: "var(--t2)" }}>−</button>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", width: 42, textAlign: "center", fontFamily: "var(--font-mono)" }}>{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom(z => Math.min(1.5, z + 0.1))} style={{ width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-card)", border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer", fontSize: 16, color: "var(--t2)" }}>+</button>
          <button onClick={() => setZoom(1)} style={{ padding: "4px 10px", fontSize: 11, fontWeight: 500, background: "transparent", border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer", color: "var(--t3)" }}>Reset</button>
        </div>

        {/* Status */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 12px", background: "var(--green-dim)", borderRadius: 20, border: "1px solid var(--green)" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--green)", display: "inline-block" }} />
          <span style={{ fontSize: 11, fontWeight: 600, color: "var(--green)" }}>Live</span>
        </div>
      </div>

      {/* Preview canvas */}
      <div style={{ flex: 1, overflow: "auto", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "28px", background: "repeating-linear-gradient(45deg, transparent, transparent 12px, var(--bg-card) 12px, var(--bg-card) 13px)" }}>
        {/* Browser chrome frame */}
        <div
          style={{
            transform: `scale(${zoom})`,
            transformOrigin: "top center",
            width: device.width,
            flexShrink: 0,
            background: "var(--bg-surface)",
            border: "1px solid var(--b2)",
            borderRadius: device.id === "desktop" ? 8 : 20,
            overflow: "hidden",
            boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
          }}
        >
          {/* Browser chrome */}
          {device.id === "desktop" && (
            <div style={{ height: 36, background: "var(--bg-elevated)", borderBlockEnd: "1px solid var(--b1)", display: "flex", alignItems: "center", padding: "0 12px", gap: 8 }}>
              <div style={{ display: "flex", gap: 5 }}>
                {["#ef4444", "#f59e0b", "#22c55e"].map(c => <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />)}
              </div>
              <div style={{ flex: 1, background: "var(--bg-input)", borderRadius: 6, height: 22, display: "flex", alignItems: "center", paddingInline: 10, fontSize: 11, color: "var(--t3)" }}>
                {currentApp ? `https://preview.flow.co/apps/${currentApp.id}` : "https://preview.flow.co"}
              </div>
            </div>
          )}

          {/* Viewport */}
          <div style={{ height: device.height, overflow: "hidden", position: "relative" }}>
            {!currentApp && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 12, color: "var(--t3)" }}>
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
                <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t2)" }}>No app selected</div>
                <div style={{ fontSize: 13 }}>Build an app in App Builder first</div>
              </div>
            )}
            {currentApp && previewUrl && (
              <iframe
                src={previewUrl}
                title={`Preview: ${currentApp.name}`}
                style={{ width: "100%", height: "100%", border: "none" }}
                sandbox="allow-scripts allow-same-origin allow-forms"
              />
            )}
            {currentApp && !previewUrl && (
              <AppMockPreview app={currentApp} device={device.id} />
            )}
          </div>
        </div>
      </div>

      {/* Bottom status bar */}
      <div style={{ height: 32, background: "var(--bg-surface)", borderBlockStart: "1px solid var(--b1)", display: "flex", alignItems: "center", paddingInline: 20, gap: 16, flexShrink: 0 }}>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>
          {device.width} × {device.height} · {device.label}
        </span>
        {currentApp && (
          <span style={{ fontSize: 11, color: "var(--t3)" }}>App: <strong style={{ color: "var(--t2)" }}>{currentApp.name}</strong></span>
        )}
        <span style={{ fontSize: 11, color: "var(--t4)", marginInlineStart: "auto" }}>Flow Live Preview</span>
      </div>
    </div>
  );
}

/* ── Mock app preview (when no preview_url is available) ──────────────── */
function AppMockPreview({ app, device }: { app: AppRecord; device: string }) {
  const fields = ["Name", "Email", "Status", "Value", "Created", "Actions"];
  const rows   = [
    ["Alice Johnson",  "alice@co.com",   "Active",   "$4,200", "Jan 12", "···"],
    ["Bob Smith",      "bob@co.com",     "Pending",  "$1,850", "Jan 14", "···"],
    ["Carol Davis",    "carol@co.com",   "Active",   "$9,100", "Jan 15", "···"],
    ["David Wilson",   "david@co.com",   "Inactive", "$0",     "Jan 16", "···"],
  ];

  if (device === "mobile") {
    return (
      <div style={{ height: "100%", overflow: "auto", background: "#fff", padding: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#111", marginBlockEnd: 12 }}>{app.name}</div>
        {rows.map((row, i) => (
          <div key={i} style={{ background: "#f8f9fa", borderRadius: 8, padding: "10px 12px", marginBlockEnd: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#1a1a2e" }}>{row[0]}</div>
            <div style={{ fontSize: 12, color: "#666", marginBlockStart: 2 }}>{row[1]}</div>
            <div style={{ display: "flex", gap: 8, marginBlockStart: 6 }}>
              <span style={{ fontSize: 11, padding: "2px 7px", background: row[2] === "Active" ? "#d1fae5" : "#f3f4f6", color: row[2] === "Active" ? "#065f46" : "#6b7280", borderRadius: 12, fontWeight: 600 }}>{row[2]}</span>
              <span style={{ fontSize: 11, color: "#6b7280", fontWeight: 600 }}>{row[3]}</span>
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "auto", background: "#fff", display: "flex", flexDirection: "column" }}>
      {/* App header */}
      <div style={{ height: 52, background: "#6e32e0", display: "flex", alignItems: "center", paddingInline: 20, gap: 12, flexShrink: 0 }}>
        <div style={{ width: 28, height: 28, borderRadius: 6, background: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: "#fff" }}>A</div>
        <span style={{ fontSize: 14, fontWeight: 600, color: "#fff" }}>{app.name}</span>
        <div style={{ marginInlineStart: "auto", display: "flex", gap: 8 }}>
          {["Dashboard","Records","Reports","Settings"].map(tab => (
            <button key={tab} style={{ padding: "4px 10px", fontSize: 12, background: "rgba(255,255,255,0.15)", border: "none", borderRadius: 6, color: "#fff", cursor: "pointer" }}>{tab}</button>
          ))}
        </div>
      </div>
      {/* Table */}
      <div style={{ flex: 1, overflow: "auto", padding: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBlockEnd: 14 }}>
          <h2 style={{ fontSize: 15, fontWeight: 700, color: "#1a1a2e", margin: 0 }}>Records</h2>
          <button style={{ padding: "6px 14px", fontSize: 12, fontWeight: 600, background: "#6e32e0", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}>+ New</button>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#f8f9fa" }}>
              {fields.map(f => <th key={f} style={{ padding: "8px 12px", textAlign: "start", fontWeight: 600, color: "#6b7280", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid #e5e7eb" }}>{f}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                {row.map((cell, j) => (
                  <td key={j} style={{ padding: "10px 12px", color: j === 2 ? (cell === "Active" ? "#059669" : cell === "Inactive" ? "#dc2626" : "#d97706") : "#374151" }}>
                    {j === 2 ? (
                      <span style={{ padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 600, background: cell === "Active" ? "#d1fae5" : cell === "Inactive" ? "#fee2e2" : "#fef3c7" }}>{cell}</span>
                    ) : cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
