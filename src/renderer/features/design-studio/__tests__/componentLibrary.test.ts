/**
 * Component Library tests.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { ComponentLibrary, createComponent } from "../features/components/ComponentLibrary";
import { DEFAULT_COMPONENTS } from "../features/components/DefaultComponents";

describe("ComponentLibrary", () => {
  let lib: ComponentLibrary;

  beforeEach(() => { lib = new ComponentLibrary(); });

  it("adds and retrieves a component", () => {
    const c = createComponent("Btn", "button", {});
    lib.add(c);
    expect(lib.get(c.id)).toBeDefined();
    expect(lib.get(c.id)?.name).toBe("Btn");
  });

  it("filters by category", () => {
    lib.add(createComponent("Btn",  "button", {}));
    lib.add(createComponent("Card", "card",   {}));
    expect(lib.byCategory("button")).toHaveLength(1);
    expect(lib.byCategory("card")).toHaveLength(1);
  });

  it("links and unlinks instances", () => {
    const c = createComponent("Hero", "hero", {});
    lib.add(c);
    lib.linkInstance(c.id, "obj_1");
    lib.linkInstance(c.id, "obj_2");
    expect(lib.get(c.id)?.instances).toContain("obj_1");

    lib.unlinkInstance("obj_1");
    expect(lib.get(c.id)?.instances).not.toContain("obj_1");
    expect(lib.get(c.id)?.instances).toContain("obj_2");
  });

  it("findByInstance returns the right component", () => {
    const c = createComponent("Card", "card", {});
    lib.add(c);
    lib.linkInstance(c.id, "canvas_obj_99");
    expect(lib.findByInstance("canvas_obj_99")?.id).toBe(c.id);
    expect(lib.findByInstance("nonexistent")).toBeUndefined();
  });

  it("update emits correct data", () => {
    const c = createComponent("Old", "button", {});
    lib.add(c);
    lib.update(c.id, { name: "New" });
    expect(lib.get(c.id)?.name).toBe("New");
  });

  it("delete removes component", () => {
    const c = createComponent("Del", "icon", {});
    lib.add(c);
    expect(lib.delete(c.id)).toBe(true);
    expect(lib.get(c.id)).toBeUndefined();
  });

  it("exportAll/importAll round-trip", () => {
    lib.importAll(DEFAULT_COMPONENTS);
    const exported = lib.exportAll();
    expect(exported.length).toBe(DEFAULT_COMPONENTS.length);
  });

  it("DEFAULT_COMPONENTS all have required fields", () => {
    DEFAULT_COMPONENTS.forEach(c => {
      expect(c.id).toBeTruthy();
      expect(c.name).toBeTruthy();
      expect(c.category).toBeTruthy();
    });
  });
});
