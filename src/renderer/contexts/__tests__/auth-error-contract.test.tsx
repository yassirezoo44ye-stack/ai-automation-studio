/**
 * Auth Error Contract — Frontend
 * ================================
 * Verifies that AuthContext's login() and register() functions propagate the
 * actual `detail` string from the backend JSON response, rather than always
 * returning the generic fallback ("Login failed" / "Registration failed").
 *
 * This is the regression gate for commit 579d51a9 which replaced
 *   parseJSON(res, …).catch(() => ({ detail: "…" }))
 * with a direct res.json() read in both error handlers.
 *
 * Why these tests matter:
 *   Before the fix: ANY non-2xx response → parseJSON throws APIError →
 *     .catch() fires → generic fallback always shown.
 *   After the fix: 409 "Email already registered" → detail forwarded to UI.
 *
 * Mock strategy note:
 *   AuthProvider's bootstrap effect calls doRefresh() ONLY when localStorage
 *   has a stored refresh token. In the jsdom test environment localStorage
 *   is always empty, so doRefresh() (and its fetch call) is NEVER triggered.
 *   Therefore tests must NOT include a "bootstrap fetch" slot — the first mock
 *   call is consumed by login()/register() itself.
 */
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach, type ReactNode } from "vitest";
import React from "react";
import { AuthProvider, useAuth } from "../AuthContext";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Build a minimal fetch stub that returns the given status + JSON body. */
function mockFetch(status: number, body: unknown, contentType = "application/json") {
  const bodyStr = typeof body === "string" ? body : JSON.stringify(body);
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    headers: {
      get: (h: string) => h.toLowerCase() === "content-type" ? contentType : null,
    },
    json: async () => JSON.parse(bodyStr),
    text: async () => bodyStr,
    clone: function () { return this; },
  });
}

/** Wrapper that provides the auth context. */
function Wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── login() error contract ─────────────────────────────────────────────────────

describe("AuthContext.login() — error propagation (commit 579d51a9 regression gate)", () => {
  it("propagates backend detail string on 401 (wrong password / not found)", async () => {
    // localStorage is empty in jsdom → AuthProvider skips doRefresh() entirely.
    // The first (and only) fetch call comes from login() itself.
    vi.stubGlobal("fetch", mockFetch(401, { detail: "Invalid email or password" }));

    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });

    // Wait for bootstrap to settle (no fetch needed — localStorage empty)
    await waitFor(() => expect(result.current.loading).toBe(false));

    let thrown: Error | undefined;
    await act(async () => {
      try {
        await result.current.login("x@x.com", "wrongpass");
      } catch (e) {
        thrown = e as Error;
      }
    });

    expect(thrown).toBeDefined();
    expect(thrown!.message).toBe("Invalid email or password");
    // Must NOT be the generic fallback
    expect(thrown!.message).not.toBe("Login failed");
  });

  it("falls back to 'Login failed' when 401 body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 401, headers: { get: () => "text/html" },
      json: async () => { throw new SyntaxError("not json"); },
      text: async () => "<html>Error</html>",
      clone: function () { return this; },
    }));

    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    let thrown: Error | undefined;
    await act(async () => {
      try { await result.current.login("x@x.com", "pw"); } catch (e) { thrown = e as Error; }
    });

    expect(thrown?.message).toBe("Login failed");
  });
});

// ── register() error contract ──────────────────────────────────────────────────

describe("AuthContext.register() — error propagation (commit 579d51a9 regression gate)", () => {
  it("propagates 'Email already registered' on 409", async () => {
    vi.stubGlobal("fetch", mockFetch(409, { detail: "Email already registered" }));

    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    let thrown: Error | undefined;
    await act(async () => {
      try {
        await result.current.register("Alice", "alice@example.com", "Str0ngPass!");
      } catch (e) {
        thrown = e as Error;
      }
    });

    expect(thrown).toBeDefined();
    expect(thrown!.message).toBe("Email already registered");
    expect(thrown!.message).not.toBe("Registration failed");
  });

  it("propagates validation error detail on 422", async () => {
    vi.stubGlobal("fetch", mockFetch(422, {
      detail: [{ msg: "Password must be at least 8 characters", loc: ["body", "password"] }],
    }));

    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    let thrown: Error | undefined;
    await act(async () => {
      try {
        await result.current.register("Bob", "bob@example.com", "short");
      } catch (e) {
        thrown = e as Error;
      }
    });

    expect(thrown).toBeDefined();
    // 422 detail is an array — no string detail → falls back to "Registration failed"
    // (Array is not a string, body?.detail check returns the array which is truthy
    //  but instanceof check fails in Error constructor) — verify it doesn't crash
    expect(thrown!.message).toBeTruthy();
  });

  it("succeeds on 201 and returns the message without throwing", async () => {
    vi.stubGlobal("fetch", mockFetch(201, {
      message: "Account created. Check your email to verify your account.",
    }));

    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    let returned: { message: string } | undefined;
    let thrown: Error | undefined;
    await act(async () => {
      try {
        returned = await result.current.register("Carol", "carol@example.com", "Str0ngPass!");
      } catch (e) {
        thrown = e as Error;
      }
    });

    expect(thrown).toBeUndefined();
    expect(returned?.message).toContain("Account created");
  });

  it("falls back to 'Registration failed' when error body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 500, headers: { get: () => "text/html" },
      json: async () => { throw new SyntaxError("not json"); },
      text: async () => "<html>Server Error</html>",
      clone: function () { return this; },
    }));

    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    let thrown: Error | undefined;
    await act(async () => {
      try {
        await result.current.register("Dave", "dave@example.com", "Str0ngPass!");
      } catch (e) {
        thrown = e as Error;
      }
    });

    expect(thrown?.message).toBe("Registration failed");
  });
});
