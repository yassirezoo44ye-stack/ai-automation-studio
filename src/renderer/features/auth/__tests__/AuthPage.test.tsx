import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AuthPage } from "../AuthPage";

const login = vi.fn();
const register = vi.fn();
vi.mock("../../../contexts/AuthContext", () => ({
  useAuth: () => ({ login, register }),
}));

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

// ── Forgot password (P0 password-reset flow) ────────────────────────────────

describe("AuthPage — forgot password", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  function goToForgotTab() {
    render(<AuthPage />);
    fireEvent.click(screen.getByText(/forgot password\?/i));
  }

  it("renders the forgot-password form when reached from the login tab", () => {
    goToForgotTab();
    expect(screen.getByRole("heading", { name: /ai automation studio/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send reset link/i })).toBeInTheDocument();
  });

  it("submits the email to /api/auth/forgot-password and shows the generic success message", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "If that email is registered, a reset link has been sent" }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    );
    goToForgotTab();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/auth/forgot-password");
    expect(JSON.parse(String(init.body))).toEqual({ email: "user@example.com" });
    await waitFor(() =>
      expect(screen.getByText("If that email exists, a reset link is on its way.")).toBeInTheDocument(),
    );
  });

  it("shows the same generic success message for an unregistered email — no account enumeration", async () => {
    // The frontend always renders the fixed t("forgot.success") copy, never
    // the backend's response body -- this is true regardless of what the
    // mock returns, which is exactly the point: there is no code path here
    // that could surface a different message for "exists" vs "doesn't".
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "If that email is registered, a reset link has been sent" }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    );
    goToForgotTab();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "nobody@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() =>
      expect(screen.getByText("If that email exists, a reset link is on its way.")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/not registered|no account|does not exist|doesn't exist/i)).not.toBeInTheDocument();
  });
});
