import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { Sidebar } from "../../../components/layout/Sidebar";

// ── Module mocks ──────────────────────────────────────────────────────────────

const mockSetPage = vi.fn();

vi.mock("../../../contexts/app", () => ({
  useAppContext: vi.fn(() => ({
    page: "leads",
    setPage: mockSetPage,
    sidebarCollapsed: false,
    setSidebarCollapsed: vi.fn(),
  })),
}));

vi.mock("../../../contexts/AuthContext", () => ({
  useAuth: vi.fn(() => ({ user: { email: "test@example.com" }, logout: vi.fn() })),
}));

vi.mock("../../../contexts/OrgContext", () => ({
  useOrg: vi.fn(() => ({ orgs: [], currentOrgId: null, setCurrentOrgId: vi.fn() })),
}));

vi.mock("../../../contexts/lang", () => ({
  useLangContext: vi.fn(() => ({ lang: "en", toggleLang: vi.fn() })),
}));

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Sidebar — navigation routes", () => {
  it("renders Teams nav item", () => {
    render(<Sidebar />);
    expect(screen.getByTitle("Teams")).toBeInTheDocument();
  });

  it("renders Billing nav item", () => {
    render(<Sidebar />);
    expect(screen.getByTitle("Billing")).toBeInTheDocument();
  });

  it("renders Settings nav item", () => {
    render(<Sidebar />);
    expect(screen.getByTitle("Settings")).toBeInTheDocument();
  });

  it("navigates to teams page when Teams is clicked", () => {
    render(<Sidebar />);
    fireEvent.click(screen.getByTitle("Teams"));
    expect(mockSetPage).toHaveBeenCalledWith("teams");
  });

  it("navigates to billing page when Billing is clicked", () => {
    render(<Sidebar />);
    fireEvent.click(screen.getByTitle("Billing"));
    expect(mockSetPage).toHaveBeenCalledWith("billing");
  });

  it("existing leads navigation still works", () => {
    render(<Sidebar />);
    fireEvent.click(screen.getByTitle("Leads"));
    expect(mockSetPage).toHaveBeenCalledWith("leads");
  });

  it("existing settings navigation still works", () => {
    render(<Sidebar />);
    fireEvent.click(screen.getByTitle("Settings"));
    expect(mockSetPage).toHaveBeenCalledWith("settings");
  });
});
