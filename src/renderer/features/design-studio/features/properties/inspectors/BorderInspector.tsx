/**
 * BorderInspector — border radius for rect/shape objects.
 */
import { useState, useEffect, useCallback } from "react";
import type { Canvas as FabricCanvas, Rect } from "fabric";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

export function BorderInspector({ getCanvas, selectedIds }: Props) {
  const [radius, setRadius] = useState(0);
  const [hasRadius, setHasRadius] = useState(false);

  useEffect(() => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) return;
    const obj = fc.getActiveObjects()[0];
    const r = (obj as Rect)?.rx ?? 0;
    setHasRadius("rx" in (obj ?? {}));
    setRadius(r);
  }, [getCanvas, selectedIds]);

  const apply = useCallback((r: number) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.getActiveObjects().forEach(o => {
      if ("rx" in o) o.set({ rx: r, ry: r } as Partial<Rect>);
    });
    fc.renderAll();
  }, [getCanvas]);

  if (!selectedIds.length || !hasRadius) return null;

  const inp: React.CSSProperties = { flex: 1, padding: "4px 6px", fontSize: "12px", border: "1px solid #2A2A2A", borderRadius: "4px", background: "#1A1A1A", color: "#F2F2F2" };

  return (
    <div style={{ padding: "12px", borderTop: "1px solid #1A1A1A" }}>
      <div style={{ fontSize: "11px", fontWeight: 600, color: "#8F8F8F", marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Border</div>
      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
        <span style={{ fontSize: "11px", color: "#BDBDBD", width: "48px", flexShrink: 0 }}>Radius</span>
        <input style={inp} type="range" min={0} max={200} value={radius}
          onChange={e => { setRadius(+e.target.value); apply(+e.target.value); }} />
        <span style={{ fontSize: "12px", color: "#F2F2F2", width: "32px", textAlign: "right" }}>{radius}px</span>
      </div>
    </div>
  );
}
