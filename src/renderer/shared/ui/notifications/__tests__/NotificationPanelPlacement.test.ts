/**
 * The notification bell sits in the top bar, so its panel must open
 * downwards. It used to open upwards (bottom: 100%) — above the viewport —
 * which made the bell look dead in production while DOM-level tests passed
 * (jsdom applies no CSS). This guards the stylesheet itself.
 */
import { describe, it, expect } from "vitest";
import css from "../../../../design-system.css?raw";

function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, `${selector} rule exists`).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start));
}

describe("notification panel placement", () => {
  it("drops below the bell instead of opening above the top bar", () => {
    const panel = rule(".g-notif-panel");
    expect(panel).toMatch(/top:\s*calc\(100% \+ 8px\)/);
    expect(panel).not.toMatch(/bottom:\s*calc\(100%/);
  });
});
