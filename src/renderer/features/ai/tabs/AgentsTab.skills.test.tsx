import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AgentsTab } from "./AgentsTab";
import { apiFetch } from "../../../utils/api";
import i18n from "../../../i18n";

vi.mock("../../../utils/api", () => ({ apiFetch: vi.fn(), authH: () => ({}) }));
vi.mock("../../../contexts/toast", () => ({ useToast: () => vi.fn() }));
const fetchMock = vi.mocked(apiFetch);
const ids = ["flow-project-planning", "flow-app-building", "flow-content-design", "flow-business-analysis"];

beforeEach(async () => {
  await i18n.changeLanguage("en");
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => new Response(JSON.stringify({
    skills: ids.map(id => ({ id, title: id, description: id })),
  }), { status: 200 }));
});
afterEach(cleanup);

it("saves selected skills and prevents a fourth selection", async () => {
  render(<AgentsTab agents={[]} loading={false} onRefresh={vi.fn()} onChatWith={vi.fn()} />);
  const form = i18n.getResourceBundle("en", "ai").agentsTab;
  fireEvent.click(screen.getByRole("button", { name: form.empty.newAgent }));
  await screen.findByLabelText(ids[0]);
  fireEvent.change(screen.getByLabelText(form.form.nameLabel), { target: { value: "Planner" } });
  fireEvent.change(screen.getByLabelText(form.form.systemPromptLabel), { target: { value: "Plan projects" } });
  for (const id of ids.slice(0, 3)) fireEvent.click(screen.getByLabelText(id));
  expect(screen.getByLabelText(ids[3])).toBeDisabled();
  fireEvent.click(screen.getByLabelText(ids[1]));
  expect(screen.getByLabelText(ids[3])).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: form.form.save }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/agents", expect.objectContaining({ method: "POST" })));
  const options = fetchMock.mock.calls.find(([url]) => url === "/api/agents")?.[1];
  expect(JSON.parse(String(options?.body)).skill_ids).toEqual([ids[0], ids[2]]);
});

it("shows a catalog loading error", async () => {
  fetchMock.mockResolvedValue(new Response("unavailable", { status: 503 }));
  render(<AgentsTab agents={[]} loading={false} onRefresh={vi.fn()} onChatWith={vi.fn()} />);
  const form = i18n.getResourceBundle("en", "ai").agentsTab;
  fireEvent.click(screen.getByRole("button", { name: form.empty.newAgent }));
  expect(await screen.findByRole("alert")).toHaveTextContent(form.form.skillsFailed);
});
