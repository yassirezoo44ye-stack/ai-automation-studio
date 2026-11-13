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

it("retains editable problem details when the server rejects the save", async () => {
  render(<AutomationPage />); await screen.findByText("Keep this task");
  fireEvent.click(screen.getByRole("button", { name: "Edit task" }));
  const details = screen.getByRole("textbox", { name: "Problem, evidence, proposed improvements and acceptance criteria" });
  fireEvent.change(details, { target: { value: "Problem: missing reply\nImprovement: retry and restore\nAcceptance: reply survives reload" } });
  fireEvent.click(screen.getByRole("button", { name: "Save task" }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Task update failed. Your task was kept.", "err"));
  expect(details).toHaveValue("Problem: missing reply\nImprovement: retry and restore\nAcceptance: reply survives reload");
});

it("saves full task details without losing line breaks", async () => {
  failMutation = false;
  render(<AutomationPage />); await screen.findByText("Keep this task");
  fireEvent.click(screen.getByRole("button", { name: "Edit task" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Problem, evidence, proposed improvements and acceptance criteria" }), { target: { value: "المشكلة: تعذر التنزيل\nالتطوير: إعادة المحاولة" } });
  fireEvent.click(screen.getByRole("button", { name: "Save task" }));
  await screen.findByText(/المشكلة: تعذر التنزيل/);
  expect(screen.queryByRole("button", { name: "Save task" })).not.toBeInTheDocument();
  const mutation = vi.mocked(apiFetch).mock.calls.find(([, options]) => options?.method === "PUT");
  expect(JSON.parse(mutation![1]!.body as string)).toEqual({ title: "Keep this task", notes: "المشكلة: تعذر التنزيل\nالتطوير: إعادة المحاولة" });
});
