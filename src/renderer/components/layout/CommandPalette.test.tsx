import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import i18n from "../../i18n";
import { CommandPalette } from "./CommandPalette";

vi.mock("../../contexts/app", () => ({
  useAppContext: () => ({ activeProjectId: null, setActiveProject: vi.fn() }),
}));

beforeEach(async () => { await i18n.changeLanguage("en"); });
afterEach(async () => { await i18n.changeLanguage("en"); });

function open() {
  const onNavigate = vi.fn();
  const onClose = vi.fn();
  render(<CommandPalette onNavigate={onNavigate} onClose={onClose} />);
  const input = screen.getByRole("textbox");
  return { onNavigate, onClose, search: (q: string) => fireEvent.change(input, { target: { value: q } }), input };
}

it.each([
  ["Leads", "leads"],
  ["Billing", "billing"],
  ["Teams", "teams"],
  ["Training", "training"],
  ["Business Lab", "business-lab"],
])("finds the sidebar page %s and opens it", (query, page) => {
  const { onNavigate, search, input } = open();
  search(query);
  expect(screen.queryByText(/No results/)).not.toBeInTheDocument();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onNavigate).toHaveBeenCalledWith(page);
});

it("finds pages by their Arabic name when the UI is in Arabic", async () => {
  await i18n.changeLanguage("ar");
  const { onNavigate, search, input } = open();
  search("العملاء");
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onNavigate).toHaveBeenCalledWith("leads");
});

it("finds an existing English entry by its Arabic sidebar name", async () => {
  await i18n.changeLanguage("ar");
  const { onNavigate, search, input } = open();
  search("الإعدادات");
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onNavigate).toHaveBeenCalledWith("settings");
});

it("still shows no results for nonsense", () => {
  const { search } = open();
  search("zzqqxx");
  expect(screen.getByText(/No results/)).toBeInTheDocument();
});
