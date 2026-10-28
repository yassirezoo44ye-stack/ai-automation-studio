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
    else if (path.endsWith("/ai-draft")) body = { text: "AI draft for Sales Executive. [Your name]", sent: false, ai: true };
    else if (path.endsWith("/draft")) body = { text: "Review this draft. [Your name]", sent: false };
    else if (path.endsWith("/profile/extract")) body = { profile: { ...profile, summary: "Sales executive, FMCG.", roles: ["Sales Executive"], skills: ["Zoho Books"], languages: ["Arabic"], experience_years: 5 } };
    else if (path.endsWith("/fit")) body = { ai_fit: { summary: "Strong FMCG match.", strengths: ["Food sales"], gaps: ["Zoho level unclear"], questions: ["Team size?"], stale: false } };
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

  it("AI draft opens in an editable panel, never sends, and can fall back to the template", async () => {
    render(<CareersPage />); await ready();
    fireEvent.click(screen.getByRole("button", { name: "Write application with AI" }));
    expect(await screen.findByLabelText("Editable application draft")).toHaveValue("AI draft for Sales Executive. [Your name]");
    expect(screen.getByRole("dialog")).toHaveTextContent(/Nothing has been sent/);
    expect(mockFetch.mock.calls.some(([path]) => path.endsWith("/jobs/job-1/ai-draft"))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Use basic template instead" }));
    await waitFor(() => expect(screen.getByLabelText("Editable application draft")).toHaveValue("Review this draft. [Your name]"));
    expect(mockFetch.mock.calls.some(([path]) => /send|apply/.test(path))).toBe(false);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("fills the profile from a CV with AI for review, without saving it", async () => {
    render(<CareersPage />); await ready();
    const button = screen.getByRole("button", { name: "Fill profile with AI" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("CV or experience"), { target: { value: "Sales Executive at Example Foods. Zoho Books. Arabic." } });
    fireEvent.click(button);
    await screen.findByText("AI suggestions added. Review them, then save your profile.");
    const extract = mockFetch.mock.calls.find(([path]) => path.endsWith("/profile/extract"));
    expect(JSON.parse(String(extract?.[1]?.body))).toEqual({ text: "Sales Executive at Example Foods. Zoho Books. Arabic." });
    // Existing values are kept and AI values are added as removable chips.
    expect(screen.getByRole("button", { name: "Remove Sales" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Zoho Books" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Arabic" })).toBeInTheDocument();
    expect(screen.getByLabelText("Years of experience")).toHaveValue(5);
    expect(mockFetch.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("edits list fields as chips and saves them as arrays", async () => {
    render(<CareersPage />); await ready();
    const skills = screen.getByLabelText("Skills");
    fireEvent.change(skills, { target: { value: "Excel" } });
    fireEvent.keyDown(skills, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Remove Dubai" }));
    fireEvent.click(screen.getByRole("button", { name: "Save profile & rank jobs" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const saved = JSON.parse(String(mockFetch.mock.calls.find(([, init]) => init?.method === "PUT")?.[1]?.body));
    expect(saved.skills).toEqual(["Excel"]);
    expect(saved.cities).toEqual([]);
  });

  it("runs an AI fit analysis in the page language and shows it on the job", async () => {
    render(<CareersPage />); await ready();
    fireEvent.click(screen.getByRole("button", { name: "Analyse fit with AI" }));
    await screen.findByText("Strong FMCG match.");
    expect(screen.getByText("Zoho level unclear")).toBeInTheDocument();
    const call = mockFetch.mock.calls.find(([path]) => path.endsWith("/jobs/job-1/fit"));
    expect(call?.[1]?.body).toBe(JSON.stringify({ language: "en" }));
    expect(screen.getByRole("button", { name: "Refresh analysis" })).toBeInTheDocument();
  });

  it("explains AI failures instead of showing a generic server error", async () => {
    render(<CareersPage />); await ready();
    mockFetch.mockImplementationOnce(async () => new Response(JSON.stringify({ detail: "AI returned no usable result" }), { status: 502, headers: { "Content-Type": "application/json" } }));
    fireEvent.click(screen.getByRole("button", { name: "Analyse fit with AI" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("AI couldn't produce a reliable result");
  });

  it("asks the server to use AI for unsupported text and reports AI-found jobs", async () => {
    render(<CareersPage />); await ready();
    mockFetch.mockImplementationOnce(async () => new Response(JSON.stringify({ inserted: 2, warning: null, method: "ai" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    fireEvent.change(screen.getByLabelText("Full message text or HTML"), { target: { value: "We are hiring a driver and a cashier" } });
    fireEvent.click(screen.getByRole("button", { name: "Extract jobs" }));
    await screen.findByText("AI found and added 2 new jobs from your text.");
    expect(JSON.parse(String(mockFetch.mock.calls.find(([path]) => path.endsWith("/import"))?.[1]?.body)).use_ai).toBe(true);
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
