/**
 * CommandManager — central command executor with undo/redo stack.
 * Replaces snapshot-based history for fine-grained operations.
 * Also accepts optional snapshot fallback for complex bulk operations.
 */
import type { Canvas as FabricCanvas } from "fabric";
import type { Command } from "./Command";
import { designBus } from "../events/DesignEventBus";

const MAX_STACK = 100;

export interface CommandManagerOptions {
  onHistoryChange?: (canUndo: boolean, canRedo: boolean, stackSize: number) => void;
}

export class CommandManager {
  private stack:   Command[] = [];
  private pointer: number    = -1;
  private locked   = false;
  private readonly opts: CommandManagerOptions;

  constructor(opts: CommandManagerOptions = {}) {
    this.opts = opts;
  }

  async execute(canvas: FabricCanvas, cmd: Command): Promise<void> {
    if (this.locked) return;

    // Truncate forward future when branching
    if (this.pointer < this.stack.length - 1) {
      this.stack = this.stack.slice(0, this.pointer + 1);
    }

    this.locked = true;
    try {
      await cmd.execute(canvas);
      this.stack.push(cmd);
      if (this.stack.length > MAX_STACK) this.stack.shift();
      else this.pointer += 1;

      designBus.emit("CommandExecuted", { description: cmd.description });
      this._notify();
    } finally {
      this.locked = false;
    }
  }

  async undo(canvas: FabricCanvas): Promise<void> {
    if (!this.canUndo() || this.locked) return;

    this.locked = true;
    try {
      const cmd = this.stack[this.pointer];
      await cmd.undo(canvas);
      this.pointer -= 1;
      canvas.renderAll();
      designBus.emit("CommandUndone", { description: cmd.description });
      this._notify();
    } finally {
      this.locked = false;
    }
  }

  async redo(canvas: FabricCanvas): Promise<void> {
    if (!this.canRedo() || this.locked) return;

    this.locked = true;
    try {
      this.pointer += 1;
      const cmd = this.stack[this.pointer];
      const fn = cmd.redo ?? cmd.execute;
      await fn.call(cmd, canvas);
      canvas.renderAll();
      designBus.emit("CommandRedone", { description: cmd.description });
      this._notify();
    } finally {
      this.locked = false;
    }
  }

  canUndo(): boolean { return this.pointer >= 0; }
  canRedo(): boolean { return this.pointer < this.stack.length - 1; }
  stackSize(): number { return this.stack.length; }

  clear(): void {
    this.stack   = [];
    this.pointer = -1;
    this._notify();
  }

  /** Get labels for history panel display */
  history(): Array<{ description: string; isCurrent: boolean }> {
    return this.stack.map((c, i) => ({
      description: c.description,
      isCurrent:   i === this.pointer,
    }));
  }

  private _notify(): void {
    this.opts.onHistoryChange?.(this.canUndo(), this.canRedo(), this.stack.length);
  }
}

/** Module-level singleton — shared across the design studio */
export const commandManager = new CommandManager();
