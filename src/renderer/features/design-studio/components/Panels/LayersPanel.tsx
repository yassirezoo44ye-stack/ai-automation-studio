import { useCallback } from "react";
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
        <span>Layers</span>
        <span className={styles.count}>{objects.length}</span>
      </div>

      {objects.length === 0 && (
        <p className={styles.empty}>No elements yet. Add shapes or text to see layers.</p>
      )}

      <ul className={styles.list} role="listbox" aria-label="Layers">
        {objects.map(obj => {
          const meta      = getMeta(obj);
          const id        = meta?.id        ?? obj.type ?? "obj";
          const name      = meta?.name      ?? "Object";
          const locked    = meta?.locked    ?? false;
          const visible   = meta?.visible   ?? true;
          const isSelected = state.selectedIds.includes(id);

          return (
            <li
              key={id}
              className={`${styles.item} ${isSelected ? styles.selected : ""}`}
              onClick={() => onSelect(id)}
              role="option"
              aria-selected={isSelected}
            >
              <button
                className={styles.iconBtn}
                onClick={e => { e.stopPropagation(); handleVisibility(id, !visible); }}
                title={visible ? "Hide" : "Show"}
                aria-label={visible ? "Hide layer" : "Show layer"}
              >
                {visible ? "👁" : "⊘"}
              </button>

              <span className={styles.name}>{name}</span>
              <span className={styles.type}>{meta?.type ?? obj.type}</span>

              <button
                className={styles.iconBtn}
                onClick={e => { e.stopPropagation(); handleLock(id, !locked); }}
                title={locked ? "Unlock" : "Lock"}
                aria-label={locked ? "Unlock layer" : "Lock layer"}
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
