import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { apiFetch } from "../../../utils/api";
import { JobsMonitor } from "../AgentOSPage";
import i18n from "../../../i18n";

vi.mock("../../../utils/api", () => ({ apiFetch: vi.fn() }));

beforeEach(async () => {
  await i18n.changeLanguage("en");
  vi.mocked(apiFetch).mockReset();
});
afterEach(cleanup);

it("shows the empty state, not an error screen, when the jobs API refuses", async () => {
  // A new account with no organization selected gets 400 with a JSON body.
  vi.mocked(apiFetch).mockImplementation(async () =>
    new Response(JSON.stringify({ detail: "X-Organization-Id header required" }), { status: 400 }));
  render(<JobsMonitor />);
  expect(await screen.findByText(i18n.t("agentos:jobsMonitor.empty"))).toBeInTheDocument();
});

it("shows counts when the jobs API answers", async () => {
  vi.mocked(apiFetch).mockImplementation(async (url: string) => new Response(JSON.stringify(
    String(url).endsWith("/stats")
      ? { total: 3, active: 1, dead: 0, counts: { pending: 2, running: 1 } }
      : { jobs: [] })));
  render(<JobsMonitor />);
  expect(await screen.findByText("3")).toBeInTheDocument();
});
