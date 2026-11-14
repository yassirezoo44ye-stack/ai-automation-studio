import { describe, it, expect, beforeEach } from "vitest";
import { clearAssistantHandoff, handOffToAssistant, peekAssistantHandoff } from "../assistantHandoff";

describe("assistant hand-off", () => {
  beforeEach(() => sessionStorage.clear());

  it("passes a trimmed question once", () => {
    handOffToAssistant("  Plan my week ");
    expect(peekAssistantHandoff()).toBe("Plan my week");
    clearAssistantHandoff();
    expect(peekAssistantHandoff()).toBe("");
  });

  it("ignores blank questions", () => {
    handOffToAssistant("   ");
    expect(peekAssistantHandoff()).toBe("");
  });
});
