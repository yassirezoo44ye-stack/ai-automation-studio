import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AuthProvider, useAuth } from "../AuthContext";

/**
 * Covers the auth-token-lifecycle audit's required scenarios: login, app
 * restart (bootstrap hydration from a stored refresh token), token refresh,
 * expired token / dead session handling, and logout cleanup — including the
 * fix for logout previously leaving a stale sub_token (and OrgContext's
 * persisted org selection) behind in localStorage.
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function Consumer() {
  const { user, loading, login, logout } = useAuth();
  return (
    <div>
      <div data-testid="loading">{String(loading)}</div>
      <div data-testid="user">{user?.email ?? ""}</div>
      <button onClick={() => login("user@example.com", "pw", true)}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

const fakeUser = {
  id: "u1", email: "user@example.com", name: "User",
  email_verified: true, avatar_url: null, created_at: null,
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  localStorage.clear();
  delete (window as unknown as Record<string, unknown>).__axon_access_token;
  delete (window as unknown as Record<string, unknown>).__axon_refresh_fn;
  delete (window as unknown as Record<string, unknown>).__axon_org_id;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuthProvider — bootstrap (app restart)", () => {
  it("with no stored refresh token, finishes loading with no user (fresh install / logged-out state)", async () => {
    render(<AuthProvider><Consumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("user")).toHaveTextContent("");
  });

  it("with a stored refresh token, silently restores the session (refresh -> /me) without a manual login", async () => {
    localStorage.setItem("axon_refresh_token", "stored-refresh-tok");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "new-jwt", refresh_token: "rotated-refresh" }))
      .mockResolvedValueOnce(jsonResponse(200, fakeUser));

    render(<AuthProvider><Consumer /></AuthProvider>);

    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("user@example.com"));
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
    expect(localStorage.getItem("axon_refresh_token")).toBe("rotated-refresh"); // rotated, persisted
    expect((window as unknown as Record<string, string>).__axon_access_token).toBe("new-jwt");
  });

  it("registers a global refresh function that apiFetch's 401 interceptor can call", async () => {
    render(<AuthProvider><Consumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(typeof (window as unknown as Record<string, unknown>).__axon_refresh_fn).toBe("function");
  });

  it("a dead/expired stored refresh token clears the session cleanly instead of leaving a broken state", async () => {
    localStorage.setItem("axon_refresh_token", "dead-refresh-tok");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "Session expired" }));

    render(<AuthProvider><Consumer /></AuthProvider>);

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("user")).toHaveTextContent("");
    expect(localStorage.getItem("axon_refresh_token")).toBeNull();
  });
});

describe("AuthProvider — login", () => {
  it("persists refresh_token and sub_token, and sets the in-memory access token, on success", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {
      access_token: "jwt-1", refresh_token: "refresh-1", sub_token: "sub-1", user: fakeUser,
    }));

    render(<AuthProvider><Consumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    fireEvent.click(screen.getByText("login"));

    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("user@example.com"));
    expect(localStorage.getItem("axon_refresh_token")).toBe("refresh-1");
    expect(localStorage.getItem("sub_token")).toBe("sub-1");
    expect((window as unknown as Record<string, string>).__axon_access_token).toBe("jwt-1");
  });
});

describe("AuthProvider — logout", () => {
  it("clears sub_token and the persisted/global org selection, not just the JWT refresh token", async () => {
    // Simulate an already-logged-in session with org state set, the way
    // OrgProvider/login would have left it.
    localStorage.setItem("axon_refresh_token", "refresh-1");
    localStorage.setItem("sub_token", "sub-1");
    localStorage.setItem("axon_current_org_id", "org-1");
    (window as unknown as Record<string, string>).__axon_org_id = "org-1";

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "jwt-1", refresh_token: "refresh-1" })) // bootstrap refresh
      .mockResolvedValueOnce(jsonResponse(200, fakeUser)) // bootstrap /me
      .mockResolvedValueOnce(jsonResponse(200, { message: "Logged out" })); // /api/auth/logout

    render(<AuthProvider><Consumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("user@example.com"));

    fireEvent.click(screen.getByText("logout"));

    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(""));
    expect(localStorage.getItem("axon_refresh_token")).toBeNull();
    expect(localStorage.getItem("sub_token")).toBeNull();
    expect(localStorage.getItem("axon_current_org_id")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__axon_org_id).toBeUndefined();
    expect((window as unknown as Record<string, unknown>).__axon_access_token).toBeNull();
  });
});
