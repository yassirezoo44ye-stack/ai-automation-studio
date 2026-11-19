import { describe, expect, it } from "vitest";
import { buildPromptError, MAX_BUILD_PROMPT_CHARS, promptCharacterCount } from "./promptValidation";

describe("build prompt bounds", () => {
  it("counts Unicode code points like the backend", () => {
    const prompt = "🚀".repeat(MAX_BUILD_PROMPT_CHARS);
    expect(promptCharacterCount(prompt)).toBe(MAX_BUILD_PROMPT_CHARS);
    expect(buildPromptError(prompt)).toBeNull();
    expect(buildPromptError(prompt + "ع")).toBe("tooLong");
  });
  it("rejects blank prompts and includes surrounding whitespace in the bound", () => {
    expect(buildPromptError(" \n\t")).toBe("empty");
    expect(buildPromptError("ع".repeat(MAX_BUILD_PROMPT_CHARS) + " ")).toBe("tooLong");
  });
});
