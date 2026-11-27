import { describe, it, expect } from "vitest";
import { extractNavSuggestions, suggestPagesForPrompt, navLabelKey } from "../shared/utils/assistantNav";

describe("extractNavSuggestions", () => {
  it("strips markers and keeps known pages in order, max two", () => {
    const r = extractNavSuggestions("Sure.\n\n[[open:settings]]\n[[open:billing]]\n[[open:leads]]");
    expect(r.text).toBe("Sure.");
    expect(r.pages).toEqual(["settings", "billing"]);
  });
  it("ignores unknown ids and duplicates", () => {
    const r = extractNavSuggestions("Hi [[open:admin-panel]] [[open:leads]] [[OPEN:leads]]");
    expect(r.pages).toEqual(["leads"]);
    expect(r.text).toBe("Hi");
  });
  it("hides a marker that is still streaming in", () => {
    expect(extractNavSuggestions("Go here:\n[[op").text).toBe("Go here:");
    expect(extractNavSuggestions("Go here:\n[[open:sett").text).toBe("Go here:");
  });
  it("leaves ordinary text untouched", () => {
    expect(extractNavSuggestions("Use [link](https://x.y) and [1]").text).toBe("Use [link](https://x.y) and [1]");
  });
});

describe("suggestPagesForPrompt", () => {
  it("needs an explicit open verb, in Arabic or English", () => {
    expect(suggestPagesForPrompt("افتح الإعدادات")).toEqual(["settings"]);
    expect(suggestPagesForPrompt("خذني إلى العملاء المحتملين")).toEqual(["leads"]);
    expect(suggestPagesForPrompt("go to billing")).toEqual(["billing"]);
    expect(suggestPagesForPrompt("why are my settings confusing")).toEqual([]);
  });
});

it("maps pages to sidebar labels", () => {
  expect(navLabelKey("app-builder")).toBe("common:sidebar.nav.appBuilder");
  expect(navLabelKey("settings")).toBe("common:sidebar.nav.settings");
});
