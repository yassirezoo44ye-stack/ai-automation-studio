import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import { BaseCommand } from "../Command";
import { attachMeta, getMeta } from "../../../utils/fabricUtils";
import { uid } from "../../../utils/geometryUtils";
import { designBus } from "../../events/DesignEventBus";

export class AddObjectCommand extends BaseCommand {
  readonly description: string;
  private readonly objectJson: object;
  private addedId: string | null = null;

  constructor(
    private readonly factory: () => FabricObject,
    description = "Add object",
  ) {
    super();
    this.description = description;
    // capture factory result JSON for redo serialisation
    this.objectJson = {};
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    const obj = this.factory();
    if (!getMeta(obj)) attachMeta(obj, { id: uid() });
    this.addedId = getMeta(obj)!.id;
    canvas.add(obj);
    canvas.setActiveObject(obj);
    canvas.renderAll();

    designBus.emit("ObjectCreated", {
      objectId: this.addedId,
      meta: getMeta(obj)!,
      fabricObject: obj,
    });
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    if (!this.addedId) return;
    const obj = canvas.getObjects().find(o => getMeta(o)?.id === this.addedId);
    if (obj) {
      canvas.remove(obj);
      canvas.discardActiveObject();
      canvas.renderAll();
      designBus.emit("ObjectDeleted", { objectId: this.addedId, meta: getMeta(obj)! });
    }
  }
}
