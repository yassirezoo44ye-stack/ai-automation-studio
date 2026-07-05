/**
 * Command system tests.
 * Uses a lightweight Fabric canvas mock — no DOM required.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { CommandManager } from "../core/commands/CommandManager";
import { BaseCommand } from "../core/commands/Command";
import type { Canvas as FabricCanvas } from "fabric";

// ── Minimal canvas mock ───────────────────────────────────────────────────────

function mockCanvas(): FabricCanvas {
  return {
    getObjects:         () => [],
    add:                vi.fn(),
    remove:             vi.fn(),
    renderAll:          vi.fn(),
    getActiveObjects:   () => [],
    setActiveObject:    vi.fn(),
    discardActiveObject: vi.fn(),
  } as unknown as FabricCanvas;
}

// ── Test command ──────────────────────────────────────────────────────────────

class CounterCommand extends BaseCommand {
  readonly description: string;
  static executed = 0;
  static undone   = 0;

  constructor(label = "counter") {
    super();
    this.description = label;
  }

  execute(): void { CounterCommand.executed++; }
  undo():    void { CounterCommand.undone++; }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("CommandManager", () => {
  let mgr: CommandManager;
  let canvas: FabricCanvas;

  beforeEach(() => {
    mgr    = new CommandManager();
    canvas = mockCanvas();
    CounterCommand.executed = 0;
    CounterCommand.undone   = 0;
  });

  it("executes a command and updates canUndo", async () => {
    expect(mgr.canUndo()).toBe(false);
    await mgr.execute(canvas, new CounterCommand());
    expect(CounterCommand.executed).toBe(1);
    expect(mgr.canUndo()).toBe(true);
    expect(mgr.canRedo()).toBe(false);
  });

  it("undo decrements pointer and calls cmd.undo()", async () => {
    await mgr.execute(canvas, new CounterCommand());
    await mgr.undo(canvas);
    expect(CounterCommand.undone).toBe(1);
    expect(mgr.canUndo()).toBe(false);
    expect(mgr.canRedo()).toBe(true);
  });

  it("redo re-executes after undo", async () => {
    await mgr.execute(canvas, new CounterCommand());
    await mgr.undo(canvas);
    await mgr.redo(canvas);
    expect(CounterCommand.executed).toBe(2);
    expect(mgr.canRedo()).toBe(false);
  });

  it("branching clears forward history", async () => {
    await mgr.execute(canvas, new CounterCommand("a"));
    await mgr.execute(canvas, new CounterCommand("b"));
    await mgr.undo(canvas);
    await mgr.execute(canvas, new CounterCommand("c")); // branch
    expect(mgr.canRedo()).toBe(false);
    expect(mgr.stackSize()).toBe(2);
  });

  it("history() returns labels with isCurrent flag", async () => {
    await mgr.execute(canvas, new CounterCommand("first"));
    await mgr.execute(canvas, new CounterCommand("second"));
    const h = mgr.history();
    expect(h).toHaveLength(2);
    expect(h[1].isCurrent).toBe(true);
    expect(h[0].isCurrent).toBe(false);
  });

  it("clear() resets everything", async () => {
    await mgr.execute(canvas, new CounterCommand());
    mgr.clear();
    expect(mgr.canUndo()).toBe(false);
    expect(mgr.stackSize()).toBe(0);
  });

  it("onHistoryChange callback fires on each state change", async () => {
    const changes: boolean[] = [];
    const m = new CommandManager({ onHistoryChange: (cu) => changes.push(cu) });
    await m.execute(canvas, new CounterCommand());
    await m.undo(canvas);
    expect(changes).toHaveLength(2);
    expect(changes[0]).toBe(true);   // after execute: canUndo=true
    expect(changes[1]).toBe(false);  // after undo: canUndo=false
  });
});
