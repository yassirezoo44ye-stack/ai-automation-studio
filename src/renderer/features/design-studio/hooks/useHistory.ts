import { useRef, useCallback } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import type { HistoryEntry } from "../types/canvas.types";
import { canvasToJSON, loadJSONToCanvas } from "../utils/fabricUtils";

const MAX_HISTORY = 80;

interface UseHistoryReturn {
  saveSnapshot:  (description?: string) => void;
  undo:          () => Promise<void>;
  redo:          () => Promise<void>;
  canUndo:       () => boolean;
  canRedo:       () => boolean;
  historyInfo:   () => { index: number; length: number };
  clearHistory:  () => void;
}

export function useHistory(
  getCanvas: () => FabricCanvas | null,
  onHistoryChange?: (index: number, length: number) => void,
): UseHistoryReturn {
  const stack   = useRef<HistoryEntry[]>([]);
  const pointer = useRef<number>(-1);
  const locked  = useRef(false); // prevent saving while undo/redo is in progress

  const notify = useCallback(() => {
    onHistoryChange?.(pointer.current, stack.current.length);
  }, [onHistoryChange]);

  const saveSnapshot = useCallback((description = "change") => {
    if (locked.current) return;
    const canvas = getCanvas();
    if (!canvas) return;

    const json = canvasToJSON(canvas);

    // Truncate forward history when a new action is taken
    if (pointer.current < stack.current.length - 1) {
      stack.current = stack.current.slice(0, pointer.current + 1);
    }

    stack.current.push({ json, description, ts: Date.now() });

    // Keep within limit (circular buffer)
    if (stack.current.length > MAX_HISTORY) {
      stack.current.shift();
    } else {
      pointer.current += 1;
    }

    notify();
  }, [getCanvas, notify]);

  const undo = useCallback(async () => {
    if (pointer.current <= 0) return;
    const canvas = getCanvas();
    if (!canvas) return;

    locked.current = true;
    pointer.current -= 1;
    const entry = stack.current[pointer.current];
    await loadJSONToCanvas(canvas, entry.json);
    locked.current = false;
    notify();
  }, [getCanvas, notify]);

  const redo = useCallback(async () => {
    if (pointer.current >= stack.current.length - 1) return;
    const canvas = getCanvas();
    if (!canvas) return;

    locked.current = true;
    pointer.current += 1;
    const entry = stack.current[pointer.current];
    await loadJSONToCanvas(canvas, entry.json);
    locked.current = false;
    notify();
  }, [getCanvas, notify]);

  const canUndo  = useCallback(() => pointer.current > 0, []);
  const canRedo  = useCallback(() => pointer.current < stack.current.length - 1, []);
  const historyInfo = useCallback(() => ({
    index:  pointer.current,
    length: stack.current.length,
  }), []);

  const clearHistory = useCallback(() => {
    stack.current   = [];
    pointer.current = -1;
    notify();
  }, [notify]);

  return { saveSnapshot, undo, redo, canUndo, canRedo, historyInfo, clearHistory };
}
