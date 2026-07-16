/**
 * AppearanceInspector — fill color, stroke color, stroke width.
 */
import { useState, useEffect, useCallback } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import { commandManager } from "../../../core/commands/CommandManager";
import { ChangeColorCommand } from "../../../core/commands/commands/ChangeColor";
import { getMeta } from "../../../utils/fabricUtils";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

export function AppearanceInspector({ getCanvas, selectedIds }: Props) {
  const [fill,        setFill]        = useState("#D4AF37");
  const [stroke,      setStroke]      = useState("#000000");
  const [strokeWidth, setStrokeWidth] = useState(0);

  useEffect(() => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) return;
    const obj = fc.getActiveObjects()[0];
    if (!obj) return;
    const rawFill = obj.fill;
    setFill(typeof rawFill === "string" ? rawFill : "#D4AF37");
    setStroke(typeof obj.stroke === "string" ? obj.stroke : "#000000");
    setStrokeWidth(obj.strokeWidth ?? 0);
  }, [getCanvas, selectedIds]);

  const applyColor = useCallback(async (prop: "fill" | "stroke", color: string) => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) return;
    await commandManager.execute(fc, new ChangeColorCommand(selectedIds, prop, color));
  }, [getCanvas, selectedIds]);

  const applyStrokeWidth = useCallback((w: number) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.getActiveObjects().forEach(o => o.set({ strokeWidth: w }));
    fc.renderAll();
  }, [getCanvas]);

  if (!selectedIds.length) return null;

  const row: React.CSSProperties = { display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" };
  const lbl: React.CSSProperties = { fontSize: "11px", color: "#BDBDBD", width: "48px", flexShrink: 0 };
  const swatch: React.CSSProperties = { width: "28px", height: "28px", borderRadius: "4px", border: "1px solid #2A2A2A", cursor: "pointer", flexShrink: 0 };
  const inp: React.CSSProperties = { flex: 1, padding: "4px 6px", fontSize: "12px", border: "1px solid #2A2A2A", borderRadius: "4px", background: "#1A1A1A", color: "#F2F2F2" };

  return (
    <div style={{ padding: "12px", borderTop: "1px solid #1A1A1A" }}>
      <div style={{ fontSize: "11px", fontWeight: 600, color: "#8F8F8F", marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Appearance</div>

      <div style={row}>
        <span style={lbl}>Fill</span>
        <input type="color" style={{ ...swatch, padding: 0 }} value={fill}
          onChange={e => setFill(e.target.value)}
          onBlur={e => void applyColor("fill", e.target.value)} />
        <input style={inp} type="text" value={fill}
          onChange={e => setFill(e.target.value)}
          onBlur={e => void applyColor("fill", e.target.value)} />
      </div>

      <div style={row}>
        <span style={lbl}>Stroke</span>
        <input type="color" style={{ ...swatch, padding: 0 }} value={stroke}
          onChange={e => setStroke(e.target.value)}
          onBlur={e => void applyColor("stroke", e.target.value)} />
        <input style={inp} type="text" value={stroke}
          onChange={e => setStroke(e.target.value)}
          onBlur={e => void applyColor("stroke", e.target.value)} />
      </div>

      <div style={row}>
        <span style={lbl}>Width</span>
        <input style={{ ...inp, flex: "0 0 60px" }} type="number" min={0} max={50} value={strokeWidth}
          onChange={e => setStrokeWidth(+e.target.value)}
          onBlur={e => applyStrokeWidth(+e.target.value)} />
      </div>
    </div>
  );
}
