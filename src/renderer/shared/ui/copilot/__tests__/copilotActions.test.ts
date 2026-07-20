import { describe, it, expect } from "vitest";
import { matchCopilotAction } from "../copilotActions";

describe("matchCopilotAction", () => {
  it("matches an explicit 'open X' phrase", () => {
    expect(matchCopilotAction("open billing")).toEqual({ label: "Open Billing", page: "billing" });
    expect(matchCopilotAction("go to settings")).toEqual({ label: "Open Settings", page: "settings" });
    expect(matchCopilotAction("take me to the marketplace")).toEqual({ label: "Open Marketplace", page: "marketplace" });
  });

  it("matches a short bare keyword without a verb", () => {
    expect(matchCopilotAction("billing")).toEqual({ label: "Open Billing", page: "billing" });
    expect(matchCopilotAction("teams")).toEqual({ label: "Open Teams", page: "teams" });
  });

  it("does not match a long sentence that merely mentions a keyword in passing", () => {
    expect(matchCopilotAction("why is the billing page so confusing to navigate")).toBeNull();
  });

  it("returns null for empty or unrelated input", () => {
    expect(matchCopilotAction("")).toBeNull();
    expect(matchCopilotAction("   ")).toBeNull();
    expect(matchCopilotAction("what's the weather like today")).toBeNull();
  });

  it("is case-insensitive", () => {
    expect(matchCopilotAction("OPEN BILLING")).toEqual({ label: "Open Billing", page: "billing" });
  });
});
