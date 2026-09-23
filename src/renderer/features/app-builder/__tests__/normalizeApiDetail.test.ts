import { describe, it, expect } from "vitest";
import { normalizeApiDetail } from "../services/builderService";

describe("normalizeApiDetail — streamBuild [object Object] regression suite", () => {
  const FALLBACK = "HTTP 422";

  // ── FastAPI validation error array ─────────────────────────────────────────

  it("single validation error → extracts msg", () => {
    const detail = [{ loc: ["body", "name"], msg: "ensure this value has at least 2 characters", type: "value_error.any_str.min_length" }];
    expect(normalizeApiDetail(detail, FALLBACK)).toBe("ensure this value has at least 2 characters");
  });

  it("multiple validation errors → joins msgs with '; '", () => {
    const detail = [
      { loc: ["body", "name"], msg: "field required" },
      { loc: ["body", "description"], msg: "ensure this value has at most 500 characters" },
    ];
    expect(normalizeApiDetail(detail, FALLBACK)).toBe(
      "field required; ensure this value has at most 500 characters",
    );
  });

  it("array with no 'msg' keys → falls back to fallback", () => {
    const detail = [{ code: "some_code" }, { reason: "unknown" }];
    expect(normalizeApiDetail(detail, FALLBACK)).toBe(FALLBACK);
  });

  it("mixed array: some have 'msg', some don't → only extracts msgs", () => {
    const detail = [{ msg: "name too short" }, { code: "no_msg_here" }, { msg: "description too long" }];
    expect(normalizeApiDetail(detail, FALLBACK)).toBe("name too short; description too long");
  });

  it("empty array → falls back to fallback", () => {
    expect(normalizeApiDetail([], FALLBACK)).toBe(FALLBACK);
  });

  it("array of empty-msg objects → falls back to fallback", () => {
    expect(normalizeApiDetail([{ msg: "" }, { msg: "   " }], FALLBACK)).toBe(FALLBACK);
  });

  // ── Plain string ────────────────────────────────────────────────────────────

  it("plain string detail → returned as-is", () => {
    expect(normalizeApiDetail("Project already exists", FALLBACK)).toBe("Project already exists");
  });

  it("plain string with whitespace → returned as-is", () => {
    expect(normalizeApiDetail("  Not found  ", FALLBACK)).toBe("  Not found  ");
  });

  it("empty string → falls back to fallback", () => {
    expect(normalizeApiDetail("", FALLBACK)).toBe(FALLBACK);
  });

  it("whitespace-only string → falls back to fallback", () => {
    expect(normalizeApiDetail("   ", FALLBACK)).toBe(FALLBACK);
  });

  // ── Object / unexpected shapes ─────────────────────────────────────────────

  it("plain object (unexpected shape) → falls back to fallback", () => {
    expect(normalizeApiDetail({ msg: "unexpected" }, FALLBACK)).toBe(FALLBACK);
  });

  it("number → falls back to fallback", () => {
    expect(normalizeApiDetail(42, FALLBACK)).toBe(FALLBACK);
  });

  it("null → falls back to fallback", () => {
    expect(normalizeApiDetail(null, FALLBACK)).toBe(FALLBACK);
  });

  it("undefined → falls back to fallback", () => {
    expect(normalizeApiDetail(undefined, FALLBACK)).toBe(FALLBACK);
  });

  it("boolean → falls back to fallback", () => {
    expect(normalizeApiDetail(true, FALLBACK)).toBe(FALLBACK);
  });

  // ── Invariant: result never contains [object Object] ──────────────────────

  it("object array → result never contains '[object Object]'", () => {
    const detail = [{ loc: ["body"], msg: "some error" }, { unexpected: true }];
    expect(normalizeApiDetail(detail, FALLBACK)).not.toContain("[object Object]");
  });

  it("plain object → result never contains '[object Object]'", () => {
    expect(normalizeApiDetail({ detail: "nested" }, FALLBACK)).not.toContain("[object Object]");
  });

  it("nested array of arrays → result never contains '[object Object]'", () => {
    expect(normalizeApiDetail([[1, 2], [3, 4]], FALLBACK)).not.toContain("[object Object]");
  });
});
