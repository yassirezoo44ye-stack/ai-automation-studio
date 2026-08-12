import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as contentApi from "../content";
import { clearTokenState, setTokenState } from "../tokenStore";

function mockFetchOnce(body: unknown, status = 200) {
  // The Fetch spec forbids a body on 204/304 responses — the Response
  // constructor throws if you try. apiFetch() never reads the body for a
  // 204 anyway (see client.ts), so match real server behavior here.
  const isEmptyStatus = status === 204 || status === 304;
  const response = new Response(isEmptyStatus ? null : JSON.stringify(body), {
    status,
    headers: isEmptyStatus ? undefined : { "Content-Type": "application/json" },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response),
  );
}

describe("content API client", () => {
  beforeEach(() => {
    setTokenState({ accessToken: "test-token" });
  });

  afterEach(() => {
    clearTokenState();
    vi.unstubAllGlobals();
  });

  it("createStrategy POSTs to the org-scoped strategies endpoint with the payload", async () => {
    mockFetchOnce({ id: "s1", name: "My Strategy" }, 201);
    await contentApi.createStrategy("org-1", { name: "My Strategy" });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/organizations/org-1/content/strategies");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ name: "My Strategy" });
  });

  it("createStrategy sends the bearer token from token state", async () => {
    mockFetchOnce({ id: "s1" }, 201);
    await contentApi.createStrategy("org-1", { name: "X" });

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer test-token");
  });

  it("listItems builds a query string only for provided filters", async () => {
    mockFetchOnce([]);
    await contentApi.listItems("org-1", { platform: "linkedin" });

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/organizations/org-1/content/items?platform=linkedin");
  });

  it("listItems omits the query string when no filters are given", async () => {
    mockFetchOnce([]);
    await contentApi.listItems("org-1");

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url.endsWith("/content/items")).toBe(true);
  });

  it("generateIdeas posts to the generate/ideas endpoint", async () => {
    mockFetchOnce({ id: "g1", status: "succeeded" });
    await contentApi.generateIdeas("org-1", { strategy_id: "strat-1", count: 3 });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/content/generate/ideas");
    expect(JSON.parse(init.body as string)).toEqual({ strategy_id: "strat-1", count: 3 });
  });

  it("deleteItem issues a DELETE request", async () => {
    mockFetchOnce(null, 204);
    await contentApi.deleteItem("org-1", "item-1");

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/content/items/item-1");
    expect(init.method).toBe("DELETE");
  });

  it("propagates a 4xx/5xx response as an ApiError with the server detail message", async () => {
    mockFetchOnce({ detail: "Content strategy not found" }, 404);
    await expect(contentApi.getStrategy("org-1", "missing")).rejects.toThrow("Content strategy not found");
  });
});
