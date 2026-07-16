import { useEffect, useRef, useCallback } from "react";
import {
  Canvas as FabricCanvas,
  Rect, Circle, Triangle, IText, FabricImage,
  PencilBrush, ActiveSelection,
  type FabricObject,
} from "fabric";
import type { Tool, CanvasPage } from "../types/canvas.types";
import {
  attachMeta, canvasToJSON, loadJSONToCanvas,
  generateThumbnail, getMeta,
} from "../utils/fabricUtils";
import { clamp, ZOOM_MIN, ZOOM_MAX, zoomToFit } from "../utils/geometryUtils";
import { uid } from "../utils/geometryUtils";

export interface UseFabricCanvasReturn {
  canvasRef:        React.RefObject<HTMLCanvasElement | null>;
  getCanvas:        () => FabricCanvas | null;
  addShape:         (tool: Tool) => void;
  addText:          () => void;
  addImage:         (src: string) => Promise<void>;
  deleteSelected:   () => void;
  copySelected:     () => void;
  pasteClipboard:   () => void;
  selectAll:        () => void;
  clearSelection:   () => void;
  bringForward:     () => void;
  sendBackward:     () => void;
  bringToFront:     () => void;
  sendToBack:       () => void;
  setActiveTool:    (tool: Tool) => void;
  zoomIn:           () => void;
  zoomOut:          () => void;
  zoomReset:        () => void;
  zoomToFitCanvas:  () => void;
  loadPage:         (page: CanvasPage) => Promise<void>;
  getJSON:          () => object;
  getThumbnail:     () => string;
}

