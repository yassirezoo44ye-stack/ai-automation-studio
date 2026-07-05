/**
 * Smart Layout — auto-layout, constraints, padding, gap, alignment, distribution.
 * Inspired by Figma Auto Layout. Operates on Fabric canvas objects.
 */
import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import { findById } from "../../utils/fabricUtils";

// ── Types ─────────────────────────────────────────────────────────────────────

export type LayoutDirection  = "horizontal" | "vertical" | "wrap";
export type AlignItems       = "start" | "center" | "end" | "stretch";
export type JustifyContent   = "start" | "center" | "end" | "space-between" | "space-around" | "space-evenly";
export type SizingMode       = "fixed" | "fill" | "hug";
export type ConstraintH      = "left" | "right" | "center" | "left-right" | "scale";
export type ConstraintV      = "top" | "bottom" | "center" | "top-bottom" | "scale";

export interface AutoLayoutConfig {
  direction:      LayoutDirection;
  gap:            number;
  paddingTop:     number;
  paddingRight:   number;
  paddingBottom:  number;
  paddingLeft:    number;
  alignItems:     AlignItems;
  justifyContent: JustifyContent;
  childSizing:    SizingMode;
  wrap:           boolean;
}

export interface ConstraintConfig {
  horizontal: ConstraintH;
  vertical:   ConstraintV;
}

export interface ResponsiveConfig {
  parentWidth:  number;
  parentHeight: number;
  constraints:  Record<string, ConstraintConfig>;  // objectId → constraints
}

// ── Defaults ──────────────────────────────────────────────────────────────────

export function defaultAutoLayout(): AutoLayoutConfig {
  return {
    direction:      "horizontal",
    gap:            16,
    paddingTop:     16,
    paddingRight:   16,
    paddingBottom:  16,
    paddingLeft:    16,
    alignItems:     "start",
    justifyContent: "start",
    childSizing:    "hug",
    wrap:           false,
  };
}

// ── Layout engine ─────────────────────────────────────────────────────────────

export class SmartLayoutEngine {

  /** Apply auto-layout to a list of objects within a container */
  applyAutoLayout(
    canvas: FabricCanvas,
    containerBounds: { left: number; top: number; width: number; height: number },
    childIds: string[],
    config: AutoLayoutConfig,
  ): void {
    const children = childIds
      .map(id => findById(canvas, id))
      .filter((o): o is FabricObject => !!o);

    if (!children.length) return;

    const {
      direction, gap,
      paddingTop, paddingRight, paddingBottom, paddingLeft,
      alignItems, justifyContent,
    } = config;

    const innerW = containerBounds.width  - paddingLeft - paddingRight;
    const innerH = containerBounds.height - paddingTop  - paddingBottom;

    if (direction === "horizontal") {
      this._layoutHorizontal(children, containerBounds, innerW, innerH, gap, paddingLeft, paddingTop, alignItems, justifyContent);
    } else if (direction === "vertical") {
      this._layoutVertical(children, containerBounds, innerW, innerH, gap, paddingLeft, paddingTop, alignItems, justifyContent);
    }

    canvas.renderAll();
  }

