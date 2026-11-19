import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../../i18n";
import { AppProvider } from "../../../contexts/AppContext";
import { LangProvider } from "../../../contexts/LangContext";
import { useAppContext } from "../../../contexts/app";
import { SettingsPage } from "../SettingsPage";
import type * as ApiModule from "../../../shared/utils/api";
import { apiFetch } from "../../../shared/utils/api";
import { loadPrefs } from "../../../shared/utils/preferences";
import { streamBuild } from "../../app-builder/services/builderService";

vi.mock("../../../contexts/OrgContext", () => ({ useOrg: () => ({ currentOrgId: null }) }));
vi.mock("../../../shared/utils/api", async original => ({ ...await original<typeof ApiModule>(), apiFetch: vi.fn() }));

function Probe() {
  const { sidebarCollapsed } = useAppContext();
  return <span data-testid="sidebar-mode">{sidebarCollapsed ? "collapsed" : "expanded"}</span>;
}
function showSettings() {
  return render(<LangProvider><AppProvider><SettingsPage /><Probe /></AppProvider></LangProvider>);
}

beforeEach(async () => {
  vi.restoreAllMocks();
  localStorage.clear();
  window.history.replaceState(null, "", "/settings");
  await i18n.changeLanguage("en");
  vi.mocked(apiFetch).mockImplementation(async path => {
    if (path === "/api/health/full") return Response.json({ status: "healthy", checks: { database: "ok", pg_version: "PostgreSQL 16 test" } });
    if (path === "/api/build/stream") return new Response('data: {"type":"done","files":[],"language":"python","run_command":"python main.py"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
    return Response.json({});
  });
});

describe("Working settings", () => {
  it("persists model choices and uses the build choice in the actual build request", async () => {
    const view = showSettings();
    fireEvent.click(screen.getByRole("button", { name: "AI & Models" }));
    fireEvent.change(screen.getByLabelText("Chat Model"), { target: { value: "claude-haiku-4-5-20251001" } });
    fireEvent.change(screen.getByLabelText("Build Model"), { target: { value: "claude-opus-4-8" } });
    expect(loadPrefs().chatModel).toBe("claude-haiku-4-5-20251001");
    for await (const event of streamBuild("project", "Build a script")) { if (event.type === "done") break; }
    const call = vi.mocked(apiFetch).mock.calls.find(([path]) => path === "/api/build/stream")!;
    expect(JSON.parse(call[1]!.body as string).model).toBe("claude-opus-4-8");
    view.unmount();
    showSettings();
    fireEvent.click(screen.getByRole("button", { name: "AI & Models" }));
    expect(screen.getByLabelText("Build Model")).toHaveValue("claude-opus-4-8");
    expect(screen.getByLabelText("Chat Model")).toHaveValue("claude-haiku-4-5-20251001");
  });

  it("restores the selected sidebar mode after reopening the application", () => {
    const view = showSettings();
    fireEvent.change(screen.getByLabelText("Sidebar default"), { target: { value: "collapsed" } });
    expect(screen.getByTestId("sidebar-mode")).toHaveTextContent("collapsed");
    view.unmount();
    showSettings();
    expect(screen.getByTestId("sidebar-mode")).toHaveTextContent("collapsed");
  });

  it("reports storage failures instead of claiming preferences were saved", () => {
    showSettings();
    fireEvent.click(screen.getByRole("button", { name: "AI & Models" }));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage unavailable"); });
    fireEvent.change(screen.getByLabelText("Chat Model"), { target: { value: "claude-opus-4-8" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save preferences");
    expect(loadPrefs().chatModel).toBe("claude-sonnet-4-6");
    expect(screen.queryByText("Saved in this browser")).not.toBeInTheDocument();
  });

  it("shows database diagnostics from the full health response", async () => {
    showSettings();
    fireEvent.click(screen.getByRole("button", { name: "System" }));
    await waitFor(() => expect(screen.getByText("PostgreSQL 16 test")).toBeInTheDocument());
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/api/health/full");
  });
});
