/**
 * EffectsInspector — opacity and blend mode.
 * Future: blur, brightness, contrast, etc.
 */
import { useState, useEffect, useCallback } from "react";
import type { Canvas as FabricCanvas } from "fabric";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

const BLEND_MODES = [
  "normal","multiply","screen","overlay","darken","lighten",
  "color-dodge","color-burn","hard-light","soft-light",
  "difference","exclusion","hue","saturation","color","luminosity",
];

export function EffectsInspector({ getCanvas, selectedIds }: Props) {
  const [opacity,    setOpacity]    = useState(100);
  const [blendMode,  setBlendMode]  = useState("normal");

  useEffect(() => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) return;
    const obj = fc.getActiveObjects()[0];
    if (!obj) return;
    setOpacity(Math.round((obj.opacity ?? 1) * 100));
    setBlendMode(obj.globalCompositeOperation ?? "normal");
  }, [getCanvas, selectedIds]);

  const apply = useCallback((op: number, bm: string) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.getActiveObjects().forEach(o => o.set({ opacity: op / 100, globalCompositeOperation: bm }));
    fc.renderAll();
  }, [getCanvas]);

  if (!selectedIds.length) return null;

  const sel: React.CSSProperties = { flex: 1, padding: "4px 6px", fontSize: "12px", border: "1px solid #374151", borderRadius: "4px", background: "#1f2937", color: "#f9fafb" };

  return (
    <div style={{ padding: "12px", borderTop: "1px solid #1f2937" }}>
      <div style={{ fontSize: "11px", fontWeight: 600, color: "#6b7280", marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Effects</div>

      <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" }}>
        <span style={{ fontSize: "11px", color: "#9ca3af", width: "48px", flexShrink: 0 }}>Opacity</span>
        <input style={{ flex: 1 }} type="range" min={0} max={100} value={opacity}
          onChange={e => { setOpacity(+e.target.value); apply(+e.target.value, blendMode); }} />
        <span style={{ fontSize: "12px", color: "#f9fafb", width: "36px", textAlign: "right" }}>{opacity}%</span>
      </div>

      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
        <span style={{ fontSize: "11px", color: "#9ca3af", width: "48px", flexShrink: 0 }}>Blend</span>
        <select style={sel} value={blendMode}
          onChange={e => { setBlendMode(e.target.value); apply(opacity, e.target.value); }}>
          {BLEND_MODES.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
    </div>
  );
}
