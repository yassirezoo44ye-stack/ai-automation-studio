import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlansTab } from "./PlansTab";
import { apiFetch } from "../../../utils/api";
import type * as ApiModule from "../../../utils/api";
import i18n from "../../../i18n";

vi.mock("./PlanRunsPanel", () => ({ PlanRunsPanel: () => null }));
let org: string | null = null;
vi.mock("../../../contexts/OrgContext", () => ({ useOrg: () => ({ currentOrgId: org }) }));
vi.mock("../../../utils/api", async original => ({ ...await original<typeof ApiModule>(), apiFetch: vi.fn() }));
const draft = { title: "CRM project", goal: "Build a small CRM", tasks: [
  { key: "scope", title: "Scope", acceptance: ["Scope approved"], depends_on: [], priority: "high" },
  { key: "build", title: "Build", acceptance: ["Data persists"], depends_on: ["scope"], priority: "medium" },
] };
const plan = { ...draft, id: "plan-one", project_id: "project-one", completed: 0, total: 2,
  tasks: draft.tasks.map((node, i) => ({ ...node, task_id: `task-${i}`, status: "pending" })) };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const fetchMock = vi.mocked(apiFetch);
beforeEach(async () => {
  org = null;
  await i18n.changeLanguage("en");
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (path, init) => {
    if (path.endsWith("/draft")) return json({ draft, saved: false });
    if (init?.method === "POST") return json(plan, 201);
    if (path.endsWith("/tasks/scope")) return json({ ...plan, completed: 1,
      tasks: [{ ...plan.tasks[0], status: "done" }, plan.tasks[1]] });
    if (path.endsWith("/plan-one")) return json(plan);
    return json({ plans: [{ id: plan.id, title: plan.title, completed: 0, total: 2 }] });
  });
});
afterEach(cleanup);

it("reviews an editable draft before saving and tracks prerequisite task progress", async () => {
  const changed = vi.fn();
  render(<PlansTab onProjectsChanged={changed} />);
  await screen.findByRole("button", { name: "CRM project — 0/2" });
  fireEvent.change(screen.getByLabelText("Describe your idea"), { target: { value: "Build a CRM" } });
  fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
  await screen.findByText("Review before saving");
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST" && !String(init.body).includes('"goal":"Build a CRM"'))).toBe(false);
  fireEvent.change(screen.getByLabelText("Project title"), { target: { value: "Reviewed CRM" } });
  fireEvent.click(screen.getByRole("button", { name: "Create project and tasks" }));
  await screen.findByText("0 of 2 tasks completed");
  expect(changed).toHaveBeenCalledOnce();
  const save = fetchMock.mock.calls.find(([path, init]) => path === "/api/project-plans" && init?.method === "POST");
  expect(JSON.parse(String(save?.[1]?.body)).draft.title).toBe("Reviewed CRM");
  const selectors = screen.getAllByLabelText("Task status");
  expect(selectors[1].querySelector('option[value="done"]')).toBeDisabled();
  fireEvent.change(selectors[0], { target: { value: "done" } });
  await screen.findByText("1 of 2 tasks completed");
  expect(screen.getAllByLabelText("Task status")[1].querySelector('option[value="done"]')).toBeEnabled();
});

it("restores saved plans on a fresh mount", async () => {
  const props = { onProjectsChanged: vi.fn() };
  const first = render(<PlansTab {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "CRM project — 0/2" }));
  await screen.findByText("0 of 2 tasks completed");
  first.unmount();
  render(<PlansTab {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "CRM project — 0/2" }));
  expect(await screen.findByText("0 of 2 tasks completed")).toBeInTheDocument();
});

it("does not show a late response from the previous organization", async () => {
  let resolve!: (value: Response) => void;
  fetchMock.mockImplementationOnce(() => new Promise<Response>(r => { resolve = r; }));
  const props = { onProjectsChanged: vi.fn() };
  const view = render(<PlansTab {...props} />);
  org = "other-org";
  fetchMock.mockResolvedValue(json({ plans: [] }));
  view.rerender(<PlansTab {...props} />);
  await screen.findByText("No saved plans yet.");
  resolve(json({ plans: [{ id: "old", title: "Private old organization", completed: 0, total: 1 }] }));
  await waitFor(() => expect(screen.queryByText(/Private old organization/)).not.toBeInTheDocument());
});

it("keeps the same idempotency key when retrying a failed save", async () => {
  let attempts = 0;
  const ids: string[] = [];
  const previous = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (path, init) => {
    if (path === "/api/project-plans" && init?.method === "POST") {
      ids.push(JSON.parse(String(init.body)).request_id as string);
      if (++attempts === 1) return json({ detail: "Temporary failure" }, 503);
    }
    return previous(path, init);
  });
  render(<PlansTab onProjectsChanged={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Describe your idea"), { target: { value: "Build a CRM" } });
  fireEvent.click(screen.getByRole("button", { name: "Generate draft" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create project and tasks" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Create project and tasks" }));
  await screen.findByText("0 of 2 tasks completed");
  expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
});
