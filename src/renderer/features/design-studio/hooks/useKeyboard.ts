import { useEffect, useCallback } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import type { Tool } from "../types/canvas.types";

interface UseKeyboardOptions {
  getCanvas:    () => FabricCanvas | null;
  undo:         () => void;
  redo:         () => void;
  onToolChange: (tool: Tool) => void;
  onDelete:     () => void;
  onCopy:       () => void;
  onPaste:      () => void;
  onSelectAll:  () => void;
  onEscape:     () => void;
  onZoomIn:     () => void;
  onZoomOut:    () => void;
  onZoomReset:  () => void;
  enabled?:     boolean;
}

const TOOL_SHORTCUTS: Record<string, Tool> = {
  v: "select",
  h: "hand",
  t: "text",
  r: "rect",
  o: "circle",
  l: "line",
  p: "pen",
  i: "eyedropper",
  c: "crop",
};

export function useKeyboard(opts: UseKeyboardOptions): void {
  const {
    getCanvas, undo, redo, onToolChange, onDelete, onCopy,
    onPaste, onSelectAll, onEscape, onZoomIn, onZoomOut, onZoomReset,
    enabled = true,
  } = opts;

  const handler = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    // Don't capture when user is typing in an input/textarea/contenteditable
    if (
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable
    ) return;

    const ctrl = e.ctrlKey || e.metaKey;
    const key  = e.key.toLowerCase();

    // Undo / Redo
    if (ctrl && key === "z" && !e.shiftKey) { e.preventDefault(); undo(); return; }
    if (ctrl && (key === "y" || (key === "z" && e.shiftKey))) { e.preventDefault(); redo(); return; }

    // Copy / Paste / Select All
    if (ctrl && key === "c") { onCopy();      return; }
    if (ctrl && key === "v") { e.preventDefault(); onPaste(); return; }
    if (ctrl && key === "a") { e.preventDefault(); onSelectAll(); return; }

    // Zoom
    if (ctrl && (key === "=" || key === "+")) { e.preventDefault(); onZoomIn();    return; }
    if (ctrl && key === "-")                  { e.preventDefault(); onZoomOut();   return; }
    if (ctrl && key === "0")                  { e.preventDefault(); onZoomReset(); return; }

    // Delete selected objects
    if (key === "delete" || key === "backspace") {
      const canvas = getCanvas();
      if (!canvas) return;
      if (canvas.getActiveObjects().length) { e.preventDefault(); onDelete(); }
      return;
    }

    // Escape
    if (key === "escape") { onEscape(); return; }

    // Tool shortcuts (no modifier)
    if (!ctrl && !e.shiftKey && !e.altKey && key in TOOL_SHORTCUTS) {
      onToolChange(TOOL_SHORTCUTS[key]);
    }
  }, [undo, redo, onCopy, onPaste, onSelectAll, onZoomIn, onZoomOut, onZoomReset,
      onDelete, onEscape, onToolChange, getCanvas]);

  useEffect(() => {
    if (!enabled) return;
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handler, enabled]);
}
