import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const setPage = vi.fn();
const setActiveProject = vi.fn();
const apiFetchSpy = vi.fn();
let data: Record<string, unknown>;
vi.mock("../../../contexts/OrgContext", () => ({ useOrg: () => ({ loading: false, currentOrgId: "org-1" }) }));
vi.mock("../../../contexts/app", () => ({ useAppContext: () => ({ setPage, setActiveProject }) }));
vi.mock("../../../contexts/lang", () => ({ useLangContext: () => ({ lang: "en" }) }));
vi.mock("../../../utils/time", () => ({ relTime: () => "just now" }));
vi.mock("../../../utils/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetchSpy(...args),
  parseJSON: async (_r: unknown, path: string) => data[path] ?? {},
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
import { HomePage } from "../HomePage";

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  apiFetchSpy.mockResolvedValue({ ok: true });
  data = { "/api/projects": [], "/api/stats": { failed_runs: 0 } };
});

describe("work-focused home", () => {
  it("hands a typed request to the assistant and disables empty submission", async () => {
    await act(async () => { render(<HomePage />); });
    const submit = screen.getByRole("button", { name: "cc.ask.submit" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("cc.ask.label"), { target: { value: "  Plan my week  " } });
    fireEvent.click(submit);
    expect(sessionStorage.getItem("flow_assistant_prompt")).toBe("Plan my week");
    expect(setPage).toHaveBeenCalledWith("ai");
  });
  it("contains current work without catalogues, metrics, suggestions or empty status panels", async () => {
    await act(async () => { render(<HomePage />); });
    expect(screen.getAllByRole("heading").map(h => h.textContent)).toEqual(["work.title", "cc.ask.title", "work.recentProjects"]);
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(apiFetchSpy.mock.calls.map(([path]) => path)).not.toContain("/api/agentos/agents");
    expect(apiFetchSpy.mock.calls.some(([path]) => String(path).startsWith("/api/leads"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "cc.newProject" }));
    expect(setPage).toHaveBeenCalledWith("new-project");
  });
  it("shows at most five recent projects and opens the selected project", async () => {
    data['/api/projects'] = Array.from({ length: 8 }, (_, i) => ({ id: String(i), name: `Project ${i}`, created_at: `2026-11-${String(i + 1).padStart(2, '0')}T00:00:00Z` }));
    await act(async () => { render(<HomePage />); });
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByText("Project 0")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Project 7/ }));
    expect(setActiveProject).toHaveBeenCalledWith("7", "build");
  });
  it("shows actionable failures, approvals and running work without idle rows", async () => {
    data['/api/stats'] = { failed_runs: 2 };
    data['/api/workflows/approvals/pending'] = { pending: ['approval'] };
    data['/api/workflows/active'] = { runs: [{ id: '1', name: 'Current job', status: 'running' }, { id: '2', name: 'Old job', status: 'completed' }] };
    await act(async () => { render(<HomePage />); });
    expect(screen.getByText('cc.attention.title')).toBeInTheDocument();
    expect(screen.queryByText('Old job')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Current job/ }));
    expect(setPage).toHaveBeenCalledWith('automation');
    fireEvent.click(screen.getByRole('button', { name: /cc.attention.failedRuns/ }));
    expect(setPage).toHaveBeenCalledWith('runs');
  });
  it("reports a failed attention check instead of claiming all systems are healthy", async () => {
    apiFetchSpy.mockImplementation((path: string) => path === '/api/saas-factory/projects/pending-review' ? Promise.reject(new Error('offline')) : Promise.resolve({ ok: true }));
    await act(async () => { render(<HomePage />); });
    expect(screen.getByRole('alert')).toHaveTextContent('work.errors.reviews');
    expect(screen.queryByText('cc.attention.allClear')).not.toBeInTheDocument();
  });
});
