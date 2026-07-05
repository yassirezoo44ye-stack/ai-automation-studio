import type { Canvas as FabricCanvas } from "fabric";
import { BaseCommand } from "../Command";
import { findById } from "../../../utils/fabricUtils";
import { designBus } from "../../events/DesignEventBus";

interface Pos { left: number; top: number }

export class MoveObjectCommand extends BaseCommand {
  readonly description = "Move object";
  private readonly before: Map<string, Pos> = new Map();

  constructor(
    private readonly ids: string[],
    private readonly after: Map<string, Pos>,
  ) {
    super();
  }

  /** Call before the move to capture current positions */
  static snapshot(canvas: FabricCanvas, ids: string[]): Map<string, Pos> {
    const map = new Map<string, Pos>();
    for (const id of ids) {
      const obj = findById(canvas, id);
      if (obj) map.set(id, { left: obj.left ?? 0, top: obj.top ?? 0 });
    }
    return map;
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    // Capture before positions first time
    if (this.before.size === 0) {
      for (const id of this.ids) {
        const obj = findById(canvas, id);
        if (obj) this.before.set(id, { left: obj.left ?? 0, top: obj.top ?? 0 });
      }
    }
    this._apply(canvas, this.after);
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    this._apply(canvas, this.before);
  }

  private _apply(canvas: FabricCanvas, positions: Map<string, Pos>): void {
    for (const [id, pos] of positions) {
      const obj = findById(canvas, id);
      if (!obj) continue;
      obj.set({ left: pos.left, top: pos.top });
      obj.setCoords();
      designBus.emit("ObjectUpdated", { objectId: id, changes: pos as unknown as Record<string, unknown> });
    }
    canvas.renderAll();
  }
}
