/**
 * Design Token system tests.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { TokenRegistry } from "../core/tokens/TokenRegistry";
import { createColorToken, createSpacingToken } from "../core/tokens/DesignToken";
import { ALL_DEFAULT_TOKENS } from "../core/tokens/defaultTokens";

describe("TokenRegistry", () => {
  let registry: TokenRegistry;

  beforeEach(() => {
    registry = new TokenRegistry();
  });

  it("adds and retrieves a token", () => {
    const t = createColorToken("primary", "#4f46e5");
    registry.add(t);
    expect(registry.get(t.id)).toEqual(t);
  });

  it("lists all tokens", () => {
    registry.add(createColorToken("a", "#111"));
    registry.add(createColorToken("b", "#222"));
    expect(registry.all()).toHaveLength(2);
  });

  it("filters by category", () => {
    registry.add(createColorToken("primary", "#4f46e5"));
    registry.add(createSpacingToken("md", 16));
    expect(registry.colors()).toHaveLength(1);
    expect(registry.spacing()).toHaveLength(1);
  });

  it("updates a token value", () => {
    const t = createColorToken("brand", "#000000");
    registry.add(t);
    registry.update(t.id, { value: "#ffffff" });
    expect(registry.get(t.id)?.value).toBe("#ffffff");
  });

  it("deletes a token", () => {
    const t = createColorToken("temp", "#aabbcc");
    registry.add(t);
    expect(registry.delete(t.id)).toBe(true);
    expect(registry.get(t.id)).toBeUndefined();
  });

  it("delete returns false for unknown id", () => {
    expect(registry.delete("ghost_id")).toBe(false);
  });

  it("generates CSS variables", () => {
    registry.add(createColorToken("primary", "#4f46e5"));
    const css = registry.toCSSVariables();
    expect(css).toContain("--token-primary: #4f46e5");
  });

  it("bulk import and export round-trips", () => {
    const tokens = [createColorToken("x", "#ff0000"), createSpacingToken("lg", 24)];
    registry.importTokens(tokens);
    const exported = registry.exportTokens();
    expect(exported).toHaveLength(2);
  });

  it("DEFAULT tokens all have required fields", () => {
    ALL_DEFAULT_TOKENS.forEach(t => {
      expect(t.id).toBeTruthy();
      expect(t.name).toBeTruthy();
      expect(t.category).toBeTruthy();
      expect(t.value).toBeTruthy();
    });
  });
});
