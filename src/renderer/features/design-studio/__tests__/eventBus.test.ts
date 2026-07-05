/**
 * DesignEventBus tests.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { DesignEventBus } from "../core/events/DesignEventBus";

describe("DesignEventBus", () => {
  let bus: DesignEventBus;

  beforeEach(() => { bus = new DesignEventBus(); });

  it("calls a subscriber when event is emitted", () => {
    const handler = vi.fn();
    bus.on("ObjectCreated", handler as never);
    bus.emit("ObjectDeleted", { objectId: "x", meta: { id: "x", name: "r", type: "shape", locked: false, visible: true } });
    expect(handler).not.toHaveBeenCalled();
    bus.emit("ObjectCreated", { objectId: "a", meta: { id: "a", name: "r", type: "shape", locked: false, visible: true }, fabricObject: {} as never });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("off() unsubscribes handler", () => {
    const handler = vi.fn();
    bus.on("PageCreated", handler as never);
    bus.off("PageCreated", handler as never);
    bus.emit("PageCreated", { pageId: "p1", name: "Page 1" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("unsubscribe fn returned from on() works", () => {
    const handler = vi.fn();
    const unsub = bus.on("PageDeleted", handler as never);
    unsub();
    bus.emit("PageDeleted", { pageId: "p2" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("once() fires exactly once", () => {
    const handler = vi.fn();
    bus.once("ExportStarted", handler as never);
    bus.emit("ExportStarted", { format: "png", pageIds: [] });
    bus.emit("ExportStarted", { format: "png", pageIds: [] });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("failing handler does not block other handlers", () => {
    bus.on("CommandExecuted", () => { throw new Error("boom"); });
    const good = vi.fn();
    bus.on("CommandExecuted", good);
    expect(() => bus.emit("CommandExecuted", { description: "test" })).not.toThrow();
    expect(good).toHaveBeenCalled();
  });

  it("handlerCount() returns correct count", () => {
    const h = vi.fn();
    expect(bus.handlerCount("SelectionChanged")).toBe(0);
    bus.on("SelectionChanged", h as never);
    expect(bus.handlerCount("SelectionChanged")).toBe(1);
  });

  it("clear() removes all handlers for an event", () => {
    const h = vi.fn();
    bus.on("TokenCreated", h as never);
    bus.clear("TokenCreated");
    bus.emit("TokenCreated", { tokenId: "t1", name: "x", category: "color" });
    expect(h).not.toHaveBeenCalled();
  });
});
