import type { Canvas as FabricCanvas } from "fabric";
import { BaseCommand } from "../Command";
import { findById } from "../../../utils/fabricUtils";
import { designBus } from "../../events/DesignEventBus";

type ColorProp = "fill" | "stroke" | "backgroundColor";

export class ChangeColorCommand extends BaseCommand {
  readonly description: string;
  private before: Map<string, string | null> = new Map();

  constructor(
    private readonly ids: string[],
    private readonly property: ColorProp,
    private readonly color: string,
  ) {
    super();
    this.description = `Change ${property}`;
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    for (const id of this.ids) {
      const obj = findById(canvas, id);
      if (!obj) continue;
      const prev = obj.get(this.property as keyof typeof obj);
      this.before.set(id, typeof prev === "string" ? prev : null);
      obj.set(this.property, this.color);
      designBus.emit("ObjectUpdated", { objectId: id, changes: { [this.property]: this.color } });
    }
    canvas.renderAll();
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    for (const [id, prevColor] of this.before) {
      const obj = findById(canvas, id);
      if (!obj) continue;
      obj.set(this.property, prevColor ?? "");
      designBus.emit("ObjectUpdated", { objectId: id, changes: { [this.property]: prevColor } });
    }
    canvas.renderAll();
  }
}
