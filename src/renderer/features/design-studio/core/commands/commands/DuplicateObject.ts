import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import { BaseCommand } from "../Command";
import { attachMeta, getMeta } from "../../../utils/fabricUtils";
import { uid } from "../../../utils/geometryUtils";
import { designBus } from "../../events/DesignEventBus";

const OFFSET = 20;

export class DuplicateObjectCommand extends BaseCommand {
  readonly description = "Duplicate object(s)";
  private clonedIds: string[] = [];

  constructor(private readonly sourceIds: string[]) {
    super();
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    this.clonedIds = [];
    const sources = canvas.getObjects().filter(o => this.sourceIds.includes(getMeta(o)?.id ?? ""));

    for (const src of sources) {
      const clone: FabricObject = await src.clone();
      clone.set({ left: (src.left ?? 0) + OFFSET, top: (src.top ?? 0) + OFFSET });
      const newId = uid();
      attachMeta(clone, { id: newId, type: getMeta(src)?.type });
      this.clonedIds.push(newId);
      canvas.add(clone);
      designBus.emit("ObjectCreated", { objectId: newId, meta: getMeta(clone)!, fabricObject: clone });
    }

    canvas.renderAll();
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    for (const id of this.clonedIds) {
      const obj = canvas.getObjects().find(o => getMeta(o)?.id === id);
      if (obj) {
        canvas.remove(obj);
        designBus.emit("ObjectDeleted", { objectId: id, meta: getMeta(obj)! });
      }
    }
    canvas.discardActiveObject();
    canvas.renderAll();
  }
}
