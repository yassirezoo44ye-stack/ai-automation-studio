import { describe, it, expect } from "vitest";
import { all, required, email, minLength, maxLength, pattern, matchesField, passwordStrength } from "../validators";

describe("validators", () => {
  it("required rejects empty/whitespace/null/undefined, accepts anything else", () => {
    const v = required();
    expect(v("", {})).toBeDefined();
    expect(v("   ", {})).toBeDefined();
    expect(v(null, {})).toBeDefined();
    expect(v(undefined, {})).toBeDefined();
    expect(v([], {})).toBeDefined();
    expect(v("x", {})).toBeUndefined();
    expect(v(0, {})).toBeUndefined(); // falsy-but-valid: zero is a real value, not "empty"
    expect(v(false, {})).toBeUndefined();
  });

  it("email accepts empty (defers to required) and valid addresses, rejects malformed ones", () => {
    const v = email();
    expect(v("", {})).toBeUndefined();
    expect(v("a@b.com", {})).toBeUndefined();
    expect(v("not-an-email", {})).toBeDefined();
    expect(v("a@b", {})).toBeDefined();
  });

  it("minLength/maxLength bound string length, ignoring empty strings", () => {
    expect(minLength(8)("short", {})).toBeDefined();
    expect(minLength(8)("longenough", {})).toBeUndefined();
    expect(minLength(8)("", {})).toBeUndefined();
    expect(maxLength(5)("toolong", {})).toBeDefined();
    expect(maxLength(5)("ok", {})).toBeUndefined();
  });

  it("pattern matches an arbitrary regex", () => {
    const v = pattern(/^\d+$/, "digits only");
    expect(v("123", {})).toBeUndefined();
    expect(v("12a", {})).toBe("digits only");
  });

  it("matchesField compares against a sibling value in the full values object", () => {
    const v = matchesField("password");
    expect(v("secret", { password: "secret" })).toBeUndefined();
    expect(v("nope", { password: "secret" })).toBeDefined();
  });

  it("passwordStrength requires at least one letter and one digit", () => {
    const v = passwordStrength();
    expect(v("alllettersnoNum", {})).toBeDefined();
    expect(v("12345678", {})).toBeDefined();
    expect(v("abc123", {})).toBeUndefined();
  });

  it("all() runs validators in order and stops at the first failure", () => {
    const calls: string[] = [];
    const first = () => { calls.push("first"); return "first failed"; };
    const second = () => { calls.push("second"); return "second failed"; };
    const combined = all(first, second);
    expect(combined("x", {})).toBe("first failed");
    expect(calls).toEqual(["first"]); // second never ran
  });
});
