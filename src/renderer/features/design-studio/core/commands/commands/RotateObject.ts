import type { Canvas as FabricCanvas } from "fabric";
import { BaseCommand } from "../Command";
import { findById } from "../../../utils/fabricUtils";
import { designBus } from "../../events/DesignEventBus";

export class RotateObjectCommand extends BaseCommand {
  readonly description = "Rotate object";
  private before: Map<string, number> = new Map();

  constructor(
    private readonly ids: string[],
    private readonly after: Map<string, number>,
  ) {
    super();
  }

  static snapshot(canvas: FabricCanvas, ids: string[]): Map<string, number> {
    const map = new Map<string, number>();
    for (const id of ids) {
      const obj = findById(canvas, id);
      if (obj) map.set(id, obj.angle ?? 0);
    }
    return map;
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    if (this.before.size === 0) {
      for (const id of this.ids) {
        const obj = findById(canvas, id);
        if (obj) this.before.set(id, obj.angle ?? 0);
      }
    }
    this._apply(canvas, this.after);
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    this._apply(canvas, this.before);
  }

  private _apply(canvas: FabricCanvas, angles: Map<string, number>): void {
    for (const [id, angle] of angles) {
      const obj = findById(canvas, id);
      if (!obj) continue;
      obj.set({ angle });
      obj.setCoords();
      designBus.emit("ObjectUpdated", { objectId: id, changes: { angle } });
    }
    canvas.renderAll();
  }
}
