import { StrictMode } from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AuthProvider, useAuth } from "../AuthContext";

/**
 * AuthContext token-lifecycle regression coverage.
 *
 * Real fetch Response objects are used for every mock (not hand-rolled
 * `{ ok, json() }` stand-ins) so parseJSON's actual content-type/body
 * handling runs for real, same principle as the backend's real-Postgres
 * test suite: exercise the real code path, not a shortcut around it.
 */

const REFRESH_KEY = "axon_refresh_token";
const SUB_TOKEN_KEY = "sub_token";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function emptyResponse(status: number): Response {
  return new Response("", { status });
}

/** Renders useAuth()'s state as text so assertions can read it via screen. */
function Probe() {
  const { user, accessToken, loading, bootstrapError, logout } = useAuth();
  return (
    <div>
      <div data-testid="loading">{String(loading)}</div>
      <div data-testid="user">{user ? user.email : "null"}</div>
      <div data-testid="accessToken">{accessToken ?? "null"}</div>
      <div data-testid="bootstrapError">{bootstrapError ?? "null"}</div>
      <button onClick={() => void logout()}>logout</button>
    </div>
  );
}

function renderAuth(strict = false) {
  const tree = (
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

const ME_USER = {
  id: "u1", email: "user@example.com", name: "User",
  email_verified: true, avatar_url: null, created_at: null,
};

describe("AuthContext — token lifecycle", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
    (window as unknown as Record<string, unknown>).__axon_access_token = null;
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("restores the session from a stored refresh token on mount (restart persistence) and populates the access token", async () => {
    localStorage.setItem(REFRESH_KEY, "stored-refresh-token");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/api/auth/refresh")) {
        return Promise.resolve(jsonResponse(200, {
          access_token: "new-access-token", refresh_token: "rotated-refresh-token",
        }));
      }
      if (String(url).includes("/api/auth/me")) {
        return Promise.resolve(jsonResponse(200, ME_USER));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderAuth();

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("accessToken")).toHaveTextContent("new-access-token");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");

    // The refresh token in storage is the rotated one, and the module-level
    // global token (read by non-React parts of the app) is populated too —
    // "access token restored" means both the React state and this global.
    expect(localStorage.getItem(REFRESH_KEY)).toBe("rotated-refresh-token");
    expect((window as unknown as Record<string, unknown>).__axon_access_token).toBe("new-access-token");
  });

  it("a 401 from the refresh endpoint clears session state, including the sub_token", async () => {
    // There is no separate "any 401 anywhere triggers a refresh" interceptor
    // in this codebase — refresh is time-scheduled + bootstrap-driven. The
    // actual 401-handling code path lives inside the refresh call itself:
    // this test exercises that real path, not an invented one.
    localStorage.setItem(REFRESH_KEY, "expired-refresh-token");
    localStorage.setItem(SUB_TOKEN_KEY, "stale-sub-token");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/api/auth/refresh")) {
        return Promise.resolve(emptyResponse(401));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderAuth();

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("accessToken")).toHaveTextContent("null");
    expect(screen.getByTestId("user")).toHaveTextContent("null");
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
    expect(localStorage.getItem(SUB_TOKEN_KEY)).toBeNull();
  });

  it("concurrent refresh calls (StrictMode double-invoking the bootstrap effect) share one in-flight request", async () => {
    localStorage.setItem(REFRESH_KEY, "stored-refresh-token");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    let refreshCallCount = 0;
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/api/auth/refresh")) {
        refreshCallCount += 1;
        return Promise.resolve(jsonResponse(200, {
          access_token: "new-access-token", refresh_token: "rotated-refresh-token",
        }));
      }
      if (String(url).includes("/api/auth/me")) {
        return Promise.resolve(jsonResponse(200, ME_USER));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    // StrictMode intentionally mounts -> runs effects -> cleans up -> runs
    // effects again for the SAME component instance -- the exact scenario
    // refreshInFlightRef exists to dedupe (see the code's own comment).
    renderAuth(true);

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(refreshCallCount).toBe(1);
  });

  it("logout clears local credentials, including the sub_token", async () => {
    localStorage.setItem(REFRESH_KEY, "stored-refresh-token");
    localStorage.setItem(SUB_TOKEN_KEY, "active-sub-token");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes("/api/auth/refresh")) {
        return Promise.resolve(jsonResponse(200, {
          access_token: "new-access-token", refresh_token: "rotated-refresh-token",
        }));
      }
      if (u.includes("/api/auth/me")) {
        return Promise.resolve(jsonResponse(200, ME_USER));
      }
      if (u.includes("/api/auth/logout") && init?.method === "POST") {
        return Promise.resolve(jsonResponse(200, { message: "Logged out" }));
      }
      throw new Error(`unexpected fetch ${u}`);
    });

    renderAuth();
    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("accessToken")).not.toHaveTextContent("null");

    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    await waitFor(() => expect(screen.getByTestId("accessToken")).toHaveTextContent("null"));
    expect(screen.getByTestId("user")).toHaveTextContent("null");
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
    expect(localStorage.getItem(SUB_TOKEN_KEY)).toBeNull();
    expect((window as unknown as Record<string, unknown>).__axon_access_token).toBeNull();
  });

  it("completes the OAuth callback: exchanges the one-time code, stores tokens, fetches the user, and cleans the URL", async () => {
    window.history.pushState({}, "", "/oauth-callback?code=one-time-exchange-code");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes("/api/auth/oauth-exchange") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { code: string };
        expect(body.code).toBe("one-time-exchange-code");
        return Promise.resolve(jsonResponse(200, {
          access_token: "oauth-access-token",
          refresh_token: "oauth-refresh-token",
          sub_token: "oauth-sub-token",
        }));
      }
      if (u.includes("/api/auth/me")) {
        return Promise.resolve(jsonResponse(200, ME_USER));
      }
      throw new Error(`unexpected fetch ${u}`);
    });

    renderAuth();

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("accessToken")).toHaveTextContent("oauth-access-token");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");
    expect(localStorage.getItem(REFRESH_KEY)).toBe("oauth-refresh-token");
    expect(localStorage.getItem(SUB_TOKEN_KEY)).toBe("oauth-sub-token");
    // The one-time code must not be left sitting in the URL (browser
    // history, refresh, share-the-link) after it's been redeemed.
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("");
  });
});