export function useFabricCanvas(
  onObjectsChange: (json: object) => void,
  onSelectionChange: (ids: string[]) => void,
): UseFabricCanvasReturn {
  const canvasRef      = useRef<HTMLCanvasElement | null>(null);
  const fabricRef      = useRef<FabricCanvas | null>(null);
  const clipboardRef   = useRef<FabricObject[]>([]);

  // ── Init / destroy ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!canvasRef.current) return;

    const fc = new FabricCanvas(canvasRef.current, {
      width:               1280,
      height:              720,
      backgroundColor:     "#ffffff",
      selection:           true,
      preserveObjectStacking: true,
      renderOnAddRemove:   true,
    });

    fabricRef.current = fc;

    // Object change events
    const onMod = () => {
      if (fabricRef.current) onObjectsChange(canvasToJSON(fabricRef.current));
    };

    fc.on("object:added",    onMod);
    fc.on("object:removed",  onMod);
    fc.on("object:modified", onMod);

    // Selection events
    const onSel = () => {
      const ids = fc.getActiveObjects().map(o => getMeta(o)?.id ?? "").filter(Boolean);
      onSelectionChange(ids);
    };
    fc.on("selection:created",  onSel);
    fc.on("selection:updated",  onSel);
    fc.on("selection:cleared",  () => onSelectionChange([]));

    return () => {
      fc.dispose();
      fabricRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const getCanvas = useCallback(() => fabricRef.current, []);

  // ── Shape creation ──────────────────────────────────────────────────────────
  const addShape = useCallback((tool: Tool) => {
    const fc = fabricRef.current;
    if (!fc) return;

    const cx = (fc.width  ?? 640) / 2;
    const cy = (fc.height ?? 360) / 2;

    let obj: FabricObject;
    switch (tool) {
      case "rect":
        obj = new Rect({ left: cx - 60, top: cy - 40, width: 120, height: 80, fill: "#D4AF37" });
        break;
      case "circle":
        obj = new Circle({ left: cx - 50, top: cy - 50, radius: 50, fill: "#D4AF37" });
        break;
      case "triangle":
        obj = new Triangle({ left: cx - 60, top: cy - 50, width: 120, height: 100, fill: "#D4AF37" });
        break;
      default:
        obj = new Rect({ left: cx - 60, top: cy - 40, width: 120, height: 80, fill: "#D4AF37" });
    }

    attachMeta(obj, { id: uid(), type: "shape" });
    fc.add(obj);
    fc.setActiveObject(obj);
    fc.renderAll();
  }, []);

  const addText = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;

    const cx = (fc.width  ?? 640) / 2;
    const cy = (fc.height ?? 360) / 2;

    const txt = new IText("Double-click to edit", {
      left: cx - 100, top: cy - 20,
      fontFamily: "Inter, sans-serif",
      fontSize: 24,
      fill: "#111111",
    });
    attachMeta(txt, { id: uid(), type: "text" });
    fc.add(txt);
    fc.setActiveObject(txt);
    fc.renderAll();
  }, []);

  const addImage = useCallback(async (src: string) => {
    const fc = fabricRef.current;
    if (!fc) return;

    const img = await FabricImage.fromURL(src, { crossOrigin: "anonymous" });
    const maxW  = (fc.width  ?? 1280) * 0.5;
    const maxH  = (fc.height ?? 720)  * 0.5;
    const scale = Math.min(maxW / (img.width ?? 1), maxH / (img.height ?? 1), 1);
    img.scale(scale);
    img.set({
      left: ((fc.width  ?? 1280) - (img.width  ?? 0) * scale) / 2,
      top:  ((fc.height ?? 720)  - (img.height ?? 0) * scale) / 2,
    });
    attachMeta(img, { id: uid(), type: "image" });
    fc.add(img);
    fc.setActiveObject(img);
    fc.renderAll();
  }, []);

  // ── Object management ───────────────────────────────────────────────────────
  const deleteSelected = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;
    fc.getActiveObjects().forEach(obj => fc.remove(obj));
    fc.discardActiveObject();
    fc.renderAll();
  }, []);

  const copySelected = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;
    clipboardRef.current = fc.getActiveObjects();
  }, []);

  const pasteClipboard = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc || !clipboardRef.current.length) return;

    clipboardRef.current.forEach(async (obj) => {
      const clone = await obj.clone();
      clone.set({ left: (obj.left ?? 0) + 20, top: (obj.top ?? 0) + 20 });
      attachMeta(clone, { id: uid() });
      fc.add(clone);
    });
    fc.renderAll();
  }, []);

  const selectAll = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;
    fc.discardActiveObject();
    const objs = fc.getObjects();
    if (!objs.length) return;
    if (objs.length === 1) { fc.setActiveObject(objs[0]); }
    else { fc.setActiveObject(new ActiveSelection(objs, { canvas: fc })); }
    fc.renderAll();
  }, []);

  const clearSelection = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;
    fc.discardActiveObject();
    fc.renderAll();
  }, []);

  // ── Z-order ─────────────────────────────────────────────────────────────────
  const bringForward  = useCallback(() => { const fc = fabricRef.current; if (!fc) return; fc.getActiveObjects().forEach(o => fc.bringObjectForward(o));  fc.renderAll(); }, []);
  const sendBackward  = useCallback(() => { const fc = fabricRef.current; if (!fc) return; fc.getActiveObjects().forEach(o => fc.sendObjectBackwards(o));  fc.renderAll(); }, []);
  const bringToFront  = useCallback(() => { const fc = fabricRef.current; if (!fc) return; fc.getActiveObjects().forEach(o => fc.bringObjectToFront(o));   fc.renderAll(); }, []);
  const sendToBack    = useCallback(() => { const fc = fabricRef.current; if (!fc) return; fc.getActiveObjects().forEach(o => fc.sendObjectToBack(o));     fc.renderAll(); }, []);

  // ── Tool switching ──────────────────────────────────────────────────────────
  const setActiveTool = useCallback((tool: Tool) => {
    const fc = fabricRef.current;
    if (!fc) return;

    if (tool === "hand") {
      fc.isDrawingMode = false;
      fc.selection     = false;
      fc.defaultCursor = "grab";
      fc.getObjects().forEach(o => o.set({ selectable: false, evented: false }));
    } else if (tool === "pen") {
      fc.isDrawingMode = true;
      fc.freeDrawingBrush = new PencilBrush(fc);
      fc.freeDrawingBrush.width = 3;
      fc.freeDrawingBrush.color = "#111111";
    } else {
      fc.isDrawingMode = false;
      fc.selection     = true;
      fc.defaultCursor = "default";
      fc.getObjects().forEach(o => {
        const meta = getMeta(o);
        if (!meta?.locked) { o.set({ selectable: true, evented: true }); }
      });
    }
    fc.renderAll();
  }, []);

  // ── Zoom ────────────────────────────────────────────────────────────────────
  const zoomIn = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;
    const z = clamp(fc.getZoom() * 1.2, ZOOM_MIN, ZOOM_MAX);
    fc.setZoom(z);
  }, []);

  const zoomOut = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;
    const z = clamp(fc.getZoom() / 1.2, ZOOM_MIN, ZOOM_MAX);
    fc.setZoom(z);
  }, []);

  const zoomReset = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc) return;
    fc.setZoom(1);
    fc.setViewportTransform([1, 0, 0, 1, 0, 0]);
  }, []);

  const zoomToFitCanvas = useCallback(() => {
    const fc = fabricRef.current;
    if (!fc || !canvasRef.current) return;
    const container = canvasRef.current.parentElement;
    if (!container) return;
    const { clientWidth: vw, clientHeight: vh } = container;
    const z = zoomToFit(fc.width ?? 1280, fc.height ?? 720, vw, vh);
    fc.setZoom(z);
    const panX = (vw - (fc.width  ?? 1280) * z) / 2;
    const panY = (vh - (fc.height ?? 720)  * z) / 2;
    fc.setViewportTransform([z, 0, 0, z, panX, panY]);
  }, []);

  // ── Page load/save ──────────────────────────────────────────────────────────
  const loadPage = useCallback(async (page: CanvasPage) => {
    const fc = fabricRef.current;
    if (!fc) return;
    fc.set({ width: page.width, height: page.height });
    fc.backgroundColor = page.backgroundColor;
    if (page.json && Object.keys(page.json).length > 2) {
      await loadJSONToCanvas(fc, page.json);
    } else {
      fc.clear();
      fc.backgroundColor = page.backgroundColor;
      fc.renderAll();
    }
  }, []);

  const getJSON = useCallback((): object => {
    const fc = fabricRef.current;
    if (!fc) return {};
    return canvasToJSON(fc);
  }, []);

  const getThumbnail = useCallback((): string => {
    const fc = fabricRef.current;
    if (!fc) return "";
    return generateThumbnail(fc);
  }, []);

  return {
    canvasRef,
    getCanvas,
    addShape,
    addText,
    addImage,
    deleteSelected,
    copySelected,
    pasteClipboard,
    selectAll,
    clearSelection,
    bringForward,
    sendBackward,
    bringToFront,
    sendToBack,
    setActiveTool,
    zoomIn,
    zoomOut,
    zoomReset,
    zoomToFitCanvas,
    loadPage,
    getJSON,
    getThumbnail,
  };
}
