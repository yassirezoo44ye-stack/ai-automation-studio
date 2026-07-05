// Geometry helpers for the canvas engine

export interface Point { x: number; y: number }
export interface Rect  { x: number; y: number; width: number; height: number }
export interface BBox  { left: number; top: number; right: number; bottom: number }

// ── Point ops ─────────────────────────────────────────────────────────────────
export function distance(a: Point, b: Point): number {
  return Math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2);
}

export function midpoint(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

// ── Snap helpers ──────────────────────────────────────────────────────────────
export function snapToGrid(value: number, gridSize: number): number {
  return Math.round(value / gridSize) * gridSize;
}

export function snapPoint(p: Point, gridSize: number): Point {
  return { x: snapToGrid(p.x, gridSize), y: snapToGrid(p.y, gridSize) };
}

// ── Rectangle helpers ─────────────────────────────────────────────────────────
export function rectContainsPoint(r: Rect, p: Point): boolean {
  return p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height;
}

export function rectsIntersect(a: Rect, b: Rect): boolean {
  return !(a.x + a.width < b.x || b.x + b.width < a.x ||
           a.y + a.height < b.y || b.y + b.height < a.y);
}

export function bboxToRect(bbox: BBox): Rect {
  return {
    x: bbox.left,
    y: bbox.top,
    width: bbox.right - bbox.left,
    height: bbox.bottom - bbox.top,
  };
}

// ── Alignment helpers ─────────────────────────────────────────────────────────
export type AlignDir = "left" | "right" | "top" | "bottom" | "centerH" | "centerV";

export function alignRects(
  rects: Array<Rect & { id: string }>,
  dir: AlignDir,
): Array<Rect & { id: string }> {
  if (rects.length < 2) return rects;

  const xs    = rects.map(r => r.x);
  const ys    = rects.map(r => r.y);
  const xs2   = rects.map(r => r.x + r.width);
  const ys2   = rects.map(r => r.y + r.height);
  const minX  = Math.min(...xs);
  const minY  = Math.min(...ys);
  const maxX  = Math.max(...xs2);
  const maxY  = Math.max(...ys2);
  const ctrX  = (minX + maxX) / 2;
  const ctrY  = (minY + maxY) / 2;

  return rects.map(r => {
    const n = { ...r };
    if (dir === "left")    n.x = minX;
    if (dir === "right")   n.x = maxX - r.width;
    if (dir === "top")     n.y = minY;
    if (dir === "bottom")  n.y = maxY - r.height;
    if (dir === "centerH") n.x = ctrX - r.width / 2;
    if (dir === "centerV") n.y = ctrY - r.height / 2;
    return n;
  });
}

// ── Angle helpers ─────────────────────────────────────────────────────────────
export function degToRad(deg: number): number { return (deg * Math.PI) / 180; }
export function radToDeg(rad: number): number { return (rad * 180) / Math.PI; }

export function rotatePoint(p: Point, origin: Point, angleDeg: number): Point {
  const rad = degToRad(angleDeg);
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  const dx  = p.x - origin.x;
  const dy  = p.y - origin.y;
  return {
    x: origin.x + dx * cos - dy * sin,
    y: origin.y + dx * sin + dy * cos,
  };
}

// ── Zoom helpers ──────────────────────────────────────────────────────────────
export const ZOOM_MIN   = 0.05;
export const ZOOM_MAX   = 20;
export const ZOOM_STEPS = [0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5, 8, 10, 20];

export function zoomToFit(
  contentW: number,
  contentH: number,
  viewportW: number,
  viewportH: number,
  padding = 80,
): number {
  const fw = (viewportW - padding * 2) / contentW;
  const fh = (viewportH - padding * 2) / contentH;
  return clamp(Math.min(fw, fh), ZOOM_MIN, ZOOM_MAX);
}

export function nextZoomStep(current: number, direction: "in" | "out"): number {
  if (direction === "in") {
    return ZOOM_STEPS.find(z => z > current + 1e-6) ?? ZOOM_MAX;
  }
  return [...ZOOM_STEPS].reverse().find(z => z < current - 1e-6) ?? ZOOM_MIN;
}

// ── Canvas coordinate transforms ──────────────────────────────────────────────
export function screenToCanvas(
  screenX: number,
  screenY: number,
  containerRect: DOMRect,
  zoom: number,
  panX: number,
  panY: number,
): Point {
  return {
    x: (screenX - containerRect.left - panX) / zoom,
    y: (screenY - containerRect.top  - panY) / zoom,
  };
}

// ── Unique ID ──────────────────────────────────────────────────────────────────
export function uid(): string {
  return `ds_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}
