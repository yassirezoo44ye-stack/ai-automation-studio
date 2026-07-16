/**
 * ShadowInspector — box shadow (offsetX, offsetY, blur, color) for selected objects.
 */
import { useState, useEffect, useCallback } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import { Shadow } from "fabric";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

interface ShadowProps { color: string; offsetX: number; offsetY: number; blur: number }

export function ShadowInspector({ getCanvas, selectedIds }: Props) {
  const [enabled, setEnabled]   = useState(false);
  const [shadow,  setShadow]    = useState<ShadowProps>({ color: "rgba(0,0,0,0.2)", offsetX: 4, offsetY: 4, blur: 8 });

  useEffect(() => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) return;
    const obj = fc.getActiveObjects()[0];
    if (!obj) return;
    const s = obj.shadow as Shadow | null;
    setEnabled(!!s);
    if (s) {
      setShadow({
        color:   s.color    ?? "rgba(0,0,0,0.2)",
        offsetX: s.offsetX  ?? 4,
        offsetY: s.offsetY  ?? 4,
        blur:    s.blur     ?? 8,
      });
    }
  }, [getCanvas, selectedIds]);

  const apply = useCallback((sh: ShadowProps | null) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.getActiveObjects().forEach(o => {
      o.set({ shadow: sh ? new Shadow(sh) : null });
    });
    fc.renderAll();
  }, [getCanvas]);

  if (!selectedIds.length) return null;

  const inp: React.CSSProperties = { flex: 1, padding: "4px 6px", fontSize: "12px", border: "1px solid #2A2A2A", borderRadius: "4px", background: "#1A1A1A", color: "#F2F2F2" };
  const row: React.CSSProperties = { display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" };
  const lbl: React.CSSProperties = { fontSize: "11px", color: "#BDBDBD", width: "48px", flexShrink: 0 };

  const updateShadow = (patch: Partial<ShadowProps>) => {
    const next = { ...shadow, ...patch };
    setShadow(next);
    if (enabled) apply(next);
  };

  return (
    <div style={{ padding: "12px", borderTop: "1px solid #1A1A1A" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
        <div style={{ fontSize: "11px", fontWeight: 600, color: "#8F8F8F", textTransform: "uppercase", letterSpacing: "0.05em" }}>Shadow</div>
        <input type="checkbox" checked={enabled} onChange={e => {
          setEnabled(e.target.checked);
          apply(e.target.checked ? shadow : null);
        }} />
      </div>

      {enabled && (
        <>
          <div style={row}>
            <span style={lbl}>Color</span>
            <input style={{ ...inp, flex: "0 0 28px", padding: 0, height: "28px" }} type="color" value={shadow.color.startsWith("rgba") ? "#000000" : shadow.color}
              onChange={e => updateShadow({ color: e.target.value })} />
            <input style={inp} type="text" value={shadow.color}
              onChange={e => updateShadow({ color: e.target.value })} />
          </div>
          <div style={row}>
            <span style={lbl}>X</span>
            <input style={inp} type="number" value={shadow.offsetX} onChange={e => updateShadow({ offsetX: +e.target.value })} />
            <span style={lbl}>Y</span>
            <input style={inp} type="number" value={shadow.offsetY} onChange={e => updateShadow({ offsetY: +e.target.value })} />
          </div>
          <div style={row}>
            <span style={lbl}>Blur</span>
            <input style={inp} type="number" min={0} value={shadow.blur} onChange={e => updateShadow({ blur: +e.target.value })} />
          </div>
        </>
      )}
    </div>
  );
}
