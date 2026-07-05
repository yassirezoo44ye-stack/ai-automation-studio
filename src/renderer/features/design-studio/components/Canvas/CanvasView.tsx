import { useEffect, useRef } from "react";
import type { UseFabricCanvasReturn } from "../../hooks/useFabricCanvas";
import type { DesignState } from "../../types/canvas.types";
import styles from "./CanvasView.module.css";

interface Props {
  fabricCanvas:  UseFabricCanvasReturn;
  state:         DesignState;
}

export function CanvasView({ fabricCanvas, state }: Props) {
  const { canvasRef, zoomToFitCanvas, loadPage } = fabricCanvas;
  const containerRef = useRef<HTMLDivElement>(null);

  const currentPage = state.project.pages.find(
    p => p.id === state.project.currentPageId,
  );

  // Load page when currentPageId changes
  useEffect(() => {
    if (currentPage) {
      void loadPage(currentPage).then(() => zoomToFitCanvas());
    }
  // Only re-run when page id changes, not on every state change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage?.id]);

  // Zoom to fit on mount
  useEffect(() => {
    const timer = setTimeout(() => zoomToFitCanvas(), 100);
    return () => clearTimeout(timer);
  }, [zoomToFitCanvas]);

  return (
    <div
      ref={containerRef}
      className={styles.canvasContainer}
      data-grid={state.showGrid}
    >
      {state.showGuides && state.guides.map(guide => (
        <div
          key={guide.id}
          className={styles.guide}
          style={
            guide.axis === "x"
              ? { left: guide.position * state.viewport.zoom, top: 0, bottom: 0, width: 1 }
              : { top: guide.position * state.viewport.zoom, left: 0, right: 0, height: 1 }
          }
        />
      ))}
      <canvas ref={canvasRef} />
    </div>
  );
}
