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
    // AUDIT FIX regression test: this is doRefresh()'s 401 branch — the
    // most common way a session actually ends (natural expiry, not an
    // explicit Logout click). Previously it cleared only the JWT refresh
    // token and left sub_token/org selection behind, same leak class as
    // the logout() test below.
    localStorage.setItem("axon_refresh_token", "dead-refresh-tok");
    localStorage.setItem("sub_token", "sub-1");
    localStorage.setItem("axon_current_org_id", "org-1");
    (window as unknown as Record<string, string>).__axon_org_id = "org-1";
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "Session expired" }));

    render(<AuthProvider><Consumer /></AuthProvider>);

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("user")).toHaveTextContent("");
    expect(localStorage.getItem("axon_refresh_token")).toBeNull();
    expect(localStorage.getItem("sub_token")).toBeNull();
    expect(localStorage.getItem("axon_current_org_id")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__axon_org_id).toBeUndefined();
  });

  it("a token revoked server-side (fetchMe's own 401) also clears sub_token/org, not just the JWT", async () => {
    // AUDIT FIX regression test: fetchMe()'s 401 branch — reached when the
    // refresh itself succeeds but the immediately-following /api/auth/me
    // call is rejected (token revoked between the two calls). Same leak
    // class as the two tests above.
    localStorage.setItem("axon_refresh_token", "stored-refresh-tok");
    localStorage.setItem("sub_token", "sub-1");
    localStorage.setItem("axon_current_org_id", "org-1");
    (window as unknown as Record<string, string>).__axon_org_id = "org-1";
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "new-jwt", refresh_token: "rotated-refresh" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Token revoked" })); // /api/auth/me

    render(<AuthProvider><Consumer /></AuthProvider>);

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("user")).toHaveTextContent("");
    expect(localStorage.getItem("axon_refresh_token")).toBeNull();
    expect(localStorage.getItem("sub_token")).toBeNull();
    expect(localStorage.getItem("axon_current_org_id")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__axon_org_id).toBeUndefined();
  });
});

describe("AuthProvider — concurrent refresh", () => {
  it("two simultaneous refresh calls share one in-flight request, not two", async () => {
    // Phase 1 audit: doRefresh() dedupes concurrent callers onto a single
    // in-flight promise (refreshInFlightRef) — without this, two
    // /api/auth/refresh calls would race with the same stored (single-use,
    // rotate-on-use) refresh token; the backend rotates it on the first
    // and 401s the second, whose "legitimately expired" handling would
    // then clear the session the first call just established. This test
    // proves the dedup actually happens, not just that it's documented.
    localStorage.setItem("axon_refresh_token", "stored-refresh-tok");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;

    let resolveRefresh!: (r: Response) => void;
    const pendingRefresh = new Promise<Response>(resolve => { resolveRefresh = resolve; });
    fetchMock
      .mockReturnValueOnce(pendingRefresh) // bootstrap's own refresh call
      .mockResolvedValueOnce(jsonResponse(200, fakeUser)); // bootstrap's /me

    render(<AuthProvider><Consumer /></AuthProvider>);
    await waitFor(() => expect(
      typeof (window as unknown as Record<string, unknown>).__axon_refresh_fn,
    ).toBe("function"));

    // Two callers race a second, concurrent refresh while the bootstrap's
    // own refresh call above is still unresolved.
    const refreshFn = (window as unknown as Record<string, () => Promise<{ token: string | null }>>).__axon_refresh_fn;
    const call1 = refreshFn();
    const call2 = refreshFn();

    resolveRefresh(jsonResponse(200, { access_token: "shared-jwt", refresh_token: "shared-rotated" }));
    const [result1, result2] = await Promise.all([call1, call2]);

    expect(result1.token).toBe("shared-jwt");
    expect(result2.token).toBe("shared-jwt");
    // Exactly 2 fetch calls total for this whole scenario (1 refresh + 1
    // /me) — not 3, which is what a second, un-deduped refresh call would
    // have produced.
    expect(fetchMock).toHaveBeenCalledTimes(2);
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
