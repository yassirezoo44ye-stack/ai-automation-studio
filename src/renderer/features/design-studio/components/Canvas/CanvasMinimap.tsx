import { useEffect, useRef } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import type { Viewport } from "../../types/canvas.types";
import styles from "./CanvasMinimap.module.css";

interface Props {
  getCanvas:    () => FabricCanvas | null;
  viewport:     Viewport;
  canvasWidth:  number;
  canvasHeight: number;
}

const THUMB_W = 160;
const THUMB_H = 90;

export function CanvasMinimap({ getCanvas, viewport, canvasWidth, canvasHeight }: Props) {
  const thumbRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const fc = getCanvas();
    if (!fc || !thumbRef.current) return;

    const thumb = thumbRef.current;
    const scale = Math.min(THUMB_W / canvasWidth, THUMB_H / canvasHeight);
    thumb.width  = Math.round(canvasWidth  * scale);
    thumb.height = Math.round(canvasHeight * scale);

    const ctx = thumb.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, thumb.width, thumb.height);

    const dataUrl = fc.toDataURL({ multiplier: scale, format: "png" });
    const img = new Image();
    img.onload = () => ctx.drawImage(img, 0, 0);
    img.src    = dataUrl;
  });

  // Viewport indicator
  const scale = Math.min(THUMB_W / canvasWidth, THUMB_H / canvasHeight);
  const vx = (-viewport.panX / viewport.zoom) * scale;
  const vy = (-viewport.panY / viewport.zoom) * scale;
  const vw = (canvasWidth  / viewport.zoom) * scale;
  const vh = (canvasHeight / viewport.zoom) * scale;

  return (
    <div className={styles.minimap}>
      <canvas ref={thumbRef} className={styles.thumb} />
      <div
        className={styles.viewport}
        style={{
          left:   Math.max(0, vx),
          top:    Math.max(0, vy),
          width:  Math.min(THUMB_W, vw),
          height: Math.min(THUMB_H, vh),
        }}
      />
    </div>
  );
}
