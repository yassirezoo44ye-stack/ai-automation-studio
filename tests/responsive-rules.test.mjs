/**
 * FE-03 guards. jsdom does no layout, so these pin the CSS rules whose
 * absence was measured in a real browser (scripts/ui-runtime-audit.mjs):
 * on a 360px phone the Leads page grew to 595px and was cut off, Settings
 * left ~130px for its content, page headers / tab bars ran off-screen, and
 * the Copilot button covered the chat's Send button.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = path => readFileSync(join(process.cwd(), "src/renderer", path), "utf8").replace(/\s+/g, " ");

describe("responsive layout rules", () => {
  const ds = read("design-system.css");

  it("page roots fill the page column instead of sizing to their content", () => {
    expect(ds).toContain(".page-enter > * { width: 100%; min-width: 0; }");
  });

  it("phones: headers wrap and tab bars scroll", () => {
    expect(ds).toMatch(/@media \(max-width: 640px\) \{ \.page-enter > header \{ flex-wrap: wrap;/);
    expect(ds).toContain('.page-enter [role="tablist"] { overflow-x: auto;');
  });

  it("phones: settings nav stacks above the content", () => {
    expect(ds).toMatch(/@media \(max-width: 760px\) \{\s*\.flow-settings-layout \{ flex-direction: column; \}/);
  });

  it("chat Send keeps clear of the floating Copilot button", () => {
    expect(read("features/ai/chat.css")).toMatch(/\.chat-composer-wrap \{[^}]*padding-inline-end: 64px;/);
  });
});
