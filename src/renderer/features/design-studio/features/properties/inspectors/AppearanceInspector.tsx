/**
 * AppearanceInspector — fill color, stroke color, stroke width.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { Canvas as FabricCanvas } from "fabric";
import { commandManager } from "../../../core/commands/CommandManager";
import { ChangeColorCommand } from "../../../core/commands/commands/ChangeColor";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

const secWrap: React.CSSProperties = { padding: "12px", borderTop: "1px solid var(--b1)" };
const secHeader: React.CSSProperties = {
  fontSize: "11px", fontWeight: 600, color: "var(--t3)",
  marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em",
};
const rowStyle: React.CSSProperties = { display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" };
const lblStyle: React.CSSProperties = { fontSize: "11px", color: "var(--t3)", width: "48px", flexShrink: 0 };
const swatchStyle: React.CSSProperties = {
  width: "28px", height: "28px", borderRadius: "var(--r-xs, 4px)",
  border: "1px solid var(--border)", cursor: "pointer", flexShrink: 0, padding: 0,
};
const inpStyle: React.CSSProperties = {
  flex: 1, padding: "4px 6px", fontSize: "12px",
  border: "1px solid var(--border)", borderRadius: "var(--r-xs, 4px)",
  background: "var(--bg-input)", color: "var(--t1)", outline: "none", fontFamily: "inherit",
};

export function AppearanceInspector({ getCanvas, selectedIds }: Props) {
  const { t } = useTranslation("designStudio");
  const [fill,        setFill]        = useState("#4f46e5");
  const [stroke,      setStroke]      = useState("#000000");
  const [strokeWidth, setStrokeWidth] = useState(0);

  useEffect(() => {
    queueMicrotask(() => {
      const fc = getCanvas();
      if (!fc || !selectedIds.length) return;
      const obj = fc.getActiveObjects()[0];
      if (!obj) return;
      const rawFill = obj.fill;
      setFill(typeof rawFill === "string" ? rawFill : "#4f46e5");
      setStroke(typeof obj.stroke === "string" ? obj.stroke : "#000000");
      setStrokeWidth(obj.strokeWidth ?? 0);
    });
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

  return (
    <div style={secWrap}>
      <div style={secHeader}>{t("inspectors.appearance.header")}</div>

      <div style={rowStyle}>
        <span style={lblStyle}>{t("inspectors.appearance.fill")}</span>
        <input type="color" style={swatchStyle} value={fill}
          onChange={e => setFill(e.target.value)}
          onBlur={e => void applyColor("fill", e.target.value)} />
        <input style={inpStyle} type="text" value={fill}
          onChange={e => setFill(e.target.value)}
          onBlur={e => void applyColor("fill", e.target.value)} />
      </div>

      <div style={rowStyle}>
        <span style={lblStyle}>{t("inspectors.appearance.stroke")}</span>
        <input type="color" style={swatchStyle} value={stroke}
          onChange={e => setStroke(e.target.value)}
          onBlur={e => void applyColor("stroke", e.target.value)} />
        <input style={inpStyle} type="text" value={stroke}
          onChange={e => setStroke(e.target.value)}
          onBlur={e => void applyColor("stroke", e.target.value)} />
      </div>

      <div style={rowStyle}>
        <span style={lblStyle}>{t("inspectors.appearance.width")}</span>
        <input style={{ ...inpStyle, flex: "0 0 60px" }} type="number" min={0} max={50} value={strokeWidth}
          onChange={e => setStrokeWidth(+e.target.value)}
          onBlur={e => applyStrokeWidth(+e.target.value)} />
      </div>
    </div>
  );
}
