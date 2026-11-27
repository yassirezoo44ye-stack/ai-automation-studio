import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { matchesQuery, normalizeSearch } from "../commandSearch";

vi.mock("../../../contexts/app", () => ({
  useAppContext: () => ({ activeProjectId: null, setActiveProject: vi.fn() }),
}));

import { CommandPalette } from "../CommandPalette";

describe("command palette search", () => {
  it("folds Arabic spelling variants", () => {
    expect(normalizeSearch("الفوترة")).toBe(normalizeSearch("الفوتره"));
    expect(normalizeSearch("أتمتة")).toBe(normalizeSearch("اتمته"));
  });

  it("matches keywords as well as the label", () => {
    expect(matchesQuery({ label: "Billing", keywords: ["الفوترة"] }, "فوتره")).toBe(true);
    expect(matchesQuery({ label: "Billing" }, "teams")).toBe(false);
  });

  it.each([
    ["leads", "leads"], ["billing", "billing"], ["teams", "teams"],
    ["training", "training"], ["business lab", "business-lab"],
  ])("finds the %s page and Enter opens it", (query, page) => {
    const onNavigate = vi.fn();
    render(<CommandPalette onNavigate={onNavigate} onClose={() => {}} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: query } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith(page);
  });

  it("finds pages by their Arabic name", () => {
    const onNavigate = vi.fn();
    render(<CommandPalette onNavigate={onNavigate} onClose={() => {}} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "العملاء المحتملون" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("leads");
  });
});
