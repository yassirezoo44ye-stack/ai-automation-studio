import type { Canvas as FabricCanvas, IText } from "fabric";
import { BaseCommand } from "../Command";
import { findById } from "../../../utils/fabricUtils";
import { designBus } from "../../events/DesignEventBus";

interface FontProps {
  fontFamily?: string;
  fontSize?: number;
  fontWeight?: string | number;
  fontStyle?: "normal" | "italic" | "oblique";
  textAlign?: "left" | "center" | "right" | "justify";
  lineHeight?: number;
  charSpacing?: number;
  underline?: boolean;
  linethrough?: boolean;
}

export class ChangeFontCommand extends BaseCommand {
  readonly description = "Change font";
  private before: Map<string, FontProps> = new Map();

  constructor(
    private readonly ids: string[],
    private readonly props: FontProps,
  ) {
    super();
  }

  async execute(canvas: FabricCanvas): Promise<void> {
    for (const id of this.ids) {
      const obj = findById(canvas, id) as IText | undefined;
      if (!obj || !("fontFamily" in obj)) continue;

      const prev: FontProps = {};
      for (const key of Object.keys(this.props) as (keyof FontProps)[]) {
        prev[key] = (obj as unknown as Record<string, unknown>)[key] as never;
      }
      this.before.set(id, prev);

      obj.set(this.props as Partial<IText>);
      designBus.emit("ObjectUpdated", { objectId: id, changes: this.props as Record<string, unknown> });
    }
    canvas.renderAll();
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    for (const [id, prev] of this.before) {
      const obj = findById(canvas, id) as IText | undefined;
      if (!obj || !("fontFamily" in obj)) continue;
      obj.set(prev as Partial<IText>);
      designBus.emit("ObjectUpdated", { objectId: id, changes: prev as Record<string, unknown> });
    }
    canvas.renderAll();
  }
}
