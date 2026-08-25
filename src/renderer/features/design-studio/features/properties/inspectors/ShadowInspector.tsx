/**
 * ShadowInspector — box shadow (offsetX, offsetY, blur, color) for selected objects.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { Canvas as FabricCanvas } from "fabric";
import { Shadow } from "fabric";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

interface ShadowProps { color: string; offsetX: number; offsetY: number; blur: number }

const secWrap: React.CSSProperties = { padding: "12px", borderTop: "1px solid var(--b1)" };
const secHeader: React.CSSProperties = {
  fontSize: "11px", fontWeight: 600, color: "var(--t3)",
  textTransform: "uppercase", letterSpacing: "0.05em",
};
const inpStyle: React.CSSProperties = {
  flex: 1, padding: "4px 6px", fontSize: "12px",
  border: "1px solid var(--border)", borderRadius: "var(--r-xs, 4px)",
  background: "var(--bg-input)", color: "var(--t1)", outline: "none", fontFamily: "inherit",
};
const rowStyle: React.CSSProperties = { display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" };
const lblStyle: React.CSSProperties = { fontSize: "11px", color: "var(--t3)", width: "48px", flexShrink: 0 };

export function ShadowInspector({ getCanvas, selectedIds }: Props) {
  const { t } = useTranslation("designStudio");
  const [enabled, setEnabled]   = useState(false);
  const [shadow,  setShadow]    = useState<ShadowProps>({ color: "rgba(0,0,0,0.2)", offsetX: 4, offsetY: 4, blur: 8 });

  useEffect(() => {
    queueMicrotask(() => {
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
    });
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

  const updateShadow = (patch: Partial<ShadowProps>) => {
    const next = { ...shadow, ...patch };
    setShadow(next);
    if (enabled) apply(next);
  };

  return (
    <div style={secWrap}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
        <div style={secHeader}>{t("inspectors.shadow.header")}</div>
        <input type="checkbox" checked={enabled} onChange={e => {
          setEnabled(e.target.checked);
          apply(e.target.checked ? shadow : null);
        }} />
      </div>

      {enabled && (
        <>
          <div style={rowStyle}>
            <span style={lblStyle}>{t("inspectors.shadow.color")}</span>
            <input
              style={{ ...inpStyle, flex: "0 0 28px", padding: 0, height: "28px", borderRadius: "var(--r-xs, 4px)" }}
              type="color"
              value={shadow.color.startsWith("rgba") ? "#000000" : shadow.color}
              onChange={e => updateShadow({ color: e.target.value })}
            />
            <input style={inpStyle} type="text" value={shadow.color}
              onChange={e => updateShadow({ color: e.target.value })} />
          </div>
          <div style={rowStyle}>
            <span style={lblStyle}>X</span>
            <input style={inpStyle} type="number" value={shadow.offsetX} onChange={e => updateShadow({ offsetX: +e.target.value })} />
            <span style={lblStyle}>Y</span>
            <input style={inpStyle} type="number" value={shadow.offsetY} onChange={e => updateShadow({ offsetY: +e.target.value })} />
          </div>
          <div style={rowStyle}>
            <span style={lblStyle}>{t("inspectors.shadow.blur")}</span>
            <input style={inpStyle} type="number" min={0} value={shadow.blur} onChange={e => updateShadow({ blur: +e.target.value })} />
          </div>
        </>
      )}
    </div>
  );
}
