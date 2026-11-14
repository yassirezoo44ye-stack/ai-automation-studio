import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlanRunsPanel } from "./PlanRunsPanel";
import { apiFetch } from "../../../utils/api";
import type * as ApiModule from "../../../utils/api";
import i18n from "../../../i18n";

vi.mock("../../../shared/utils/api", async original => ({ ...await original<typeof ApiModule>(), apiFetch: vi.fn() }));
const mockFetch = vi.mocked(apiFetch);
const skills = [{ id: "flow-project-planning", title: "Project planning", description: "Planning" }];
const tasks = [{ key: "scope", title: "Approve scope", status: "pending", depends_on: [] }];
const run = { id: "run-one", plan_id: "plan-one", node_id: "scope", runner: "inspect_project", skill_id: null,
  status: "queued", created_at: "2026-11-14T00:00:00Z", started_at: null, finished_at: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
let rows: typeof run[] = [];
beforeEach(async () => {
  localStorage.clear(); rows = [];
  await i18n.changeLanguage("en");
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (path, init) => {
    if (path === "/api/agents/skills") return json({ skills });
    if (init?.method === "POST") { rows = [run]; return json(run, 202); }
    if (init?.method === "DELETE") { rows = [{ ...run, status: "cancelled" }]; return json({ ...rows[0], log: [], output: null, error: null }); }
    if (path.endsWith("/runs/run-one")) return json({ ...rows[0], output: rows[0]?.status === "completed" ? 'Inspection report: code_executed=false' : null,
      error: null, log: ["Approved task snapshot", "Worker claimed approved run"], acceptance_verified: false });
    return json({ runs: rows });
  });
});
afterEach(cleanup);

it("requires approval for the exact configuration and sends no arbitrary agent or workspace", async () => {
  const started = vi.fn();
  render(<PlanRunsPanel planId="plan-one" tasks={tasks} onStarted={started} />);
  await screen.findByRole("option", { name: "Project planning" });
  fireEvent.change(screen.getByLabelText("Skill for this run"), { target: { value: skills[0].id } });
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "Start approved run" })).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Execution mode"), { target: { value: "inspect_project" } });
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Start approved run" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Start approved run" }));
  await waitFor(() => expect(started).toHaveBeenCalledOnce());
  const options = mockFetch.mock.calls.find(([, init]) => init?.method === "POST")?.[1];
  const body = JSON.parse(String(options?.body));
  expect(body).toEqual({ request_id: expect.any(String), approved: true, runner: "inspect_project", skill_id: null });
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

it("reopens a completed result and keeps acceptance subject to review", async () => {
  rows = [{ ...run, status: "completed" }];
  const view = render(<PlanRunsPanel planId="plan-one" tasks={tasks} onStarted={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Approve scope — Result ready" }));
  expect(await screen.findByText('Inspection report: code_executed=false')).toBeInTheDocument();
  expect(screen.getByText(/A completed run is not proof/)).toBeInTheDocument();
  view.unmount();
  render(<PlanRunsPanel planId="plan-one" tasks={tasks} onStarted={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Approve scope — Result ready" }));
  expect(await screen.findByText('Inspection report: code_executed=false')).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve scope — Result ready" }));
  expect(await screen.findByText('Inspection report: code_executed=false')).toBeInTheDocument();
});

it("cancels a queued run without showing a deliverable", async () => {
  rows = [run];
  render(<PlanRunsPanel planId="plan-one" tasks={tasks} onStarted={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
  await screen.findByRole("button", { name: "Approve scope — Cancelled" });
  expect(screen.queryByRole("button", { name: "Download result" })).not.toBeInTheDocument();
});

it("retains the request key after a lost/failed response", async () => {
  const original = mockFetch.getMockImplementation()!;
  const keys: string[] = [];
  mockFetch.mockImplementation(async (path, init) => {
    if (init?.method === "POST") {
      keys.push(JSON.parse(String(init.body)).request_id as string);
      if (keys.length === 1) return json({ detail: "Temporary error" }, 503);
    }
    return original(path, init);
  });
  render(<PlanRunsPanel planId="plan-one" tasks={tasks} onStarted={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Execution mode"), { target: { value: "inspect_project" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Start approved run" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Start approved run" }));
  await screen.findByRole("button", { name: "Approve scope — Queued" });
  expect(keys).toHaveLength(2); expect(keys[0]).toBe(keys[1]);
});