  /** Apply constraints for responsive resizing */
  applyConstraints(
    canvas: FabricCanvas,
    oldParent: { width: number; height: number },
    newParent: { width: number; height: number },
    config: ResponsiveConfig,
  ): void {
    const wRatio = newParent.width  / oldParent.width;
    const hRatio = newParent.height / oldParent.height;

    for (const [id, constraint] of Object.entries(config.constraints)) {
      const obj = findById(canvas, id);
      if (!obj) continue;

      const left   = obj.left   ?? 0;
      const top    = obj.top    ?? 0;
      const width  = (obj.width  ?? 0) * (obj.scaleX ?? 1);
      const height = (obj.height ?? 0) * (obj.scaleY ?? 1);

      // Horizontal constraints
      switch (constraint.horizontal) {
        case "left":        /* keep left as-is */ break;
        case "right":       obj.set({ left: newParent.width - (oldParent.width - left) }); break;
        case "center":      obj.set({ left: newParent.width / 2 - width / 2 }); break;
        case "left-right":  obj.set({ left, scaleX: ((newParent.width - (oldParent.width - left - width)) / width) * (obj.scaleX ?? 1) }); break;
        case "scale":       obj.set({ left: left * wRatio, scaleX: (obj.scaleX ?? 1) * wRatio }); break;
      }

      // Vertical constraints
      switch (constraint.vertical) {
        case "top":         /* keep top as-is */ break;
        case "bottom":      obj.set({ top: newParent.height - (oldParent.height - top) }); break;
        case "center":      obj.set({ top: newParent.height / 2 - height / 2 }); break;
        case "top-bottom":  obj.set({ top, scaleY: ((newParent.height - (oldParent.height - top - height)) / height) * (obj.scaleY ?? 1) }); break;
        case "scale":       obj.set({ top: top * hRatio, scaleY: (obj.scaleY ?? 1) * hRatio }); break;
      }

      obj.setCoords();
    }

    canvas.renderAll();
  }

  /** Distribute objects evenly */
  distributeEvenly(canvas: FabricCanvas, objectIds: string[], axis: "horizontal" | "vertical"): void {
    const objs = objectIds
      .map(id => findById(canvas, id))
      .filter((o): o is FabricObject => !!o)
      .sort((a, b) => axis === "horizontal" ? (a.left ?? 0) - (b.left ?? 0) : (a.top ?? 0) - (b.top ?? 0));

    if (objs.length < 3) return;

    const first = objs[0];
    const last  = objs[objs.length - 1];

    const firstPos = axis === "horizontal"
      ? (first.left ?? 0)
      : (first.top  ?? 0);

    const lastPos  = axis === "horizontal"
      ? (last.left ?? 0) + (last.getBoundingRect().width)
      : (last.top  ?? 0) + (last.getBoundingRect().height);

    const totalSize = objs.reduce((s, o) => {
      const br = o.getBoundingRect();
      return s + (axis === "horizontal" ? br.width : br.height);
    }, 0);

    const totalGap    = lastPos - firstPos - totalSize;
    const gapBetween  = totalGap / (objs.length - 1);

    let cursor = firstPos;
    objs.forEach(obj => {
      if (axis === "horizontal") obj.set({ left: cursor });
      else                       obj.set({ top:  cursor });
      const br = obj.getBoundingRect();
      cursor += (axis === "horizontal" ? br.width : br.height) + gapBetween;
      obj.setCoords();
    });

    canvas.renderAll();
  }

  // ── Private helpers ─────────────────────────────────────────────────────────

  private _layoutHorizontal(
    children: FabricObject[],
    container: { left: number; top: number },
    innerW: number,
    innerH: number,
    gap: number,
    paddingLeft: number,
    paddingTop: number,
    alignItems: AlignItems,
    _justifyContent: JustifyContent,
  ): void {
    let x = container.left + paddingLeft;

    children.forEach(child => {
      const br = child.getBoundingRect();
      let y = container.top + paddingTop;

      if (alignItems === "center")  y += (innerH - br.height) / 2;
      else if (alignItems === "end") y += innerH - br.height;

      child.set({ left: x, top: y });
      child.setCoords();
      x += br.width + gap;
    });
  }

  private _layoutVertical(
    children: FabricObject[],
    container: { left: number; top: number },
    innerW: number,
    _innerH: number,
    gap: number,
    paddingLeft: number,
    paddingTop: number,
    alignItems: AlignItems,
    _justifyContent: JustifyContent,
  ): void {
    let y = container.top + paddingTop;

    children.forEach(child => {
      const br = child.getBoundingRect();
      let x = container.left + paddingLeft;

      if (alignItems === "center")  x += (innerW - br.width) / 2;
      else if (alignItems === "end") x += innerW - br.width;

      child.set({ left: x, top: y });
      child.setCoords();
      y += br.height + gap;
    });
  }
}

export const smartLayout = new SmartLayoutEngine();
