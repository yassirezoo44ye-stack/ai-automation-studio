import { afterEach, describe, expect, it, vi } from "vitest";
import { oauthStartUrl } from "./oauth";
afterEach(() => vi.unstubAllGlobals());
describe("canonical OAuth origin", () => {
  it("reports network failure without navigating to a fallback host", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(oauthStartUrl("google")).rejects.toThrow("تعذر الاتصال");
  });
  it.each(["google", "github", "microsoft"] as const)("starts %s directly on callback host", async provider => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ origin: "https://backend.example.test" }))));
    expect(await oauthStartUrl(provider)).toBe(`https://backend.example.test/api/auth/${provider}`);
  });
  it.each(["https://u:p@example.test", "javascript:alert(1)", "http://example.test", "https://example.test/other", "https://example.test/?next=x"])("rejects unsafe config %s", async origin => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ origin }))));
    await expect(oauthStartUrl("google")).rejects.toThrow();
  });
  it("does not start a flow when configuration request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(oauthStartUrl("google")).rejects.toThrow("تعذر بدء");
  });
});
