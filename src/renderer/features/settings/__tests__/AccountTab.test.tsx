import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AccountTab } from "../AccountTab";

vi.mock("../../../utils/api", () => ({ apiFetch: vi.fn() }));
vi.mock("../../../contexts/lang", () => ({
  useLangContext: () => ({ lang: "en", setLang: vi.fn(), toggleLang: vi.fn() }),
}));
const authState: { user: Record<string, unknown> | null; logout: ReturnType<typeof vi.fn> } = {
  user: null, logout: vi.fn(),
};
vi.mock("../../../contexts/AuthContext", () => ({ useAuth: () => authState }));

import { apiFetch } from "../../../utils/api";
const mockedFetch = vi.mocked(apiFetch);

function user(hasPassword: boolean) {
  return { id: "u1", email: "me@example.com", name: "Me", email_verified: true, avatar_url: null, created_at: null, has_password: hasPassword };
}

function openDelete() {
  fireEvent.click(screen.getByTestId("delete-account-start"));
}

describe("AccountTab", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
    authState.logout = vi.fn().mockResolvedValue(undefined);
  });

  it("lets an OAuth-only account delete by typing its e-mail, without a password field", async () => {
    authState.user = user(false);
    mockedFetch.mockResolvedValue(new Response(JSON.stringify({ message: "Account deleted" }), { status: 200 }));
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, assign }, writable: true });
    render(<AccountTab />);
    openDelete();
    expect(screen.queryByTestId("delete-password")).toBeNull();
    const confirm = screen.getByTestId("delete-account-confirm");
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByTestId("delete-email"), { target: { value: "ME@example.com" } });
    expect(confirm).not.toBeDisabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(authState.logout).toHaveBeenCalled());
    const [path, init] = mockedFetch.mock.calls[0];
    expect(path).toBe("/api/auth/me");
    expect(init?.method).toBe("DELETE");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "ME@example.com" });
    expect(assign).toHaveBeenCalledWith("/");
  });

  it("requires the password for password accounts", () => {
    authState.user = user(true);
    render(<AccountTab />);
    openDelete();
    fireEvent.change(screen.getByTestId("delete-email"), { target: { value: "me@example.com" } });
    expect(screen.getByTestId("delete-account-confirm")).toBeDisabled();
    fireEvent.change(screen.getByTestId("delete-password"), { target: { value: "pw" } });
    expect(screen.getByTestId("delete-account-confirm")).not.toBeDisabled();
  });

  it("explains which organizations need a new owner and stays signed in", async () => {
    authState.user = user(true);
    mockedFetch.mockResolvedValue(new Response(
      JSON.stringify({ detail: { message: "Transfer ownership", organizations: ["Team A"] } }), { status: 409 },
    ));
    render(<AccountTab />);
    openDelete();
    fireEvent.change(screen.getByTestId("delete-email"), { target: { value: "me@example.com" } });
    fireEvent.change(screen.getByTestId("delete-password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByTestId("delete-account-confirm"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Team A");
    expect(authState.logout).not.toHaveBeenCalled();
  });

  it("downloads the data export", async () => {
    authState.user = user(true);
    mockedFetch.mockResolvedValue(new Response("{}", { status: 200 }));
    const createObjectURL = vi.fn(() => "blob:x");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    render(<AccountTab />);
    fireEvent.click(screen.getByTestId("export-data"));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(mockedFetch).toHaveBeenCalledWith("/api/auth/me/export");
  });
});
