import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import { BaseCommand } from "../Command";
import { getMeta, attachMeta } from "../../../utils/fabricUtils";
import { designBus } from "../../events/DesignEventBus";

interface SavedObject {
  objectJson: object;
  index: number;
}

export class DeleteObjectCommand extends BaseCommand {
  readonly description = "Delete object(s)";
  private saved: SavedObject[] = [];

  constructor(private readonly targetIds: string[]) {
    super();
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    this.saved = [];
    const objs = canvas.getObjects();

    for (const id of this.targetIds) {
      const idx = objs.findIndex(o => getMeta(o)?.id === id);
      if (idx === -1) continue;
      const obj = objs[idx];
      this.saved.push({ objectJson: obj.toObject(["_meta"]), index: idx });
      canvas.remove(obj);
      designBus.emit("ObjectDeleted", { objectId: id, meta: getMeta(obj)! });
    }

    canvas.discardActiveObject();
    canvas.renderAll();
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    // Restore in original order
    const sorted = [...this.saved].sort((a, b) => a.index - b.index);

    for (const { objectJson } of sorted) {
      const [obj] = await canvas.loadFromJSON({
        version: "6.6.0",
        objects: [objectJson],
      } as Parameters<typeof canvas.loadFromJSON>[0]).then(() => {
        const all = canvas.getObjects();
        return all.slice(-1);
      });

      if (obj) {
        if (!getMeta(obj)) attachMeta(obj);
        const meta = getMeta(obj)!;
        designBus.emit("ObjectCreated", { objectId: meta.id, meta, fabricObject: obj });
      }
    }

    canvas.renderAll();
  }
}
