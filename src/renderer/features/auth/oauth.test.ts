import { afterEach, describe, expect, it, vi } from "vitest";
import { oauthProviders, oauthStartUrl } from "./oauth";
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
describe("configured providers", () => {
  it("lists only known providers the server reports", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ origin: "https://b.example.test", providers: ["google", "evil"] }))));
    expect(await oauthProviders()).toEqual(["google"]);
  });
  it("is unknown for an older backend or a failed request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ origin: "https://b.example.test" }))));
    expect(await oauthProviders()).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect(await oauthProviders()).toBeNull();
  });
  it("refuses to start a provider the server has not configured", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response(JSON.stringify({ origin: "https://b.example.test", providers: ["google"] }))));
    await expect(oauthStartUrl("github")).rejects.toThrow("غير متاحة");
    expect(await oauthStartUrl("google")).toBe("https://b.example.test/api/auth/google");
  });
});
