import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, authH } from "../api";

/**
 * Covers the auth-token-lifecycle fix: apiFetch() now attempts exactly one
 * silent refresh-and-retry when the backend flags a 401 as an expired JWT
 * (`{"error": "token_expired"}`, app/factory.py's api_auth_middleware) —
 * previously every 401 (expired, invalid, or missing) just propagated to
 * the caller, with a 13-minute background timer as the only renewal path.
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  delete (window as unknown as Record<string, unknown>).__axon_access_token;
  delete (window as unknown as Record<string, unknown>).__axon_refresh_fn;
  delete (window as unknown as Record<string, unknown>).__axon_org_id;
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch — 401 token_expired refresh-and-retry", () => {
  it("retries once with the fresh token when the backend flags token_expired and refresh succeeds", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Token expired", error: "token_expired" }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    (window as unknown as Record<string, unknown>).__axon_access_token = "stale-jwt";
    (window as unknown as Record<string, () => Promise<{ token: string | null }>>).__axon_refresh_fn =
      vi.fn(async () => {
        (window as unknown as Record<string, string>).__axon_access_token = "fresh-jwt";
        return { token: "fresh-jwt" };
      });

    const res = await apiFetch("/api/projects");

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondCallHeaders = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(secondCallHeaders["Authorization"]).toBe("Bearer fresh-jwt");
  });

  it("does not retry and returns the original 401 when refresh itself fails", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "Token expired", error: "token_expired" }));

    (window as unknown as Record<string, () => Promise<{ token: string | null }>>).__axon_refresh_fn =
      vi.fn(async () => ({ token: null }));

    const res = await apiFetch("/api/projects");

    expect(res.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1); // no retry attempted
  });

  it("does not attempt a refresh for a generic 401 (missing/invalid credentials, not expiry)", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "Subscription required" }));
    const refreshFn = vi.fn();
    (window as unknown as Record<string, unknown>).__axon_refresh_fn = refreshFn;

    const res = await apiFetch("/api/projects");

    expect(res.status).toBe(401);
    expect(refreshFn).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never attempts a refresh for /api/auth/* calls themselves (avoids a refresh-triggered-by-refresh loop)", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "Token expired", error: "token_expired" }));
    const refreshFn = vi.fn();
    (window as unknown as Record<string, unknown>).__axon_refresh_fn = refreshFn;

    const res = await apiFetch("/api/auth/me");

    expect(res.status).toBe(401);
    expect(refreshFn).not.toHaveBeenCalled();
  });

  it("does not loop more than once even if the retried request is also a 401", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Token expired", error: "token_expired" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Token expired", error: "token_expired" }));
    (window as unknown as Record<string, () => Promise<{ token: string | null }>>).__axon_refresh_fn =
      vi.fn(async () => ({ token: "fresh-jwt" }));

    const res = await apiFetch("/api/projects");

    expect(res.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2); // original + exactly one retry, no further recursion
  });

  it("does not blow up when no refresh function is registered yet (e.g. before AuthProvider mounts)", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "Token expired", error: "token_expired" }));

    const res = await apiFetch("/api/projects");

    expect(res.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("authH — always sends both credential headers when available", () => {
  it("includes X-Sub-Token, Authorization, and X-Organization-Id when all three are set", () => {
    localStorage.setItem("sub_token", "sub-tok");
    (window as unknown as Record<string, string>).__axon_access_token = "jwt-tok";
    (window as unknown as Record<string, string>).__axon_org_id = "org-1";

    const headers = authH();

    expect(headers["X-Sub-Token"]).toBe("sub-tok");
    expect(headers["Authorization"]).toBe("Bearer jwt-tok");
    expect(headers["X-Organization-Id"]).toBe("org-1");
  });
});
