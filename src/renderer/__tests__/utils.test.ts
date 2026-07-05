import { describe, it, expect } from "vitest";
import { relTime } from "../shared/utils/time";
import { fileIcon } from "../shared/utils/files";

describe("relTime", () => {
  it("shows 'just now' for very recent timestamps", () => {
    const now = new Date().toISOString();
    expect(relTime(now)).toMatch(/just now|second/i);
  });

  it("handles undefined gracefully", () => {
    expect(() => relTime(undefined as unknown as string)).not.toThrow();
  });
});

describe("fileIcon", () => {
  it("returns icon for known extensions", () => {
    expect(fileIcon("app.tsx")).toBeTruthy();
    expect(fileIcon("server.py")).toBeTruthy();
    expect(fileIcon("styles.css")).toBeTruthy();
  });

  it("returns default icon for unknown extensions", () => {
    const result = fileIcon("unknown.xyz");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });
});
