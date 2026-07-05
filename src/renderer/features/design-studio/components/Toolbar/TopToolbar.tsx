import styles from "./TopToolbar.module.css";

interface Props {
  projectName:  string;
  unsaved:      boolean;
  historyIndex: number;
  historyLength:number;
  zoom:         number;
  canUndo:      boolean;
  canRedo:      boolean;
  onUndo:       () => void;
  onRedo:       () => void;
  onZoomIn:     () => void;
  onZoomOut:    () => void;
  onZoomReset:  () => void;
  onExport:     () => void;
  onSave:       () => void;
}

export function TopToolbar({
  projectName, unsaved, zoom,
  canUndo, canRedo, onUndo, onRedo,
  onZoomIn, onZoomOut, onZoomReset,
  onExport, onSave,
}: Props) {
  return (
    <header className={styles.toolbar}>
      <div className={styles.left}>
        <span className={styles.projectName}>
          {projectName}
          {unsaved && <span className={styles.dot} title="Unsaved changes" />}
        </span>
      </div>

      <div className={styles.center}>
        <button
          className={styles.btn}
          onClick={onUndo}
          disabled={!canUndo}
          title="Undo (Ctrl+Z)"
          aria-label="Undo"
        >
          ↩
        </button>
        <button
          className={styles.btn}
          onClick={onRedo}
          disabled={!canRedo}
          title="Redo (Ctrl+Y)"
          aria-label="Redo"
        >
          ↪
        </button>

        <div className={styles.divider} />

        <button className={styles.btn} onClick={onZoomOut} title="Zoom out (Ctrl+-)">−</button>
        <button className={styles.zoomLabel} onClick={onZoomReset} title="Reset zoom (Ctrl+0)">
          {Math.round(zoom * 100)}%
        </button>
        <button className={styles.btn} onClick={onZoomIn} title="Zoom in (Ctrl+=)">+</button>
      </div>

      <div className={styles.right}>
        <button className={styles.btnSecondary} onClick={onSave} title="Save">
          Save
        </button>
        <button className={styles.btnPrimary} onClick={onExport} title="Export">
          Export
        </button>
      </div>
    </header>
  );
}
