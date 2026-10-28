/**
 * LeadsPage — AI board, AI follow-up drafts, re-scoring and the pipeline brief.
 */
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import i18n from "../../../i18n";
import { ToastCtx } from "../../../contexts/toast";
import { apiFetch } from "../../../shared/utils/api";
import type * as ApiModule from "../../../shared/utils/api";

vi.mock("../../../shared/utils/api", async importOriginal => {
  const actual = await importOriginal<typeof ApiModule>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../../../contexts/OrgContext", () => ({
  useOrg: () => ({ loading: false, currentOrgId: "org-1", orgs: [{ id: "org-1", name: "Acme" }], createOrg: vi.fn() }),
}));

import { LeadsPage } from "../LeadsPage";

const mockFetch = vi.mocked(apiFetch);
const toast = vi.fn();
const base = { phone: null, source: "website", ai_notes: null, created_at: "2026-10-27T10:00:00Z", updated_at: "2026-10-27T10:00:00Z" };
const leads = [
  { ...base, id: "l1", name: "Sara Dental", email: "sara@example.com", status: "qualified", ai_score: 9, ai_tier: "hot", ai_notes: "Agency of 8" },
  { ...base, id: "l2", name: "Omar Studio", email: null, status: "new", ai_score: 5, ai_tier: "warm" },
  { ...base, id: "l3", name: "Lina Unscored", email: null, status: "new", ai_score: null, ai_tier: null },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
  toast.mockReset();
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (path, init) => {
    const url = String(path);
    if (url.startsWith("/api/leads?")) return json({ leads });
    if (url.startsWith("/api/automations")) return json({ items: [], total: 0 });
    if (url.endsWith("/ai-followup")) return json({ subject: "Following up on automation", body: "Hi Sara, thanks for your interest. [Your name]", sent: false });
    if (url.endsWith("/qualify")) return json({ ...leads[1], ai_score: 8, ai_tier: "hot", status: "qualified", ai_notes: "Ready to buy" });
    if (url.endsWith("/status")) return json({ ...leads[2], status: JSON.parse(String(init?.body)).status });
    if (url.endsWith("/brief")) return json({
      stats: { total: 3, open: 3, tiers: { hot: 1, warm: 1, cold: 0, unscored: 1 } },
      summary: "One hot lead is ready; call Sara today.",
      actions: [{ lead_id: "l1", name: "Sara Dental", action: "Call today" }],
    });
    return json({});
  });
});

function renderPage() {
  return render(<ToastCtx.Provider value={toast}><LeadsPage /></ToastCtx.Provider>);
}

describe("LeadsPage — AI", () => {
  it("groups leads into hot / warm / cold / unscored columns", async () => {
    renderPage();
    const hot = await screen.findByRole("region", { name: "Hot" });
    expect(within(hot).getByText("Sara Dental")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Warm" })).getByText("Omar Studio")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Not scored yet" })).getByText("Lina Unscored")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(screen.queryByRole("region", { name: "Hot" })).not.toBeInTheDocument();
    expect(screen.getByText("Omar Studio")).toBeInTheDocument();
  });

  it("drafts a follow-up with AI in an editable panel and never sends it", async () => {
    renderPage();
    const hot = await screen.findByRole("region", { name: "Hot" });
    fireEvent.click(within(hot).getByRole("button", { name: "Draft follow-up with AI" }));
    const dialog = await screen.findByRole("dialog", { name: "Follow-up for Sara Dental" });
    expect(within(dialog).getByLabelText("Subject")).toHaveValue("Following up on automation");
    expect(within(dialog).getByLabelText("Message")).toHaveValue("Hi Sara, thanks for your interest. [Your name]");
    expect(dialog).toHaveTextContent("Nothing has been sent");
    const mail = within(dialog).getByRole("link", { name: "Open in email app" });
    expect(mail.getAttribute("href")).toContain("mailto:sara@example.com?subject=Following%20up%20on%20automation");
    const call = mockFetch.mock.calls.find(([p]) => String(p) === "/api/leads/l1/ai-followup");
    expect(call?.[1]?.body).toBe(JSON.stringify({ language: "en" }));
    expect(mockFetch.mock.calls.some(([p]) => /send/.test(String(p)))).toBe(false);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("re-scores a lead with AI and moves it to its new column", async () => {
    renderPage();
    const warm = await screen.findByRole("region", { name: "Warm" });
    fireEvent.click(within(warm).getByRole("button", { name: "Re-score with AI" }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Hot" })).getByText("Omar Studio")).toBeInTheDocument());
    expect(screen.getByText("Ready to buy")).toBeInTheDocument();
  });

  it("shows the AI pipeline brief and jumps to a suggested lead", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Generate brief" }));
    await screen.findByText("One hot lead is ready; call Sara today.");
    fireEvent.click(screen.getByRole("button", { name: "Sara Dental" }));
    await waitFor(() => expect(document.getElementById("lead-l1")).toHaveClass("is-highlighted"));
  });

  it("explains AI failures instead of a generic error", async () => {
    renderPage();
    const hot = await screen.findByRole("region", { name: "Hot" });
    mockFetch.mockImplementationOnce(async () => json({ detail: "AI returned no usable result" }, 502));
    fireEvent.click(within(hot).getByRole("button", { name: "Draft follow-up with AI" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("AI couldn't produce a reliable result"), "err"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("updates status through the API and filters by status", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("Status of Lina Unscored"), { target: { value: "contacted" } });
    await waitFor(() => expect(mockFetch.mock.calls.some(([p, init]) => String(p) === "/api/leads/l3/status" && init?.body === JSON.stringify({ status: "contacted" }))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /^Contacted/ }));
    await waitFor(() => expect(screen.queryByText("Sara Dental")).not.toBeInTheDocument());
    expect(screen.getByText("Lina Unscored")).toBeInTheDocument();
  });
});
