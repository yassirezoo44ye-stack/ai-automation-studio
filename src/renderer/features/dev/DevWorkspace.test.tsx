import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DevWorkspace } from "./DevWorkspace";
import { apiFetch } from "../../utils/api";
import type * as ApiModule from "../../utils/api";
import i18n from "../../i18n";
const toast = vi.hoisted(() => vi.fn());
vi.mock("../../contexts/toast", () => ({ useToast: () => toast }));
vi.mock("../../contexts/app", () => ({ useAppContext: () => ({ activeProjectId: "project-1" }) }));
vi.mock("./tabs/BuildTab", () => ({ BuildTab: () => null }));
vi.mock("../../utils/api", async original => ({ ...await original<typeof ApiModule>(), apiFetch: vi.fn() }));
beforeEach(async () => {
  vi.resetAllMocks(); await i18n.changeLanguage("en");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(apiFetch).mockImplementation(async (path, options) => {
    if (options?.method === "DELETE" || path.endsWith("/download")) return new Response(null, { status: 403 });
    return new Response(JSON.stringify(path === "/api/projects" ? [{ id: "project-1", name: "Example" }] : { files: [{ path: "index.html", size: 20 }] }), { status: 200 });
  });
});
it("preserves the workspace file list after a rejected clear", async () => {
  render(<DevWorkspace />); await screen.findByRole("tab", { name: /Files.*1/ });
  fireEvent.click(screen.getByRole("button", { name: /Clear/ }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Could not clear the workspace. Your files were kept.", "err"));
  expect(screen.getByRole("tab", { name: /Files.*1/ })).toBeInTheDocument();
  expect(toast).not.toHaveBeenCalledWith("Workspace cleared");
});
it("reports a failed project download", async () => {
  render(<DevWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /ZIP/ }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Could not download the project. Please try again.", "err"));
});
