import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AutomationPage } from "./AutomationPage";
import { apiFetch } from "../../utils/api";
import type * as ApiModule from "../../utils/api";
import i18n from "../../i18n";
const toast = vi.hoisted(() => vi.fn());
vi.mock("../../contexts/toast", () => ({ useToast: () => toast }));
vi.mock("../../utils/api", async original => ({ ...await original<typeof ApiModule>(), apiFetch: vi.fn() }));
let failMutation = true;
beforeEach(async () => {
  vi.resetAllMocks(); failMutation = true; await i18n.changeLanguage("en");
  vi.mocked(apiFetch).mockImplementation(async (path, options) => {
    if (options?.method) return new Response(null, { status: failMutation ? 403 : 204 });
    const body = path.startsWith("/api/tasks") ? { tasks: [{ id: "t-1", title: "Keep this task", status: "pending", priority: "medium", created_at: "2026-11-01T08:00:00Z" }] } : path.startsWith("/api/automation-runs") ? { items: [] } : [];
    return new Response(JSON.stringify(body), { status: 200 });
  });
});
it("keeps a task pending and reports a rejected update", async () => {
  render(<AutomationPage />); await screen.findByText("Keep this task");
  fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Task update failed. Your task was kept.", "err"));
  expect(screen.getByRole("button", { name: "Mark done" })).toBeInTheDocument();
});
it("keeps a task visible and reports a rejected delete", async () => {
  render(<AutomationPage />); await screen.findByText("Keep this task");
  fireEvent.click(screen.getByTitle("Delete"));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Task deletion failed. Your task was kept.", "err"));
  expect(screen.getByText("Keep this task")).toBeInTheDocument();
});
it("updates a task after the server accepts it", async () => {
  failMutation = false; render(<AutomationPage />); await screen.findByText("Keep this task");
  fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
  await screen.findByRole("button", { name: "Mark pending" });
});

it("shows persisted pending and completed runs rather than filtering to running only", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    if (path.startsWith("/api/automation-runs")) {
      return new Response(JSON.stringify({ items: [
        { run_id: "run-pending-1", name: "Pending order sync", status: "pending" },
        { run_id: "run-complete-2", name: "Completed order sync", status: "completed" },
      ] }), { status: 200 });
    }
    return new Response(JSON.stringify(path.startsWith("/api/tasks") ? { tasks: [] } : []), { status: 200 });
  });
  render(<AutomationPage />);
  fireEvent.click(screen.getByRole("tab", { name: "Workflows" }));
  expect(await screen.findByText(/Pending order sync/)).toBeInTheDocument();
  expect(screen.getByText(/Completed order sync/)).toBeInTheDocument();
  expect(vi.mocked(apiFetch).mock.calls.some(([url]) => url === "/api/automation-runs?limit=20")).toBe(true);
});

it("does not issue overlapping workflow refresh requests", async () => {
  let resolveRuns!: (response: Response) => void;
  let requests = 0;
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    if (path.startsWith("/api/automation-runs")) {
      requests += 1;
      return new Promise<Response>(resolve => { resolveRuns = resolve; });
    }
    return new Response(JSON.stringify(path.startsWith("/api/tasks") ? { tasks: [] } : []), { status: 200 });
  });
  render(<AutomationPage />);
  fireEvent.click(screen.getByRole("tab", { name: "Workflows" }));
  await waitFor(() => expect(requests).toBe(1));
  fireEvent.click(screen.getByRole("button", { name: /Refresh/i }));
  expect(requests).toBe(1);
  resolveRuns(new Response(JSON.stringify({ items: [] }), { status: 200 }));
  await waitFor(() => expect(screen.queryByText("…")).not.toBeInTheDocument());
});
