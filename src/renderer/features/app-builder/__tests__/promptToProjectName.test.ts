import { describe, it, expect } from "vitest";
import { promptToProjectName } from "../services/builderService";

describe("promptToProjectName — 422 regression suite", () => {
  // ── Regression cases: single-char names that formerly caused HTTP 422 ──

  it("numbered list prompt: '1. Build a CRM' → 'New App' (was '1')", () => {
    expect(promptToProjectName("1. Build a CRM with users and roles")).toBe("New App");
  });

  it("numbered list prompt: '2. Add authentication' → 'New App' (was '2')", () => {
    expect(promptToProjectName("2. Add authentication to the app")).toBe("New App");
  });

  it("XML processing instruction: '<?xml version...' → 'New App' (was '<')", () => {
    expect(promptToProjectName('<?xml version="1.0" encoding="UTF-8"?>\n<root/>')).toBe("New App");
  });

  it("PHP-style open tag: '<?php ...' → 'New App' (was '<')", () => {
    expect(promptToProjectName("<?php\necho 'hello';\n?>")).toBe("New App");
  });

  it("single-character prompt → 'New App'", () => {
    expect(promptToProjectName("A")).toBe("New App");
  });

  it("single character before newline → 'New App'", () => {
    expect(promptToProjectName("A\nBuild a todo list app")).toBe("New App");
  });

  it("leading '!' (empty split head) → 'New App'", () => {
    expect(promptToProjectName("!Build this app")).toBe("New App");
  });

  it("leading '.' (empty split head) → 'New App'", () => {
    expect(promptToProjectName(".Something weird")).toBe("New App");
  });

  it("empty string → 'New App'", () => {
    expect(promptToProjectName("")).toBe("New App");
  });

  it("whitespace-only prompt → 'New App'", () => {
    expect(promptToProjectName("   ")).toBe("New App");
  });

  it("single char followed by dot: 'A. Build X' → 'New App' (was 'A')", () => {
    expect(promptToProjectName("A. Build a dashboard")).toBe("New App");
  });

  // ── Normal prompts: must NOT regress to 'New App' ──

  it("'Build a CRM...' → valid name (not 'New App')", () => {
    const result = promptToProjectName("Build a CRM with contact management");
    expect(result).not.toBe("New App");
    expect(result.length).toBeGreaterThanOrEqual(2);
    expect(result).toBe("CRM with contact management");
  });

  it("'Create a todo app' → valid name (not 'New App')", () => {
    const result = promptToProjectName("Create a todo app");
    expect(result).not.toBe("New App");
    expect(result.length).toBeGreaterThanOrEqual(2);
  });

  it("plain HTML prompt starting with '<!DOCTYPE' → valid name", () => {
    const result = promptToProjectName("<!DOCTYPE html>\n<html><body>Make me a landing page</body></html>");
    expect(result.length).toBeGreaterThanOrEqual(2);
  });

  it("'Make the landing page' → valid name", () => {
    const result = promptToProjectName("Make the landing page responsive");
    expect(result).not.toBe("New App");
    expect(result.length).toBeGreaterThanOrEqual(2);
  });

  it("SQL prompt starting with CREATE TABLE → valid name (not 'New App')", () => {
    // "CREATE TABLE users..." → regex strips "CREATE " (create + no a/an/the)
    // → "TABLE users..." → split on first \n/./!/?
    const result = promptToProjectName("CREATE TABLE users (\n  id SERIAL PRIMARY KEY\n);");
    expect(result.length).toBeGreaterThanOrEqual(2);
    expect(result).not.toBe("New App");
  });

  it("result is always capitalised when valid", () => {
    const result = promptToProjectName("build an ecommerce store");
    expect(result[0]).toBe(result[0].toUpperCase());
  });

  it("result never exceeds 45 chars (slice guard)", () => {
    const long = "Build a very long application name that goes way beyond the limit that we have set for project names";
    expect(promptToProjectName(long).length).toBeLessThanOrEqual(45);
  });
});
