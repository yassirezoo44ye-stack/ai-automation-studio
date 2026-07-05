import type { Canvas as FabricCanvas } from "fabric";
import { BaseCommand } from "../Command";
import { findById } from "../../../utils/fabricUtils";
import { designBus } from "../../events/DesignEventBus";

interface Size { scaleX: number; scaleY: number; width?: number; height?: number }

export class ResizeObjectCommand extends BaseCommand {
  readonly description = "Resize object";
  private before: Map<string, Size> = new Map();

  constructor(
    private readonly ids: string[],
    private readonly after: Map<string, Size>,
  ) {
    super();
  }

  static snapshot(canvas: FabricCanvas, ids: string[]): Map<string, Size> {
    const map = new Map<string, Size>();
    for (const id of ids) {
      const obj = findById(canvas, id);
      if (obj) map.set(id, { scaleX: obj.scaleX ?? 1, scaleY: obj.scaleY ?? 1 });
    }
    return map;
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    if (this.before.size === 0) {
      for (const id of this.ids) {
        const obj = findById(canvas, id);
        if (obj) this.before.set(id, { scaleX: obj.scaleX ?? 1, scaleY: obj.scaleY ?? 1 });
      }
    }
    this._apply(canvas, this.after);
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    this._apply(canvas, this.before);
  }

  private _apply(canvas: FabricCanvas, sizes: Map<string, Size>): void {
    for (const [id, size] of sizes) {
      const obj = findById(canvas, id);
      if (!obj) continue;
      obj.set({ scaleX: size.scaleX, scaleY: size.scaleY });
      obj.setCoords();
      designBus.emit("ObjectUpdated", { objectId: id, changes: size as unknown as Record<string, unknown> });
    }
    canvas.renderAll();
  }
}
