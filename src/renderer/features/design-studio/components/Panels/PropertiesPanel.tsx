/**
 * PropertiesPanel — right-side inspector panel.
 * Composes PositionInspector, AppearanceInspector, TypographyInspector,
 * ShadowInspector, BorderInspector, and EffectsInspector into one panel.
 * Each inspector is self-contained and only renders when relevant.
 */
import type { Canvas as FabricCanvas } from "fabric";
import { PositionInspector }   from "../../features/properties/inspectors/PositionInspector";
import { AppearanceInspector } from "../../features/properties/inspectors/AppearanceInspector";
import { TypographyInspector } from "../../features/properties/inspectors/TypographyInspector";
import { ShadowInspector }     from "../../features/properties/inspectors/ShadowInspector";
import { BorderInspector }     from "../../features/properties/inspectors/BorderInspector";
import { EffectsInspector }    from "../../features/properties/inspectors/EffectsInspector";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

export function PropertiesPanel({ getCanvas, selectedIds }: Props) {
  if (!selectedIds.length) {
    return (
      <div style={{
        padding: "16px 12px",
        color: "#6b7280",
        fontSize: "12px",
        textAlign: "center",
        lineHeight: 1.5,
      }}>
        Select an object to edit its properties.
      </div>
    );
  }

  return (
    <div style={{ overflowY: "auto", maxHeight: "100%" }}>
      <PositionInspector   getCanvas={getCanvas} selectedIds={selectedIds} />
      <AppearanceInspector getCanvas={getCanvas} selectedIds={selectedIds} />
      <TypographyInspector getCanvas={getCanvas} selectedIds={selectedIds} />
      <ShadowInspector     getCanvas={getCanvas} selectedIds={selectedIds} />
      <BorderInspector     getCanvas={getCanvas} selectedIds={selectedIds} />
      <EffectsInspector    getCanvas={getCanvas} selectedIds={selectedIds} />
    </div>
  );
}
