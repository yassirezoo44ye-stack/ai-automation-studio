import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { Canvas as FabricCanvas } from "fabric";
import type { DesignState } from "../../types/canvas.types";
import { getMeta, setLocked, setVisible } from "../../utils/fabricUtils";
import styles from "./LayersPanel.module.css";

interface Props {
  state:     DesignState;
  getCanvas: () => FabricCanvas | null;
  onSelect:  (id: string) => void;
}

export function LayersPanel({ state, getCanvas, onSelect }: Props) {
  const { t } = useTranslation("designStudio");
  const canvas = getCanvas();
  const objects = canvas ? [...canvas.getObjects()].reverse() : [];

  const handleVisibility = useCallback((id: string, visible: boolean) => {
    const fc = getCanvas();
    if (!fc) return;
    const obj = fc.getObjects().find(o => getMeta(o)?.id === id);
    if (!obj) return;
    setVisible(obj, visible);
    fc.renderAll();
  }, [getCanvas]);

  const handleLock = useCallback((id: string, locked: boolean) => {
    const fc = getCanvas();
    if (!fc) return;
    const obj = fc.getObjects().find(o => getMeta(o)?.id === id);
    if (!obj) return;
    setLocked(obj, locked);
    fc.renderAll();
  }, [getCanvas]);

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span>{t("layersPanel.header")}</span>
        <span className={styles.count}>{objects.length}</span>
      </div>

      {objects.length === 0 && (
        <p className={styles.empty}>{t("layersPanel.empty")}</p>
      )}

      <ul className={styles.list} role="listbox" aria-label={t("layersPanel.listAriaLabel")}>
        {objects.map(obj => {
          const meta      = getMeta(obj);
          const id        = meta?.id        ?? obj.type ?? "obj";
          const name      = meta?.name      ?? t("layersPanel.defaultObjectName");
          const locked    = meta?.locked    ?? false;
          const visible   = meta?.visible   ?? true;
          const isSelected = state.selectedIds.includes(id);

          return (
            <li
              key={id}
              className={`${styles.item} ${isSelected ? styles.selected : ""}`}
              onClick={() => onSelect(id)}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(id); } }}
              role="option"
              tabIndex={0}
              aria-selected={isSelected}
            >
              <button
                className={styles.iconBtn}
                onClick={e => { e.stopPropagation(); handleVisibility(id, !visible); }}
                title={visible ? t("layersPanel.hide") : t("layersPanel.show")}
                aria-label={visible ? t("layersPanel.hideLayerAriaLabel") : t("layersPanel.showLayerAriaLabel")}
              >
                {visible ? "👁" : "⊘"}
              </button>

              <span className={styles.name}>{name}</span>
              <span className={styles.type}>{meta?.type ?? obj.type}</span>

              <button
                className={styles.iconBtn}
                onClick={e => { e.stopPropagation(); handleLock(id, !locked); }}
                title={locked ? t("layersPanel.unlock") : t("layersPanel.lock")}
                aria-label={locked ? t("layersPanel.unlockLayerAriaLabel") : t("layersPanel.lockLayerAriaLabel")}
              >
                {locked ? "🔒" : "🔓"}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
