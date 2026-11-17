/// <reference types="node" />
// @vitest-environment node
/**
 * WCAG 2.1 AA text contrast for the design tokens (a11y audit M2, 2026-11-17).
 *
 * The audit found 606 of 642 axe violations came from two translucent text
 * tokens (--t4 at 65%, --t5 at 35% opacity) and from white text on the
 * dark theme's #FF1744 buttons. This guards the tokens themselves: every
 * text token must reach 4.5:1 on every background surface of its theme,
 * and --on-accent must reach 4.5:1 on --accent-fill.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../design-system.css", import.meta.url), "utf8");

function themeBlock(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`theme block not found: ${selector}`);
  const body = css.slice(start, css.indexOf("\n}", start));
  const vars: Record<string, string> = {};
  for (const m of body.matchAll(/--([\w-]+):\s*([^;]+);/g)) vars[m[1]] = m[2].trim();
  return vars;
}

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map(c => c + c).join("") : h;
  const [r, g, b] = [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const THEMES = [":root", '[data-theme="dark"]', '[data-theme="high-contrast"]'];
const TEXT = ["t1", "t2", "t3", "t4", "t5"];
const SURFACES = ["bg-base", "bg-surface", "bg-elevated"];

describe.each(THEMES)("text contrast tokens in %s", selector => {
  const vars = themeBlock(selector);

  it.each(TEXT)("--%s is a solid colour with >= 4.5:1 on every surface", token => {
    const fg = vars[token];
    expect(fg, `--${token} must be a solid hex colour, not translucent`).toMatch(/^#[0-9a-fA-F]{3,6}$/);
    for (const surface of SURFACES) {
      expect(contrast(fg, vars[surface]), `--${token} on --${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("--on-accent has >= 4.5:1 on --accent-fill", () => {
    expect(contrast(vars["on-accent"], vars["accent-fill"])).toBeGreaterThanOrEqual(4.5);
  });
});
