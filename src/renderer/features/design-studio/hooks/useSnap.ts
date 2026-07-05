import { useRef, useCallback, useState } from "react";
import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import { snapToGrid } from "../utils/geometryUtils";

const SNAP_THRESHOLD = 6; // px
const GRID_SIZE      = 20;

interface SnapLine {
  axis:  "x" | "y";
  value: number;
}

export interface UseSnapReturn {
  getSnapLines:   (canvas: FabricCanvas, moving: FabricObject) => SnapLine[];
  applyGridSnap:  (value: number) => number;
  snapEnabled:    boolean;
  setSnapEnabled: (v: boolean) => void;
}

export function useSnap(initialEnabled = true): UseSnapReturn {
  const enabledRef = useRef(initialEnabled);
  const [snapEnabled, setSnapState] = useState(initialEnabled);

  const setSnapEnabled = useCallback((v: boolean) => {
    enabledRef.current = v;
    setSnapState(v);
  }, []);

  const applyGridSnap = useCallback((value: number) => {
    if (!enabledRef.current) return value;
    return snapToGrid(value, GRID_SIZE);
  }, []);

  const getSnapLines = useCallback((
    canvas: FabricCanvas,
    moving: FabricObject,
  ): SnapLine[] => {
    if (!enabledRef.current) return [];

    const lines: SnapLine[] = [];
    const movingB = moving.getBoundingRect();
    const movingCenterX = movingB.left + movingB.width  / 2;
    const movingCenterY = movingB.top  + movingB.height / 2;

    const canvasW = canvas.width  ?? 0;
    const canvasH = canvas.height ?? 0;

    // Canvas edges and centre
    const canvasBounds = [
      { axis: "x" as const, value: 0       },
      { axis: "x" as const, value: canvasW / 2 },
      { axis: "x" as const, value: canvasW },
      { axis: "y" as const, value: 0       },
      { axis: "y" as const, value: canvasH / 2 },
      { axis: "y" as const, value: canvasH },
    ];

    for (const bound of canvasBounds) {
      const ref = bound.axis === "x"
        ? [movingB.left, movingCenterX, movingB.left + movingB.width]
        : [movingB.top,  movingCenterY, movingB.top  + movingB.height];
      if (ref.some(r => Math.abs(r - bound.value) < SNAP_THRESHOLD)) {
        lines.push(bound);
      }
    }

    // Object-to-object snap
    canvas.getObjects().forEach(obj => {
      if (obj === moving) return;
      const b = obj.getBoundingRect();
      const objCenterX = b.left + b.width  / 2;
      const objCenterY = b.top  + b.height / 2;

      const xCandidates = [b.left, objCenterX, b.left + b.width];
      const yCandidates = [b.top,  objCenterY, b.top  + b.height];
      const mXCandidates = [movingB.left, movingCenterX, movingB.left + movingB.width];
      const mYCandidates = [movingB.top,  movingCenterY, movingB.top  + movingB.height];

      for (const xv of xCandidates) {
        if (mXCandidates.some(mx => Math.abs(mx - xv) < SNAP_THRESHOLD)) {
          lines.push({ axis: "x", value: xv });
        }
      }
      for (const yv of yCandidates) {
        if (mYCandidates.some(my => Math.abs(my - yv) < SNAP_THRESHOLD)) {
          lines.push({ axis: "y", value: yv });
        }
      }
    });

    return lines;
  }, []);

  return {
    getSnapLines,
    applyGridSnap,
    snapEnabled,
    setSnapEnabled,
  };
}
