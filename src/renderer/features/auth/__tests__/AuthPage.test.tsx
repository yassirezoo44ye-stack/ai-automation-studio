import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AuthPage } from "../AuthPage";

const login = vi.fn();
const register = vi.fn();
vi.mock("../../../contexts/AuthContext", () => ({
  useAuth: () => ({ login, register }),
}));

// ── Reset-password tab (URL-driven) ─────────────────────────────────────────

describe("AuthPage — password reset tab (URL token flow)", () => {
  const originalPathname  = window.location.pathname;
  const originalSearch    = window.location.search;
  const replaceStateSpy   = vi.spyOn(window.history, "replaceState");

  afterEach(() => {
    // Restore URL after each test so other suites see the normal '/' path
    Object.defineProperty(window, "location", {
      value: { ...window.location, pathname: originalPathname, search: originalSearch },
      writable: true,
      configurable: true,
    });
    replaceStateSpy.mockClear();
  });

  function setResetUrl(token: string) {
    Object.defineProperty(window, "location", {
      value: { ...window.location, pathname: "/reset-password", search: `?token=${token}` },
      writable: true,
      configurable: true,
    });
  }

  it("shows the reset-password form when the URL is /reset-password?token=...", () => {
    setResetUrl("abc123");
    render(<AuthPage />);
    expect(screen.getByText(/enter a new password/i)).toBeInTheDocument();
    // Login/Register tabs should NOT be visible on the reset view
    expect(screen.queryByRole("tab", { name: /sign in/i })).not.toBeInTheDocument();
  });

  it("cleans the token from the URL bar on mount (token is sensitive)", () => {
    setResetUrl("secret-token");
    render(<AuthPage />);
    expect(replaceStateSpy).toHaveBeenCalledWith(null, "", "/");
  });

  it("does not switch to reset tab when URL has no token param", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, pathname: "/reset-password", search: "" },
      writable: true,
      configurable: true,
    });
    render(<AuthPage />);
    // Without a token, we stay on the default login tab
    expect(screen.queryByText(/enter a new password/i)).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /sign in/i })).toBeInTheDocument();
  });

  it("reset form shows validation error when passwords do not match", async () => {
    setResetUrl("tok1");
    render(<AuthPage />);
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "NewPass1!" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "Different1!" } });
    fireEvent.click(screen.getByRole("button", { name: /set new password/i }));
    await waitFor(() => expect(screen.getByText("Passwords do not match")).toBeInTheDocument());
  });

  it("on reset success, shows a success banner and a back-to-sign-in button", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200,
      headers: { get: () => "application/json" },
      text: async () => JSON.stringify({ message: "Password reset successful" }),
    }));
    setResetUrl("valid-token");
    render(<AuthPage />);
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "Str0ngPass!" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "Str0ngPass!" } });
    fireEvent.click(screen.getByRole("button", { name: /set new password/i }));
    await waitFor(() => expect(screen.getByText(/password updated/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /back to sign in/i })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

// ── Login form ───────────────────────────────────────────────────────────────

describe("AuthPage — login form (framework flagship migration)", () => {
  beforeEach(() => { login.mockReset(); register.mockReset(); });

  it("shows field errors and does not call login when submitted empty — no silent failure, no alert()", () => {
    const alertSpy = vi.spyOn(window, "alert");
    render(<AuthPage />);
    fireEvent.click(screen.getByRole("button", { name: /sign in$/i }));
    expect(screen.getByText("Email is required")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("rejects a malformed email with a field-level error before ever calling login", () => {
    render(<AuthPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "not-an-email" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in$/i }));
    expect(screen.getByText(/enter a valid email/i)).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });

  it("calls login with the entered credentials once the form is valid", async () => {
    login.mockResolvedValueOnce(undefined);
    render(<AuthPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in$/i }));
    await waitFor(() => expect(login).toHaveBeenCalledWith("user@example.com", "secret123", false));
  });

  it("surfaces a rejected login as a visible error banner, not a swallowed exception", async () => {
    login.mockRejectedValueOnce(new Error("Invalid credentials"));
    render(<AuthPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in$/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Invalid credentials"));
  });

  it("disables the submit button while the login request is in flight, preventing a duplicate submit", async () => {
    let resolveLogin!: () => void;
    login.mockImplementationOnce(() => new Promise<void>(resolve => { resolveLogin = resolve; }));
    render(<AuthPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "secret123" } });
    const submitBtn = screen.getByRole("button", { name: /sign in$/i });
    fireEvent.click(submitBtn);
    await waitFor(() => expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: /signing in/i })); // duplicate click while in flight
    expect(login).toHaveBeenCalledTimes(1);
    resolveLogin();
  });

  it("register form rejects a mismatched confirm-password before calling register", () => {
    render(<AuthPage />);
    fireEvent.click(screen.getByRole("tab", { name: /create account/i }));
    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^email/i), { target: { value: "ada@example.com" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "password1" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "different1" } });
    fireEvent.click(screen.getByRole("button", { name: /create account$/i }));
    expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();
  });
});
