import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ResetPasswordPage } from "../ResetPasswordPage";

function renderWithToken(token: string | null) {
  window.history.pushState({}, "", token ? `/reset-password?token=${token}` : "/reset-password");
  return render(<ResetPasswordPage />);
}

describe("ResetPasswordPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders the new-password form for a valid token, without calling the API yet", () => {
    renderWithToken("valid-token-abc");
    expect(screen.getByLabelText(/^new password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm new password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reset password$/i })).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows the invalid-link state immediately when no token is present in the URL, without calling the API", () => {
    renderWithToken(null);
    expect(screen.getByText(/invalid or missing/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^new password/i)).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("blocks submission when the password confirmation does not match", () => {
    renderWithToken("valid-token-abc");
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "newpassword1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "different1" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));
    expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("submits token + new password to /api/auth/reset-password and shows success on a valid token", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "Password reset successfully. Please log in with your new password." }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    );
    renderWithToken("valid-token-abc");
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "newpassword1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "newpassword1" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/auth/reset-password");
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({ token: "valid-token-abc", password: "newpassword1" });

    await waitFor(() =>
      expect(screen.getByText(/your password has been reset/i)).toBeInTheDocument(),
    );
    // "Return to Login" is offered from the success state.
    expect(screen.getByRole("button", { name: /go to sign in/i })).toBeInTheDocument();
  });

  it("returning to login after success navigates away, not an in-SPA state change", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "ok" }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    // jsdom's real Location.prototype.href is non-configurable, so it
    // can't be spied on in place; assigning to it for real throws "Not
    // implemented: navigation". Render and complete the flow first (so
    // the component has already read the real location for
    // pathname/search), THEN stub the global wholesale via
    // vi.stubGlobal -- restored automatically by this file's afterEach,
    // same mechanism already used for `fetch`, so it can't leak into
    // other tests/files.
    renderWithToken("valid-token-abc");
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "newpassword1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "newpassword1" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));
    await waitFor(() => expect(screen.getByText(/your password has been reset/i)).toBeInTheDocument());

    let assignedHref: string | undefined;
    vi.stubGlobal("location", { set href(v: string) { assignedHref = v; } });

    fireEvent.click(screen.getByRole("button", { name: /go to sign in/i }));
    expect(assignedHref).toBe("/");
  });

  it("handles an invalid/expired token cleanly — an error banner, not a crash, no partial success state", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid or expired reset link" }), {
        status: 400, headers: { "content-type": "application/json" },
      }),
    );
    renderWithToken("expired-token-xyz");
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "newpassword1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "newpassword1" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/your password has been reset/i)).not.toBeInTheDocument();
    // Still on the form -- the user can retry with a fresh request, not stuck.
    expect(screen.getByLabelText(/^new password/i)).toBeInTheDocument();
  });

  it("never sends the password in a GET/query-string context — only inside the POST body", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "ok" }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    renderWithToken("valid-token-abc");
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "supersecret1" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "supersecret1" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain("supersecret1");
    expect(init.method).toBe("POST");
    expect(localStorage.getItem("supersecret1")).toBeNull();
  });
});
