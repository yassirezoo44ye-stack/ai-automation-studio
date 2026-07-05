import type { Canvas as FabricCanvas } from "fabric";
import { BaseCommand } from "../Command";
import { findById, setLocked, getMeta } from "../../../utils/fabricUtils";
import { designBus } from "../../events/DesignEventBus";

export class LockObjectCommand extends BaseCommand {
  readonly description: string;
  private before: Map<string, boolean> = new Map();

  constructor(
    private readonly ids: string[],
    private readonly locked: boolean,
  ) {
    super();
    this.description = locked ? "Lock object(s)" : "Unlock object(s)";
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    for (const id of this.ids) {
      const obj = findById(canvas, id);
      if (!obj) continue;
      this.before.set(id, getMeta(obj)?.locked ?? false);
      setLocked(obj, this.locked);
      designBus.emit("ObjectUpdated", { objectId: id, changes: { locked: this.locked } });
    }
    canvas.renderAll();
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    for (const [id, wasLocked] of this.before) {
      const obj = findById(canvas, id);
      if (obj) {
        setLocked(obj, wasLocked);
        designBus.emit("ObjectUpdated", { objectId: id, changes: { locked: wasLocked } });
      }
    }
    canvas.renderAll();
  }
}

export class UnlockObjectCommand extends LockObjectCommand {
  constructor(ids: string[]) { super(ids, false); }
}
