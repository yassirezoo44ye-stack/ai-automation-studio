/**
 * Command pattern base — every canvas edit becomes a reversible Command.
 * Commands store the minimal state needed to execute, undo, and redo
 * without requiring full JSON snapshots on every operation.
 */
import type { Canvas as FabricCanvas } from "fabric";

export interface Command {
  /** Human-readable label shown in the history panel */
  readonly description: string;

  /** Apply the effect to the canvas */
  execute(canvas: FabricCanvas): void | Promise<void>;

  /** Revert to the state before execute() was called */
  undo(canvas: FabricCanvas): void | Promise<void>;

  /** Re-apply after an undo (default: delegate to execute) */
  redo?(canvas: FabricCanvas): void | Promise<void>;
}

/** Abstract base — redo delegates to execute by default */
export abstract class BaseCommand implements Command {
  abstract readonly description: string;
  abstract execute(canvas: FabricCanvas): void | Promise<void>;
  abstract undo(canvas: FabricCanvas): void | Promise<void>;

  redo(canvas: FabricCanvas): void | Promise<void> {
    return this.execute(canvas);
  }
}
