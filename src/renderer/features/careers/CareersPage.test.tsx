import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CareersPage } from "./CareersPage";
import i18n from "../../i18n";
import { apiFetch } from "../../shared/utils/api";
import type * as ApiModule from "../../shared/utils/api";

let orgId: string | null = "org-a";
vi.mock("../../contexts/OrgContext", () => ({ useOrg: () => ({ currentOrgId: orgId }) }));
vi.mock("../../shared/utils/api", async importOriginal => {
  const actual = await importOriginal<typeof ApiModule>();
  return { ...actual, apiFetch: vi.fn() };
});
const mockFetch = vi.mocked(apiFetch);
const profile = { summary: "Four years in food sales.", roles: ["Sales"], sectors: ["Food"], skills: [], languages: ["English"], cities: ["Dubai"], experience_years: 4, minimum_monthly_aed: 4000, uae_driving_license: null };
let connected = false;
const job = {
  id: "job-1", title: "Sales Executive", company: "Example Foods", location: "Dubai", url: "https://www.linkedin.com/jobs/view/4470888126/", status: "new", source: "linkedin", verification: "email_only", deadline: null,
  description: "Food sales opportunity", salary: { text: null, min: null, max: null, kind: "unknown", period: "unknown" },
  assessment: { score: 55, expired: false, strengths: [{ kind: "sectors", evidence: ["Food"] }], gaps: [], checks: ["Full requirements unverified / الشروط الكاملة غير متحققة"], next_step: "Review requirements, then apply / راجع الشروط ثم قدّم" },
};

beforeEach(async () => {
  orgId = "org-a"; connected = false; sessionStorage.clear(); window.history.replaceState(null, "", "/careers");
  await i18n.changeLanguage("en");
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (path, init) => {
    let body: unknown = {};
    if (path.endsWith("/profile")) body = profile;
    else if (path.endsWith("/jobs")) body = { items: [job] };
    else if (path.endsWith("/gmail")) body = { configured: false, connected, enabled: false, interval_hours: 24, last_sync: null, last_error: null };
    else if (path.endsWith("/import")) body = { inserted: 1, warning: null };
    else if (path.endsWith("/draft")) body = { text: "Review this draft. [Your name]", sent: false };
    void init;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
});

async function ready() {
  await screen.findByRole("heading", { name: "Sales Executive" });
}

describe("Career assistant", () => {
  it("renders Arabic labels and right-to-left layout", async () => {
    await i18n.changeLanguage("ar");
    const { container } = render(<CareersPage />);
    await screen.findByRole("heading", { name: "Sales Executive" });
    expect(screen.getByRole("heading", { name: "مساعد الوظائف" })).toBeInTheDocument();
    expect(container.querySelector("section")).toHaveAttribute("dir", "rtl");
    expect(screen.getByText("ملخص البريد فقط")).toBeInTheDocument();
  });
  it("requires a workspace and does not fetch private data without one", () => {
    orgId = null; render(<CareersPage />);
    expect(screen.getByText(/Choose a workspace/)).toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("loads private data without starting Gmail sync, and distinguishes excerpts", async () => {
    render(<CareersPage />); await ready();
    expect(screen.getByText("Email excerpt only")).toBeInTheDocument();
    expect(screen.getByText(/not acceptance probability/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect Gmail (read only)" })).toBeDisabled();
    expect(mockFetch.mock.calls.every(([path]) => !path.endsWith("/sync"))).toBe(true);
    expect(mockFetch.mock.calls.every(([, init]) => (init?.headers as Record<string, string>)["X-Organization-Id"] === "org-a")).toBe(true);
  });

  it("imports pasted alert text and displays the added count", async () => {
    render(<CareersPage />); await ready();
    fireEvent.change(screen.getByLabelText("Full message text or HTML"), { target: { value: "alert body with direct links" } });
    fireEvent.click(screen.getByRole("button", { name: "Extract jobs" }));
    await screen.findByText("Imported 1 new jobs. Existing jobs were preserved.");
    expect(mockFetch.mock.calls.find(([path]) => path.endsWith("/import"))?.[1]?.body).toContain("alert body with direct links");
  });

  it("draft generation never sends an application", async () => {
    render(<CareersPage />); await ready();
    fireEvent.click(screen.getByRole("button", { name: "Prepare application draft" }));
    expect(await screen.findByLabelText("Editable application draft")).toHaveValue("Review this draft. [Your name]");
    expect(screen.getByText(/Nothing has been sent/)).toBeInTheDocument();
    expect(mockFetch.mock.calls.some(([path]) => /send|apply/.test(path))).toBe(false);
  });

  it("changes application status through the private API", async () => {
    render(<CareersPage />); await ready();
    fireEvent.change(screen.getByLabelText("Application status"), { target: { value: "saved" } });
    await waitFor(() => expect(mockFetch.mock.calls.some(([path, init]) => path.endsWith("/status") && init?.body === JSON.stringify({ status: "saved" }))).toBe(true));
  });

  it("Gmail scheduling requires an explicit user action", async () => {
    connected = true; render(<CareersPage />); await ready();
    const checkbox = screen.getByLabelText("Enable a daily inbox check and in-app notification");
    expect(checkbox).not.toBeChecked();
    expect(mockFetch.mock.calls.some(([path]) => path.endsWith("/schedule"))).toBe(false);
    fireEvent.click(checkbox);
    await waitFor(() => expect(mockFetch.mock.calls.some(([path, init]) => path.endsWith("/schedule") && init?.body === JSON.stringify({ enabled: true, interval_hours: 24 }))).toBe(true));
  });

  it("retains imported text and surfaces server failures", async () => {
    render(<CareersPage />); await ready();
    mockFetch.mockImplementationOnce(async () => new Response(JSON.stringify({ detail: "Import unavailable" }), { status: 503, headers: { "Content-Type": "application/json" } }));
    fireEvent.change(screen.getByLabelText("Full message text or HTML"), { target: { value: "keep this text" } });
    fireEvent.click(screen.getByRole("button", { name: "Extract jobs" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Internal server error");
    expect(screen.getByLabelText("Full message text or HTML")).toHaveValue("keep this text");
  });
});
