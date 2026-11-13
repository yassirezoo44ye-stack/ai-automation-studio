import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { apiFetch } from "../utils/api";
import { useFlowSkill } from "./useFlowSkill";
import { FlowSkillSelect } from "../ui/FlowSkillSelect";
import i18n from "../../i18n";

vi.mock("../utils/api", () => ({ apiFetch: vi.fn() }));
const skill = { id: "flow-project-planning", title: "Project planning" };
function Harness() {
  const selection = useFlowSkill();
  return <><FlowSkillSelect selection={selection} /><output data-testid="active">{selection.skillId}</output></>;
}
beforeEach(async () => {
  localStorage.clear();
  await i18n.changeLanguage("en");
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({ skills: [skill] })));
});
afterEach(cleanup);

it("restores a chosen skill in a new session and can disable it", async () => {
  const first = render(<Harness />);
  await screen.findByRole("option", { name: skill.title });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: skill.id } });
  expect(screen.getByTestId("active")).toHaveTextContent(skill.id);
  first.unmount();
  render(<Harness />);
  await screen.findByRole("option", { name: skill.title });
  expect(screen.getByRole("combobox")).toHaveValue(skill.id);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
  expect(localStorage.getItem("flow.skill-selection.v1")).toBe('""');
});

it("ignores malformed and unknown saved selections", async () => {
  localStorage.setItem("flow.skill-selection.v1", '{bad');
  const first = render(<Harness />);
  await screen.findByRole("option", { name: skill.title });
  expect(screen.getByRole("combobox")).toHaveValue("");
  first.unmount();
  localStorage.setItem("flow.skill-selection.v1", '"../unknown"');
  render(<Harness />);
  await screen.findByRole("option", { name: skill.title });
  expect(screen.getByTestId("active")).toBeEmptyDOMElement();
});

it("updates from another browser tab", async () => {
  render(<Harness />);
  await screen.findByRole("option", { name: skill.title });
  localStorage.setItem("flow.skill-selection.v1", JSON.stringify(skill.id));
  fireEvent(window, new StorageEvent("storage", { key: "flow.skill-selection.v1" }));
  expect(screen.getByRole("combobox")).toHaveValue(skill.id);
});
