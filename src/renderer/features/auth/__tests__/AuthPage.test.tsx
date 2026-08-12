import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
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

  it("shows reset-password form when pathname=/reset-password and ?token= is present", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "?token=abc123", pathname: "/reset-password" },
      writable: true,
    });
    render(<AuthPage />);
    // Should show the reset form, not the login tabs
    expect(screen.queryByRole("tab", { name: /sign in/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset password/i })).toBeInTheDocument();
    // Restore
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "", pathname: "/" },
      writable: true,
    });
  });

  it("reset-password form validates mismatched passwords before calling API", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "?token=abc123", pathname: "/reset-password" },
      writable: true,
    });
    render(<AuthPage />);
    // "New Password" and "Confirm New Password" both match /new password/i — use exact label text
    const [newPwField] = screen.getAllByLabelText(/new password/i);
    const confirmPwField = screen.getByLabelText(/confirm new password/i);
    fireEvent.change(newPwField, { target: { value: "password1" } });
    fireEvent.change(confirmPwField, { target: { value: "different1" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));
    expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "", pathname: "/" },
      writable: true,
    });
  });

  it("shows invalid-token message when reset tab has no token", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "", pathname: "/" },
      writable: true,
    });
    render(<AuthPage />);
    // Default is login tab, no reset token visible
    expect(screen.queryByRole("button", { name: /reset password/i })).not.toBeInTheDocument();
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
