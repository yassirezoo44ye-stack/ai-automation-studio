/**
 * PropertiesPanel — right-side inspector panel.
 * Composes PositionInspector, AppearanceInspector, TypographyInspector,
 * ShadowInspector, BorderInspector, and EffectsInspector into one panel.
 * Each inspector is self-contained and only renders when relevant.
 */
import type { Canvas as FabricCanvas } from "fabric";
import { useTranslation } from "react-i18next";
import { PositionInspector }   from "../../features/properties/inspectors/PositionInspector";
import { AppearanceInspector } from "../../features/properties/inspectors/AppearanceInspector";
import { TypographyInspector } from "../../features/properties/inspectors/TypographyInspector";
import { ShadowInspector }     from "../../features/properties/inspectors/ShadowInspector";
import { BorderInspector }     from "../../features/properties/inspectors/BorderInspector";
import { EffectsInspector }    from "../../features/properties/inspectors/EffectsInspector";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
  onBringForward: () => void;
  onSendBackward: () => void;
}

const layerBtn: React.CSSProperties = {
  flex: 1, padding: "6px 8px", fontSize: "11px",
  border: "1px solid var(--border)", borderRadius: "var(--r-xs, 4px)",
  background: "var(--bg-input)", color: "var(--t2)",
  cursor: "pointer", fontFamily: "inherit", transition: "background 0.12s, border-color 0.12s",
};

export function PropertiesPanel({ getCanvas, selectedIds, onBringForward, onSendBackward }: Props) {
  const { t } = useTranslation("designStudio");

  if (!selectedIds.length) {
    return (
      <div style={{
        padding: "16px 12px",
        color: "var(--t4)",
        fontSize: "12px",
        textAlign: "center",
        lineHeight: 1.5,
      }}>
        {t("propertiesPanel.emptyState")}
      </div>
    );
  }

  return (
    <div style={{ overflowY: "auto", maxHeight: "100%" }}>
      <div style={{ display: "flex", gap: "6px", padding: "10px 12px 0" }}>
        <button
          onClick={onBringForward}
          title={t("propertiesPanel.bringForward")}
          aria-label={t("propertiesPanel.bringForward")}
          style={layerBtn}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--ba)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border)"; }}
        >
          {t("propertiesPanel.bringForward")}
        </button>
        <button
          onClick={onSendBackward}
          title={t("propertiesPanel.sendBackward")}
          aria-label={t("propertiesPanel.sendBackward")}
          style={layerBtn}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--ba)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border)"; }}
        >
          {t("propertiesPanel.sendBackward")}
        </button>
      </div>
      <PositionInspector   getCanvas={getCanvas} selectedIds={selectedIds} />
      <AppearanceInspector getCanvas={getCanvas} selectedIds={selectedIds} />
      <TypographyInspector getCanvas={getCanvas} selectedIds={selectedIds} />
      <ShadowInspector     getCanvas={getCanvas} selectedIds={selectedIds} />
      <BorderInspector     getCanvas={getCanvas} selectedIds={selectedIds} />
      <EffectsInspector    getCanvas={getCanvas} selectedIds={selectedIds} />
    </div>
  );
}
