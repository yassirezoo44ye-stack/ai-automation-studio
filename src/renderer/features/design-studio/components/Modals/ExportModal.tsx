import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Canvas as FabricCanvas } from "fabric";
import { exportCanvas, type ExportFormat } from "../../services/exportService";
import styles from "./ExportModal.module.css";

interface Props {
  getCanvas: () => FabricCanvas | null;
  onClose:   () => void;
}

const FORMAT_IDS: ExportFormat[] = ["png", "jpg", "svg", "json"];

export function ExportModal({ getCanvas, onClose }: Props) {
  const { t } = useTranslation("designStudio");
  const [format,     setFormat]     = useState<ExportFormat>("png");
  const [quality,    setQuality]    = useState(92);
  const [scale,      setScale]      = useState(2);
  const [exporting,  setExporting]  = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleExport = async () => {
    const fc = getCanvas();
    if (!fc) return;
    setExporting(true);
    try {
      exportCanvas(fc, { format, quality: quality / 100, multiplier: scale });
    } finally {
      setExporting(false);
      onClose();
    }
  };

  return (
    // Backdrop click-to-close — not in the tab order, and Escape (handled
    // by the window listener above) is the keyboard equivalent.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
    <div className={styles.backdrop} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={styles.modal} role="dialog" aria-label={t("exportModal.dialogAriaLabel")}>
        <div className={styles.header}>
          <h2 className={styles.title}>{t("exportModal.title")}</h2>
          <button className={styles.close} onClick={onClose} aria-label={t("exportModal.closeAriaLabel")}>✕</button>
        </div>

        <div className={styles.body}>
          <div className={styles.group}>
            <div className={styles.label}>{t("exportModal.format")}</div>
            <div className={styles.formatGrid}>
              {FORMAT_IDS.map(id => (
                <button
                  key={id}
                  className={`${styles.formatBtn} ${format === id ? styles.active : ""}`}
                  onClick={() => setFormat(id)}
                >
                  <span className={styles.formatName}>{id.toUpperCase()}</span>
                  <span className={styles.formatDesc}>{t(`exportModal.formats.${id}.desc`)}</span>
                </button>
              ))}
            </div>
          </div>

          {(format === "png" || format === "jpg") && (
            <>
              <div className={styles.group}>
                <div className={styles.label}>{t("exportModal.scale")}</div>
                <div className={styles.row}>
                  {[1, 2, 3].map(s => (
                    <button
                      key={s}
                      className={`${styles.scaleBtn} ${scale === s ? styles.active : ""}`}
                      onClick={() => setScale(s)}
                    >
                      {s}x
                    </button>
                  ))}
                </div>
              </div>

              {format === "jpg" && (
                <div className={styles.group}>
                  <label className={styles.label} htmlFor="export-quality">{t("exportModal.quality", { quality })}</label>
                  <input
                    id="export-quality"
                    type="range"
                    min={40}
                    max={100}
                    value={quality}
                    onChange={e => setQuality(Number(e.target.value))}
                    className={styles.slider}
                  />
                </div>
              )}
            </>
          )}
        </div>

        <div className={styles.footer}>
          <button className={styles.btnSecondary} onClick={onClose}>{t("exportModal.cancel")}</button>
          <button
            className={styles.btnPrimary}
            onClick={() => void handleExport()}
            disabled={exporting}
          >
            {exporting ? t("exportModal.exporting") : t("exportModal.exportFormat", { format: format.toUpperCase() })}
          </button>
        </div>
      </div>
    </div>
  );
}
