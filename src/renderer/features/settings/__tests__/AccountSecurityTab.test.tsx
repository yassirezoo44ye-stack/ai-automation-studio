import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { AccountSecurityTab } from "../AccountSecurityTab";

vi.mock("../../../utils/api", () => ({ apiFetch: vi.fn() }));

const auth = {
  user: { id: "u1", email: "u@example.com", name: "U", has_password: true, mfa_enabled: false } as Record<string, unknown> | null,
  logout: vi.fn(),
  refreshUser: vi.fn(),
  updateProfile: vi.fn(),
};
vi.mock("../../../contexts/AuthContext", () => ({ useAuth: () => auth }));

import { apiFetch } from "../../../utils/api";
const mockedApiFetch = vi.mocked(apiFetch);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const SESSIONS = [
  { id: "s1", ip_address: "1.2.3.4", user_agent: "Firefox on Linux", created_at: "2026-11-01T10:00:00Z", last_used_at: null },
];

function route(handlers: Record<string, () => Response>) {
  mockedApiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    const h = handlers[key];
    if (!h) throw new Error(`unexpected call ${key}`);
    return h();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.user = { id: "u1", email: "u@example.com", name: "U", has_password: true, mfa_enabled: false };
});

describe("AccountSecurityTab", () => {
  it("lists sessions and revokes one", async () => {
    route({
      "GET /api/auth/sessions": () => json(SESSIONS),
      "DELETE /api/auth/sessions/s1": () => json({ revoked: true }),
    });
    render(<AccountSecurityTab />);
    expect(await screen.findByText("Firefox on Linux")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.queryByText("Firefox on Linux")).not.toBeInTheDocument());
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/sessions/s1", expect.objectContaining({ method: "DELETE" }));
  });

  it("translates a wrong current password", async () => {
    route({
      "GET /api/auth/sessions": () => json([]),
      "PUT /api/auth/me/password": () => json({ detail: "Current password is incorrect" }, 400),
    });
    render(<AccountSecurityTab />);
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "old-pass" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-password-1" } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "new-password-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("Current password is incorrect.")).toBeInTheDocument();
    expect(auth.logout).not.toHaveBeenCalled();
  });

  it("shows a rate-limit message on 429", async () => {
    route({
      "GET /api/auth/sessions": () => json({ detail: "Too many attempts" }, 429),
    });
    render(<AccountSecurityTab />);
    expect(await screen.findByText("Too many attempts. Please wait a minute.")).toBeInTheDocument();
  });

  it("hides password forms for accounts that sign in with a provider", async () => {
    auth.user = { id: "u1", email: "u@example.com", name: "U", has_password: false, mfa_enabled: false };
    route({ "GET /api/auth/sessions": () => json([]) });
    render(<AccountSecurityTab />);
    await screen.findByText("No other active sessions.");
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
    // Provider accounts delete by typing their e-mail only (no password field).
    fireEvent.click(screen.getByTestId("delete-account-start"));
    expect(screen.getByTestId("delete-email")).toBeInTheDocument();
    expect(screen.queryByTestId("delete-password")).not.toBeInTheDocument();
  });

  it("asks to sign in when there is no user", () => {
    auth.user = null;
    render(<AccountSecurityTab />);
    expect(screen.getByText(/signed out/)).toBeInTheDocument();
  });
});
