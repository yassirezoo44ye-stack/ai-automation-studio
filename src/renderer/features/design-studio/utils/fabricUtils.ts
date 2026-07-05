import type { Canvas as FabricCanvas, FabricObject, TOptions, ObjectEvents } from "fabric";
import type { ElementMeta, FabricObjWithMeta } from "../types/canvas.types";
import { uid } from "./geometryUtils";

// ── Meta attachment ────────────────────────────────────────────────────────────

export function attachMeta(obj: FabricObject, meta: Partial<ElementMeta> = {}): void {
  const extended = obj as FabricObjWithMeta;
  extended._meta = {
    id:      meta.id      ?? uid(),
    name:    meta.name    ?? inferName(obj),
    type:    meta.type    ?? inferType(obj),
    locked:  meta.locked  ?? false,
    visible: meta.visible ?? true,
  };
}

export function getMeta(obj: FabricObject): ElementMeta | undefined {
  return (obj as FabricObjWithMeta)._meta;
}

export function getOrCreateMeta(obj: FabricObject): ElementMeta {
  const extended = obj as FabricObjWithMeta;
  if (!extended._meta) attachMeta(obj);
  return extended._meta!;
}

// ── Type inference ─────────────────────────────────────────────────────────────

function inferType(obj: FabricObject): ElementMeta["type"] {
  const t = obj.type ?? "";
  if (t === "i-text" || t === "text" || t === "textbox") return "text";
  if (t === "image")  return "image";
  if (t === "group")  return "group";
  if (["rect","circle","triangle","polygon","path","ellipse"].includes(t)) return "shape";
  return "shape";
}

function inferName(obj: FabricObject): string {
  const t = obj.type ?? "object";
  const cap = t.charAt(0).toUpperCase() + t.slice(1);
  return cap;
}

// ── Object helpers ────────────────────────────────────────────────────────────

export function getAllObjects(canvas: FabricCanvas): FabricObject[] {
  return canvas.getObjects().filter(o => {
    const meta = getMeta(o);
    return !meta || meta.type !== "frame";
  });
}

export function findById(canvas: FabricCanvas, id: string): FabricObject | undefined {
  return canvas.getObjects().find(o => getMeta(o)?.id === id);
}

export function setLocked(obj: FabricObject, locked: boolean): void {
  const meta = getOrCreateMeta(obj);
  meta.locked = locked;
  obj.set({
    selectable:     !locked,
    evented:        !locked,
    lockMovementX:  locked,
    lockMovementY:  locked,
    lockRotation:   locked,
    lockScalingX:   locked,
    lockScalingY:   locked,
  } as TOptions<ObjectEvents>);
}

export function setVisible(obj: FabricObject, visible: boolean): void {
  const meta = getOrCreateMeta(obj);
  meta.visible = visible;
  obj.set("visible" as keyof TOptions<ObjectEvents>, visible);
}

// ── Canvas serialisation ──────────────────────────────────────────────────────

export function canvasToJSON(canvas: FabricCanvas): object {
  const json = canvas.toObject(["_meta"]);
  return json as object;
}

export async function loadJSONToCanvas(
  canvas: FabricCanvas,
  json: object,
): Promise<void> {
  await canvas.loadFromJSON(json as Parameters<typeof canvas.loadFromJSON>[0]);
  // Re-attach meta for any objects that lost it (shouldn't happen, but safety check)
  canvas.getObjects().forEach(obj => {
    if (!(obj as FabricObjWithMeta)._meta) attachMeta(obj);
  });
  canvas.renderAll();
}

// ── Alignment ─────────────────────────────────────────────────────────────────

export type AlignTarget = "left" | "right" | "top" | "bottom" | "centerH" | "centerV";

export function alignObjects(canvas: FabricCanvas, target: AlignTarget): void {
  const selection = canvas.getActiveObjects();
  if (selection.length < 2) return;

  const bounds = selection.reduce(
    (acc, obj) => {
      const b = obj.getBoundingRect();
      return {
        left:   Math.min(acc.left,   b.left),
        top:    Math.min(acc.top,    b.top),
        right:  Math.max(acc.right,  b.left + b.width),
        bottom: Math.max(acc.bottom, b.top  + b.height),
      };
    },
    { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity },
  );

  selection.forEach(obj => {
    const b = obj.getBoundingRect();
    if (target === "left")    obj.set({ left: bounds.left });
    if (target === "right")   obj.set({ left: bounds.right  - b.width  });
    if (target === "top")     obj.set({ top:  bounds.top  });
    if (target === "bottom")  obj.set({ top:  bounds.bottom - b.height });
    if (target === "centerH") obj.set({ left: (bounds.left + bounds.right)  / 2 - b.width  / 2 });
    if (target === "centerV") obj.set({ top:  (bounds.top  + bounds.bottom) / 2 - b.height / 2 });
    obj.setCoords();
  });
  canvas.renderAll();
}

export function distributeObjects(
  canvas: FabricCanvas,
  axis: "horizontal" | "vertical",
): void {
  const selection = canvas.getActiveObjects();
  if (selection.length < 3) return;

  const sorted = [...selection].sort((a, b) =>
    axis === "horizontal" ? a.left! - b.left! : a.top! - b.top!,
  );

  const first = sorted[0];
  const last  = sorted[sorted.length - 1];
  const firstB = first.getBoundingRect();
  const lastB  = last.getBoundingRect();

  const totalSpan  = axis === "horizontal"
    ? (lastB.left + lastB.width) - firstB.left
    : (lastB.top  + lastB.height) - firstB.top;
  const totalSizes = sorted.reduce((s, o) => {
    const b = o.getBoundingRect();
    return s + (axis === "horizontal" ? b.width : b.height);
  }, 0);
  const gap = (totalSpan - totalSizes) / (sorted.length - 1);

  let pos = axis === "horizontal" ? firstB.left + firstB.width + gap
                                  : firstB.top  + firstB.height + gap;
  sorted.slice(1, -1).forEach(obj => {
    if (axis === "horizontal") { obj.set({ left: pos }); pos += obj.getBoundingRect().width  + gap; }
    else                       { obj.set({ top:  pos }); pos += obj.getBoundingRect().height + gap; }
    obj.setCoords();
  });
  canvas.renderAll();
}

// ── Thumbnail generation ──────────────────────────────────────────────────────

export function generateThumbnail(
  canvas: FabricCanvas,
  maxW = 320,
  maxH = 180,
): string {
  const w = canvas.width  ?? 1280;
  const h = canvas.height ?? 720;
  const scale = Math.min(maxW / w, maxH / h);
  return canvas.toDataURL({ multiplier: scale, format: "jpeg", quality: 0.6 });
}
